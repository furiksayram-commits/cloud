from flask import Flask, render_template, request, send_file, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename
from io import BytesIO
import os
import shutil
from datetime import datetime
import mimetypes
import re
import hashlib
from PIL import Image
from PIL.ExifTags import TAGS
from PIL.Image import Exif

# OpenCV опционально (для миниатюр видео)
try:
    import cv2
    import numpy as np
    OPENCV_AVAILABLE = True
    print("✅ OpenCV установлен - миниатюры видео доступны")
except ImportError:
    OPENCV_AVAILABLE = False
    print("⚠️  OpenCV не установлен. Миниатюры видео будут недоступны.")

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500 MB для больших файлов

# Конфигурация
UPLOAD_FOLDER = 'storage'
THUMBNAIL_CACHE_FOLDER = '.thumbcache'
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 
                      'xls', 'xlsx', 'zip', 'rar', 'mp3', 'mp4', 'avi', 'mkv', 
                      'py', 'js', 'html', 'css', 'json', 'xml'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Создаем папки
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

if not os.path.exists(THUMBNAIL_CACHE_FOLDER):
    os.makedirs(THUMBNAIL_CACHE_FOLDER, exist_ok=True)
elif not os.path.isdir(UPLOAD_FOLDER):
    # Если storage существует но это не папка (например, файл или битая ссылка)
    print(f"⚠️  ВНИМАНИЕ: {UPLOAD_FOLDER} существует но это не папка!")
    print(f"Пожалуйста, удалите или переименуйте: rm {UPLOAD_FOLDER}")

def safe_filename(filename):
    """Безопасное имя файла с поддержкой кириллицы"""
    # Убираем опасные символы, но оставляем кириллицу и основные символы
    filename = filename.strip()
    # Заменяем запрещенные символы в Windows
    forbidden_chars = r'[<>:"/\\|?*]'
    filename = re.sub(forbidden_chars, '_', filename)
    # Убираем точки в начале и конце
    filename = filename.strip('.')
    # Если имя пустое после очистки, используем значение по умолчанию
    if not filename:
        filename = 'file'
    return filename

def rename_by_date_if_long(filepath, max_length=30):
    """Переименовать файл по дате съемки если имя слишком длинное
    
    Args:
        filepath: путь к файлу
        max_length: максимальная длина имени (без расширения)
    
    Returns:
        новый путь к файлу (или старый, если не переименован)
    """
    try:
        filename = os.path.basename(filepath)
        name_without_ext, ext = os.path.splitext(filename)
        
        # Проверяем длину имени (без расширения)
        if len(name_without_ext) <= max_length:
            return filepath
        
        print(f"📏 Длинное имя ({len(name_without_ext)} символов): {filename}")
        
        # Получаем дату из EXIF
        date_obj = get_image_date(filepath)
        
        # Форматируем имя: DDMMYYYY
        new_name = date_obj.strftime('%d%m%Y')
        
        # Добавляем расширение
        new_filename = f"{new_name}{ext}"
        
        # Путь к новому файлу
        directory = os.path.dirname(filepath)
        new_filepath = os.path.join(directory, new_filename)
        
        # Если файл с таким именем уже существует, добавляем счетчик
        counter = 1
        while os.path.exists(new_filepath):
            new_filename = f"{new_name}_{counter}{ext}"
            new_filepath = os.path.join(directory, new_filename)
            counter += 1
        
        # Переименовываем файл
        os.rename(filepath, new_filepath)
        print(f"✅ Переименовано: {filename} → {new_filename}")
        
        return new_filepath
    
    except Exception as e:
        print(f"❌ Ошибка переименования {filepath}: {e}")
        return filepath

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_folder_size(folder_path):
    """Получить размер папки (сумма всех файлов внутри)"""
    total_size = 0
    try:
        for dirpath, dirnames, filenames in os.walk(folder_path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                try:
                    total_size += os.path.getsize(filepath)
                except:
                    pass
    except:
        pass
    return total_size

def get_file_info(filepath):
    """Получить информацию о файле"""
    stat = os.stat(filepath)
    is_dir = os.path.isdir(filepath)
    
    # Для папок считаем общий размер всех файлов внутри
    if is_dir:
        size = get_folder_size(filepath)
    else:
        size = stat.st_size
    
    # Определить тип файла
    name = os.path.basename(filepath)
    is_image = not is_dir and name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'))
    is_video = not is_dir and name.lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.webm'))
    
    return {
        'name': name,
        'size': size,
        'size_formatted': format_size(size),
        'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
        'modified_timestamp': stat.st_mtime,
        'is_dir': is_dir,
        'is_image': is_image,
        'is_video': is_video
    }

def format_size(size):
    """Форматировать размер файла"""
    for unit in ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} ПБ"

def get_image_date(filepath):
    """Извлечь дату съемки из EXIF данных изображения"""
    try:
        image = Image.open(filepath)
        
        # Пробуем разные способы получения EXIF
        exif_data = None
        
        # Способ 1: getexif() (современный)
        try:
            exif_data = image.getexif()
        except:
            pass
        
        # Способ 2: _getexif() (устаревший, но иногда работает)
        if not exif_data:
            try:
                exif_data = image._getexif()
            except:
                pass
        
        if exif_data:
            # Ищем дату съемки - DateTimeOriginal имеет приоритет
            datetime_original = None
            datetime_digitized = None
            datetime_standard = None
            
            # Коды EXIF тегов
            DATETIME_ORIGINAL = 36867  # DateTimeOriginal
            DATETIME_DIGITIZED = 36868  # DateTimeDigitized
            DATETIME = 306  # DateTime
            
            # Пробуем по кодам тегов
            if isinstance(exif_data, dict):
                for tag_id, value in exif_data.items():
                    if isinstance(tag_id, int):
                        if tag_id == DATETIME_ORIGINAL:
                            datetime_original = value
                        elif tag_id == DATETIME_DIGITIZED:
                            datetime_digitized = value
                        elif tag_id == DATETIME:
                            datetime_standard = value
                    else:
                        # Если tag_id это уже строка
                        tag = str(tag_id)
                        if 'DateTimeOriginal' in tag:
                            datetime_original = value
                        elif 'DateTimeDigitized' in tag:
                            datetime_digitized = value
                        elif tag == 'DateTime':
                            datetime_standard = value
            else:
                # Для объекта Exif используем get()
                try:
                    datetime_original = exif_data.get(DATETIME_ORIGINAL)
                    datetime_digitized = exif_data.get(DATETIME_DIGITIZED)
                    datetime_standard = exif_data.get(DATETIME)
                except:
                    pass
            
            # Приоритет: DateTimeOriginal > DateTimeDigitized > DateTime
            date_str = datetime_original or datetime_digitized or datetime_standard
            
            if date_str:
                try:
                    # Формат: '2024:12:06 10:30:45' или '2024-12-06 10:30:45'
                    date_str = str(date_str).strip()
                    
                    # Пробуем разные форматы
                    for fmt in ['%Y:%m:%d %H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y:%m:%d', '%Y-%m-%d']:
                        try:
                            date_obj = datetime.strptime(date_str, fmt)
                            print(f"✓ EXIF дата для {os.path.basename(filepath)}: {date_obj.strftime('%Y-%m-%d %H:%M:%S')} (из EXIF)")
                            return date_obj
                        except:
                            continue
                    
                    print(f"✗ Не удалось распарсить дату: {date_str}")
                except Exception as e:
                    print(f"✗ Ошибка парсинга даты {date_str}: {e}")
            else:
                print(f"✗ EXIF данные найдены, но нет полей с датой для {os.path.basename(filepath)}")
        else:
            print(f"✗ Нет EXIF данных для {os.path.basename(filepath)}")
            
    except Exception as e:
        print(f"✗ Ошибка чтения изображения {os.path.basename(filepath)}: {e}")
    
    # Если EXIF не найден, используем дату модификации файла
    fallback_date = datetime.fromtimestamp(os.path.getmtime(filepath))
    print(f"⚠ Используется дата файла для {os.path.basename(filepath)}: {fallback_date.strftime('%Y-%m-%d %H:%M:%S')}")
    return fallback_date

def get_photo_destination_path(filepath):
    """Определить путь для сохранения фото: Фото/Год/Месяц"""
    date_obj = get_image_date(filepath)
    year = date_obj.strftime('%Y')
    
    # Русские названия месяцев
    month_names_ru = {
        '01': 'Январь', '02': 'Февраль', '03': 'Март', '04': 'Апрель',
        '05': 'Май', '06': 'Июнь', '07': 'Июль', '08': 'Август',
        '09': 'Сентябрь', '10': 'Октябрь', '11': 'Ноябрь', '12': 'Декабрь'
    }
    
    month_num = date_obj.strftime('%m')
    month_name = month_names_ru.get(month_num, date_obj.strftime('%B'))
    
    result_path = os.path.join('Фото', year, month_name)
    print(f"Путь назначения для {os.path.basename(filepath)}: {result_path}")
    
    return result_path

def get_video_destination_path(filepath):
    """Определить путь для сохранения видео: Видео/Год/Месяц"""
    # Используем дату модификации файла
    date_obj = datetime.fromtimestamp(os.path.getmtime(filepath))
    year = date_obj.strftime('%Y')
    
    # Русские названия месяцев
    month_names_ru = {
        '01': 'Январь', '02': 'Февраль', '03': 'Март', '04': 'Апрель',
        '05': 'Май', '06': 'Июнь', '07': 'Июль', '08': 'Август',
        '09': 'Сентябрь', '10': 'Октябрь', '11': 'Ноябрь', '12': 'Декабрь'
    }
    
    month_num = date_obj.strftime('%m')
    month_name = month_names_ru.get(month_num, date_obj.strftime('%B'))
    
    result_path = os.path.join('Видео', year, month_name)
    print(f"Путь назначения для {os.path.basename(filepath)}: {result_path}")
    
    return result_path

@app.route('/')
def index():
    return redirect(url_for('browse', path=''))

@app.route('/browse/')
@app.route('/browse/<path:path>')
def browse(path=''):
    """Просмотр файлов и папок"""
    full_path = os.path.join(app.config['UPLOAD_FOLDER'], path)
    
    if not os.path.exists(full_path):
        flash('Папка не найдена!', 'error')
        return redirect(url_for('index'))
    
    if os.path.isfile(full_path):
        return send_file(full_path, as_attachment=True)
    
    items = []
    try:
        for item in os.listdir(full_path):
            item_path = os.path.join(full_path, item)
            info = get_file_info(item_path)
            info['path'] = os.path.join(path, item).replace('\\', '/')
            items.append(info)
    except PermissionError:
        flash('Нет доступа к этой папке!', 'error')
        return redirect(url_for('index'))
    
    # Функция для определения приоритета папок
    def get_folder_priority(item):
        if not item['is_dir']:
            return (1, -item.get('modified_timestamp', 0))  # Файлы после папок, по дате
        
        # Приоритет для специальных папок
        folder_order = {'Фото': 0, 'Видео': 1, 'Документы': 2}
        name = item['name']
        if name in folder_order:
            return (0, folder_order[name], '')
        else:
            return (0, 999, name.lower())  # Остальные папки по алфавиту
    
    # Сортировка: сначала папки в определённом порядке, потом файлы (по дате, новые первые)
    items.sort(key=get_folder_priority)
    
    # Путь для навигации
    breadcrumbs = []
    parent_path = ''
    if path:
        parts = path.split('/')
        current = ''
        for i, part in enumerate(parts):
            current = os.path.join(current, part).replace('\\', '/')
            breadcrumbs.append({'name': part, 'path': current})
        
        # Родительская папка (для кнопки "Назад")
        if len(parts) > 1:
            parent_path = '/'.join(parts[:-1])
        # Если только одна папка, то родитель - корень
    
    # Подсчет статистики (включая размер папок)
    total_size = sum(item['size'] for item in items)
    
    return render_template('index.html', 
                         items=items, 
                         current_path=path,
                         parent_path=parent_path,
                         breadcrumbs=breadcrumbs,
                         total_size=format_size(total_size),
                         total_files=len([i for i in items if not i['is_dir']]),
                         total_folders=len([i for i in items if i['is_dir']]))

@app.route('/upload', methods=['POST'])
def upload_file():
    """Загрузка файлов"""
    if 'file' not in request.files:
        flash('Файл не выбран!', 'error')
        return redirect(request.referrer)
    
    files = request.files.getlist('file')
    current_path = request.form.get('current_path', '')
    upload_path = os.path.join(app.config['UPLOAD_FOLDER'], current_path)
    
    uploaded_count = 0
    photo_count = 0
    video_count = 0
    
    for file in files:
        if file and file.filename:
            filename = safe_filename(file.filename)
            if filename:
                # Проверяем тип файла
                _, ext = os.path.splitext(filename.lower())
                is_image = ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']
                is_video = ext in ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm']
                
                if is_image:
                    # Сохраняем временно для анализа EXIF
                    temp_path = os.path.join(upload_path, filename)
                    file.save(temp_path)
                    
                    # Переименовываем если имя длинное (> 20 символов)
                    temp_path = rename_by_date_if_long(temp_path, max_length=20)
                    filename = os.path.basename(temp_path)  # Обновляем имя файла
                    
                    # Определяем путь для сохранения: Фото/Год/Месяц
                    photo_dest_path = get_photo_destination_path(temp_path)
                    full_dest_path = os.path.join(app.config['UPLOAD_FOLDER'], photo_dest_path)
                    
                    # Создаем структуру папок если её нет
                    os.makedirs(full_dest_path, exist_ok=True)
                    
                    # Перемещаем файл в нужную папку
                    final_path = os.path.join(full_dest_path, filename)
                    
                    # Если файл уже существует, добавляем номер
                    if os.path.exists(final_path):
                        name, ext = os.path.splitext(filename)
                        counter = 1
                        while os.path.exists(final_path):
                            final_path = os.path.join(full_dest_path, f"{name}_{counter}{ext}")
                            counter += 1
                    
                    shutil.move(temp_path, final_path)
                    photo_count += 1
                    uploaded_count += 1
                    
                elif is_video:
                    # Сохраняем временно
                    temp_path = os.path.join(upload_path, filename)
                    file.save(temp_path)
                    
                    # Переименовываем если имя длинное (> 20 символов)
                    temp_path = rename_by_date_if_long(temp_path, max_length=20)
                    filename = os.path.basename(temp_path)  # Обновляем имя файла
                    
                    # Определяем путь для сохранения: Видео/Год/Месяц
                    video_dest_path = get_video_destination_path(temp_path)
                    full_dest_path = os.path.join(app.config['UPLOAD_FOLDER'], video_dest_path)
                    
                    # Создаем структуру папок если её нет
                    os.makedirs(full_dest_path, exist_ok=True)
                    
                    # Перемещаем файл в нужную папку
                    final_path = os.path.join(full_dest_path, filename)
                    
                    # Если файл уже существует, добавляем номер
                    if os.path.exists(final_path):
                        name, ext = os.path.splitext(filename)
                        counter = 1
                        while os.path.exists(final_path):
                            final_path = os.path.join(full_dest_path, f"{name}_{counter}{ext}")
                            counter += 1
                    
                    shutil.move(temp_path, final_path)
                    video_count += 1
                    uploaded_count += 1
                    
                else:
                    # Обычные файлы сохраняем в текущую папку
                    filepath = os.path.join(upload_path, filename)
                    file.save(filepath)
                    uploaded_count += 1
    
    if photo_count > 0 or video_count > 0:
        message_parts = []
        if photo_count > 0:
            message_parts.append(f'Фото: {photo_count}')
        if video_count > 0:
            message_parts.append(f'Видео: {video_count}')
        flash(f'Загружено файлов: {uploaded_count}. Автоматически отсортировано - {", ".join(message_parts)}', 'success')
    else:
        flash(f'Успешно загружено файлов: {uploaded_count}', 'success')
    
    return redirect(url_for('browse', path=current_path))


@app.route('/upload_direct', methods=['POST'])
def upload_direct():
    """Загрузка файлов без автосортировки (в текущую папку)"""
    if 'file' not in request.files:
        flash('Файл не выбран!', 'error')
        return redirect(request.referrer)
    
    files = request.files.getlist('file')
    current_path = request.form.get('current_path', '')
    upload_path = os.path.join(app.config['UPLOAD_FOLDER'], current_path)
    
    # Создаем папку если её нет
    os.makedirs(upload_path, exist_ok=True)
    
    uploaded_count = 0
    
    for file in files:
        if file and file.filename:
            filename = safe_filename(file.filename)
            if filename:
                filepath = os.path.join(upload_path, filename)
                
                # Если файл уже существует, добавляем номер
                if os.path.exists(filepath):
                    name, ext = os.path.splitext(filename)
                    counter = 1
                    while os.path.exists(filepath):
                        filepath = os.path.join(upload_path, f"{name}_{counter}{ext}")
                        counter += 1
                
                file.save(filepath)
                
                # Переименовываем если имя длинное (для изображений и видео)
                _, ext = os.path.splitext(filename.lower())
                if ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm']:
                    filepath = rename_by_date_if_long(filepath, max_length=20)
                
                uploaded_count += 1
    
    flash(f'Успешно загружено файлов: {uploaded_count}', 'success')
    return redirect(url_for('browse', path=current_path))


@app.route('/create_folder', methods=['POST'])
def create_folder():
    """Создание новой папки"""
    folder_name = request.form.get('folder_name', '').strip()
    current_path = request.form.get('current_path', '')
    
    if not folder_name:
        flash('Введите имя папки!', 'error')
        return redirect(url_for('browse', path=current_path))
    
    folder_name = safe_filename(folder_name)
    new_folder_path = os.path.join(app.config['UPLOAD_FOLDER'], current_path, folder_name)
    
    if os.path.exists(new_folder_path):
        flash('Папка с таким именем уже существует!', 'error')
    else:
        os.makedirs(new_folder_path)
        flash(f'Папка "{folder_name}" создана!', 'success')
    
    return redirect(url_for('browse', path=current_path))

@app.route('/delete/<path:path>')
def delete_item(path):
    """Удаление файла или папки"""
    full_path = os.path.join(app.config['UPLOAD_FOLDER'], path)
    
    if not os.path.exists(full_path):
        flash('Файл или папка не найдены!', 'error')
        return redirect(url_for('index'))
    
    try:
        if os.path.isdir(full_path):
            shutil.rmtree(full_path)
            flash('Папка удалена!', 'success')
        else:
            os.remove(full_path)
            flash('Файл удален!', 'success')
    except Exception as e:
        flash(f'Ошибка при удалении: {str(e)}', 'error')
    
    # Вернуться в родительскую папку
    parent_path = os.path.dirname(path).replace('\\', '/')
    return redirect(url_for('browse', path=parent_path))

@app.route('/download/<path:path>')
def download_file(path):
    """Скачивание файла"""
    full_path = os.path.join(app.config['UPLOAD_FOLDER'], path)
    
    if not os.path.exists(full_path) or os.path.isdir(full_path):
        flash('Файл не найден!', 'error')
        return redirect(url_for('index'))
    
    return send_file(full_path, as_attachment=True)

@app.route('/storage_info')
def storage_info():
    """Информация о хранилище"""
    total_size = 0
    file_count = 0
    folder_count = 0
    
    for root, dirs, files in os.walk(app.config['UPLOAD_FOLDER']):
        folder_count += len(dirs)
        for file in files:
            file_count += 1
            filepath = os.path.join(root, file)
            try:
                total_size += os.path.getsize(filepath)
            except:
                pass
    
    return jsonify({
        'total_size': format_size(total_size),
        'file_count': file_count,
        'folder_count': folder_count
    })

@app.route('/search')
def search():
    """Поиск файлов по имени"""
    query = request.args.get('q', '').lower().strip()
    current_path = request.args.get('path', '')
    
    if not query:
        return redirect(url_for('browse', path=current_path))
    
    results = []
    search_path = os.path.join(app.config['UPLOAD_FOLDER'], current_path)
    
    for root, dirs, files in os.walk(search_path):
        for item in dirs + files:
            if query in item.lower():
                item_path = os.path.join(root, item)
                relative_path = os.path.relpath(item_path, app.config['UPLOAD_FOLDER'])
                info = get_file_info(item_path)
                info['path'] = relative_path.replace('\\', '/')
                results.append(info)
    
    # Сортировка: сначала папки, потом файлы
    results.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
    
    return render_template('search_results.html', 
                         items=results, 
                         query=query,
                         current_path=current_path)

@app.route('/api/search')
def api_search():
    """API для поиска файлов (возвращает JSON)"""
    query = request.args.get('q', '').lower().strip()
    current_path = request.args.get('path', '')
    
    if not query:
        return jsonify([])
    
    results = []
    search_path = os.path.join(app.config['UPLOAD_FOLDER'], current_path)
    
    for root, dirs, files in os.walk(search_path):
        for item in dirs + files:
            if query in item.lower():
                item_path = os.path.join(root, item)
                relative_path = os.path.relpath(item_path, app.config['UPLOAD_FOLDER'])
                info = get_file_info(item_path)
                info['path'] = relative_path.replace('\\', '/')
                results.append(info)
    
    # Сортировка: сначала папки, потом файлы
    results.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
    
    return jsonify(results)

@app.route('/rename', methods=['POST'])
def rename_item():
    """Переименование файла или папки"""
    old_path = request.form.get('old_path', '')
    new_name = request.form.get('new_name', '').strip()
    
    if not old_path or not new_name:
        flash('Неверные параметры!', 'error')
        return redirect(url_for('index'))
    
    old_full_path = os.path.join(app.config['UPLOAD_FOLDER'], old_path)
    
    if not os.path.exists(old_full_path):
        flash('Файл или папка не найдены!', 'error')
        return redirect(url_for('index'))
    
    # Если это файл (не папка), сохраняем расширение
    if os.path.isfile(old_full_path):
        old_name = os.path.basename(old_path)
        _, old_ext = os.path.splitext(old_name)
        # Убираем расширение из нового имени, если пользователь его добавил
        new_name_without_ext, new_ext = os.path.splitext(new_name)
        # Используем старое расширение
        if new_ext:
            new_name = new_name_without_ext + old_ext
        else:
            new_name = new_name + old_ext
    
    new_name = safe_filename(new_name)
    parent_dir = os.path.dirname(old_full_path)
    new_full_path = os.path.join(parent_dir, new_name)
    
    if os.path.exists(new_full_path):
        flash('Файл или папка с таким именем уже существует!', 'error')
    else:
        try:
            os.rename(old_full_path, new_full_path)
            flash(f'Успешно переименовано в "{new_name}"!', 'success')
        except Exception as e:
            flash(f'Ошибка при переименовании: {str(e)}', 'error')
    
    parent_path = os.path.dirname(old_path).replace('\\', '/')
    return redirect(url_for('browse', path=parent_path))

@app.route('/preview/<path:path>')
def preview_file(path):
    """Предварительный просмотр файла (для изображений)"""
    full_path = os.path.join(app.config['UPLOAD_FOLDER'], path)
    
    if not os.path.exists(full_path) or os.path.isdir(full_path):
        flash('Файл не найден!', 'error')
        return redirect(url_for('index'))
    
    # Определяем MIME тип для изображений и видео
    file_ext = os.path.splitext(path)[1].lower()
    if file_ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']:
        mimetype = 'image/jpeg' if file_ext in ['.jpg', '.jpeg'] else f'image/{file_ext[1:]}'
        return send_file(full_path, mimetype=mimetype)
    elif file_ext == '.mp4':
        return send_file(full_path, mimetype='video/mp4', conditional=True)
    elif file_ext == '.mov':
        return send_file(full_path, mimetype='video/mp4', conditional=True)  # Пробуем как MP4
    elif file_ext == '.avi':
        return send_file(full_path, mimetype='video/x-msvideo', conditional=True)
    elif file_ext == '.mkv':
        return send_file(full_path, mimetype='video/x-matroska', conditional=True)
    elif file_ext == '.webm':
        return send_file(full_path, mimetype='video/webm', conditional=True)
    
    # Для остальных файлов
    return send_file(full_path)

@app.route('/thumb/<path:path>')
def get_thumbnail(path):
    """Получить миниатюру изображения (200x200px) или первый кадр видео с кешированием на диск"""
    full_path = os.path.join(app.config['UPLOAD_FOLDER'], path)
    
    if not os.path.exists(full_path) or os.path.isdir(full_path):
        return '', 404
    
    file_ext = os.path.splitext(path)[1].lower()
    
    # Создаем хеш для имени кеша
    cache_hash = hashlib.md5(full_path.encode()).hexdigest()
    cache_filename = f"{cache_hash}.jpg"
    cache_path = os.path.join(THUMBNAIL_CACHE_FOLDER, cache_filename)
    
    # Если кеш существует и оригинал не изменился - возвращаем кеш
    if os.path.exists(cache_path):
        file_mtime = os.path.getmtime(full_path)
        cache_mtime = os.path.getmtime(cache_path)
        if cache_mtime >= file_mtime:
            return send_file(cache_path, mimetype='image/jpeg')
    
    # Для видео - извлекаем первый кадр (если OpenCV доступен)
    if file_ext in ['.mp4', '.avi', '.mkv', '.mov', '.webm', '.flv', '.wmv']:
        if not OPENCV_AVAILABLE:
            # Если OpenCV нет - возвращаем SVG иконку видео
            svg_icon = '''<svg width="200" height="200" xmlns="http://www.w3.org/2000/svg">
                <rect width="200" height="200" fill="#2c3e50"/>
                <polygon points="70,50 70,150 150,100" fill="#3498db"/>
                <text x="100" y="180" font-family="Arial" font-size="14" fill="#ecf0f1" text-anchor="middle">VIDEO</text>
            </svg>'''
            return svg_icon, 200, {'Content-Type': 'image/svg+xml'}
        
        try:
            # Открываем видео
            cap = cv2.VideoCapture(full_path)
            
            # Читаем первый кадр
            ret, frame = cap.read()
            cap.release()
            
            if ret:
                # Конвертируем BGR (OpenCV) в RGB (PIL)
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                
                # Создаем PIL Image из numpy array
                img = Image.fromarray(frame_rgb)
                
                # Создаем миниатюру
                img.thumbnail((200, 200), Image.Resampling.LANCZOS)
                
                # Сохраняем в кеш
                img.save(cache_path, 'JPEG', quality=60, optimize=True)
                
                return send_file(cache_path, mimetype='image/jpeg')
            else:
                print(f"Не удалось прочитать кадр из видео: {path}")
                # Возвращаем SVG иконку при ошибке
                svg_icon = '''<svg width="200" height="200" xmlns="http://www.w3.org/2000/svg">
                    <rect width="200" height="200" fill="#2c3e50"/>
                    <polygon points="70,50 70,150 150,100" fill="#3498db"/>
                    <text x="100" y="180" font-family="Arial" font-size="14" fill="#ecf0f1" text-anchor="middle">VIDEO</text>
                </svg>'''
                return svg_icon, 200, {'Content-Type': 'image/svg+xml'}
        except Exception as e:
            print(f"Ошибка извлечения кадра из видео {path}: {e}")
            # Возвращаем SVG иконку при ошибке
            svg_icon = '''<svg width="200" height="200" xmlns="http://www.w3.org/2000/svg">
                <rect width="200" height="200" fill="#2c3e50"/>
                <polygon points="70,50 70,150 150,100" fill="#3498db"/>
                <text x="100" y="180" font-family="Arial" font-size="14" fill="#ecf0f1" text-anchor="middle">VIDEO</text>
            </svg>'''
            return svg_icon, 200, {'Content-Type': 'image/svg+xml'}
    
    # Для изображений - обычная миниатюра
    if file_ext not in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']:
        return '', 404
    
    try:
        # Генерируем миниатюру
        with Image.open(full_path) as img:
            # Конвертируем в RGB если нужно
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Применяем EXIF ориентацию
            try:
                for orientation in TAGS.keys():
                    if TAGS[orientation] == 'Orientation':
                        break
                exif = img._getexif()
                if exif is not None:
                    orientation_value = exif.get(orientation)
                    if orientation_value == 3:
                        img = img.rotate(180, expand=True)
                    elif orientation_value == 6:
                        img = img.rotate(270, expand=True)
                    elif orientation_value == 8:
                        img = img.rotate(90, expand=True)
            except:
                pass
            
            # Создаем миниатюру (200x200px для экономии места)
            img.thumbnail((200, 200), Image.Resampling.LANCZOS)
            
            # Сохраняем в кеш с низким качеством (меньше размер)
            img.save(cache_path, 'JPEG', quality=60, optimize=True)
            
            return send_file(cache_path, mimetype='image/jpeg')
    except Exception as e:
        print(f"Ошибка при генерации миниатюры {path}: {e}")
        return '', 500

@app.route('/category/<category>/<path:path>')
@app.route('/category/<category>')
@app.route('/category/<category>/')
def browse_by_category(category, path=''):
    """Просмотр файлов по категориям (фото, видео, документы)"""
    full_path = os.path.join(app.config['UPLOAD_FOLDER'], path)
    
    if not os.path.exists(full_path):
        flash('Папка не найдена!', 'error')
        return redirect(url_for('index'))
    
    # Определяем расширения для категорий
    category_extensions = {
        'image': ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'],
        'video': ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv'],
        'document': ['.doc', '.docx', '.pdf', '.txt', '.xls', '.xlsx', '.ppt', '.pptx']
    }
    
    if category not in category_extensions:
        flash('Неизвестная категория!', 'error')
        return redirect(url_for('browse', path=path))
    
    extensions = category_extensions[category]
    items = []
    
    # Рекурсивный поиск файлов по категории
    def collect_files(directory, relative_path=''):
        try:
            for item in os.listdir(directory):
                item_path = os.path.join(directory, item)
                
                if os.path.isdir(item_path):
                    # Рекурсивно обходим вложенные папки
                    new_relative = os.path.join(relative_path, item).replace('\\', '/')
                    collect_files(item_path, new_relative)
                else:
                    # Проверяем расширение файла
                    _, ext = os.path.splitext(item.lower())
                    if ext in extensions:
                        info = get_file_info(item_path)
                        file_relative_path = os.path.join(relative_path, item).replace('\\', '/')
                        info['path'] = file_relative_path
                        items.append(info)
        except PermissionError:
            pass
    
    collect_files(full_path, path)
    
    # Сортировка по имени
    items.sort(key=lambda x: x['name'].lower())
    
    # Путь для навигации
    breadcrumbs = []
    if path:
        parts = path.split('/')
        current = ''
        for part in parts:
            current = os.path.join(current, part).replace('\\', '/')
            breadcrumbs.append({'name': part, 'path': current})
    
    # Подсчет статистики
    total_size = sum(item['size'] for item in items)
    
    # Названия категорий
    category_names = {
        'image': 'Фото',
        'video': 'Видео',
        'document': 'Документы'
    }
    
    return render_template('index.html', 
                         items=items, 
                         current_path=path,
                         breadcrumbs=breadcrumbs,
                         total_size=format_size(total_size),
                         total_files=len(items),
                         total_folders=0,
                         category=category,
                         category_name=category_names.get(category, category))

# Создание PNG иконок из SVG при первом запуске
def create_pwa_icons():
    """Создать иконки для PWA"""
    static_dir = os.path.join(os.path.dirname(__file__), 'static')
    icon_192_path = os.path.join(static_dir, 'icon-192.png')
    icon_512_path = os.path.join(static_dir, 'icon-512.png')
    
    # Если иконки уже существуют, пропускаем
    if os.path.exists(icon_192_path) and os.path.exists(icon_512_path):
        return
    
    try:
        from PIL import Image, ImageDraw, ImageFont
        
        # Создаём иконку 192x192
        img_192 = Image.new('RGB', (192, 192), color='#1a1a1a')
        draw_192 = ImageDraw.Draw(img_192)
        
        # Рисуем облако (простая иконка)
        try:
            font_192 = ImageFont.truetype("arial.ttf", 100)
        except:
            font_192 = ImageFont.load_default()
        
        draw_192.text((96, 96), "☁", fill='#4CAF50', font=font_192, anchor='mm')
        img_192.save(icon_192_path, 'PNG')
        
        # Создаём иконку 512x512
        img_512 = Image.new('RGB', (512, 512), color='#1a1a1a')
        draw_512 = ImageDraw.Draw(img_512)
        
        try:
            font_512 = ImageFont.truetype("arial.ttf", 280)
        except:
            font_512 = ImageFont.load_default()
        
        draw_512.text((256, 256), "☁", fill='#4CAF50', font=font_512, anchor='mm')
        img_512.save(icon_512_path, 'PNG')
        
        print(f"✓ PWA иконки созданы: {icon_192_path}, {icon_512_path}")
    except Exception as e:
        print(f"⚠ Ошибка создания иконок: {e}")

if __name__ == '__main__':
    # Создать иконки для PWA
    create_pwa_icons()
    
    # Определить режим работы (production на мобильных для скорости)
    import sys
    debug_mode = '--debug' in sys.argv
    
    print(f"🚀 Запуск сервера в режиме: {'DEBUG' if debug_mode else 'PRODUCTION'}")
    if not debug_mode:
        print("💡 Для включения debug режима добавьте флаг: python app.py --debug")

    # Автоматический вывод локального IP
    import socket
    def get_local_ip():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('10.255.255.255', 1))
            IP = s.getsockname()[0]
        except Exception:
            IP = '127.0.0.1'
        finally:
            s.close()
        return IP
    local_ip = get_local_ip()
    print(f"🌐 Откройте в браузере: http://localhost:3000")
    print(f"🌐 Или с другого устройства: http://{local_ip}:3000")

    # Запуск сервера (доступен в локальной сети)
    app.run(host='0.0.0.0', port=3000, debug=debug_mode, threaded=True)
