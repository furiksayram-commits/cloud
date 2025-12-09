#!/data/data/com.termux/files/usr/bin/bash

# Автоматический скрипт установки Home Cloud на Termux
# Использование: bash install-termux.sh

echo "🚀 Установка Home Cloud на Termux..."
echo ""

# Обновление пакетов
echo "📦 Обновление пакетов..."
pkg update -y && pkg upgrade -y

# Установка зависимостей
echo "📦 Установка зависимостей..."
pkg install -y python git clang libjpeg-turbo libpng zlib termux-api

# Настройка доступа к хранилищу
echo ""
echo "📁 ВАЖНО: Сейчас откроется диалог разрешений Android"
echo "   ОБЯЗАТЕЛЬНО нажмите 'Разрешить' / 'Allow'!"
echo ""
echo "Нажмите Enter чтобы продолжить..."
read
termux-setup-storage
sleep 3

# Проверка что storage доступен
if [ ! -d ~/storage/shared ]; then
    echo ""
    echo "❌ ОШИБКА: ~/storage/shared не найден!"
    echo "   Похоже вы не дали разрешение на доступ к хранилищу."
    echo ""
    echo "Выполните вручную:"
    echo "   termux-setup-storage"
    echo "   (и дайте разрешение в диалоге Android)"
    echo ""
    exit 1
fi

echo "✅ Доступ к хранилищу получен!"
sleep 1

# Клонирование проекта
echo "📥 Клонирование проекта..."
cd ~
if [ -d "cloud" ]; then
    echo "⚠️  Папка cloud уже существует. Удалить? (y/n)"
    read -r answer
    if [ "$answer" = "y" ]; then
        rm -rf cloud
        git clone https://github.com/furiksayram-commits/cloud.git
    fi
else
    git clone https://github.com/furiksayram-commits/cloud.git
fi

cd ~/cloud

# Настройка хранилища ПЕРЕД установкой Python
echo "💾 Настройка хранилища..."

# Проверяем доступные варианты и создаём папку
if [ -w ~/storage/downloads ]; then
    echo "✅ Используем ~/storage/downloads/HomeCloud"
    mkdir -p ~/storage/downloads/HomeCloud
    STORAGE_PATH=~/storage/downloads/HomeCloud
elif [ -w ~/storage/documents ]; then
    echo "✅ Используем ~/storage/documents/HomeCloud"
    mkdir -p ~/storage/documents/HomeCloud
    STORAGE_PATH=~/storage/documents/HomeCloud
else
    echo "⚠️  Нет доступа к storage, используем внутреннюю память Termux"
    mkdir -p ~/cloud/storage
    STORAGE_PATH=~/cloud/storage
fi

# Удалить старую ссылку если есть
rm -f ~/cloud/storage

# Создать ссылку только если используем внешний storage
if [ "$STORAGE_PATH" != "~/cloud/storage" ]; then
    ln -sf "$STORAGE_PATH" ~/cloud/storage
fi

echo "✅ Storage настроен: $STORAGE_PATH"

# Создание виртуального окружения
echo "🐍 Создание виртуального окружения Python..."
python -m venv .venv

# Активация виртуального окружения
echo "🔧 Установка Python пакетов..."
source .venv/bin/activate

# Обновить pip и setuptools
pip install --upgrade pip setuptools wheel

# Установить Pillow с правильными флагами для Termux
echo "📦 Установка Pillow..."
CFLAGS="-I$PREFIX/include" LDFLAGS="-L$PREFIX/lib" pip install --no-cache-dir pillow

# Установить остальные зависимости
pip install flask werkzeug

# Установить Gunicorn для высокой производительности
echo "🚀 Установка Gunicorn (для быстрой работы)..."
pip install gunicorn

# Создание папки для хранилища (уже должна быть создана выше)
echo "💾 Проверка хранилища..."
if [ ! -d ~/cloud/storage ]; then
    echo "⚠️  Storage не найден, создаём..."
    mkdir -p ~/storage/shared/HomeCloud
    rm -f ~/cloud/storage
    ln -sf ~/storage/shared/HomeCloud ~/cloud/storage
fi

# Создание скрипта запуска
echo "📝 Создание скрипта запуска..."
cat > ~/cloud/start.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
cd ~/cloud
source .venv/bin/activate
termux-wake-lock
echo "🚀 Запуск Home Cloud сервера (FAST MODE с Gunicorn)..."
echo "📱 Откройте браузер: http://localhost:3000"
echo "🌐 Или с другого устройства: http://$(termux-wifi-connectioninfo | grep -oP '(?<="ip": ")[^"]*'):3000"
echo ""
gunicorn -w 4 -b 0.0.0.0:3000 --timeout 120 --access-logfile - app:app
EOF

chmod +x ~/cloud/start.sh

# Создание скрипта запуска с Flask (для отладки)
cat > ~/cloud/start-debug.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
cd ~/cloud
source .venv/bin/activate
termux-wake-lock
echo "🐛 Запуск в режиме отладки (медленный)..."
echo "📱 Откройте браузер: http://localhost:3000"
echo ""
python app.py --debug
EOF

chmod +x ~/cloud/start-debug.sh

# Создание скрипта автозапуска
echo "🔄 Настройка автозапуска..."
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/start-cloud.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock
cd ~/cloud
source .venv/bin/activate
gunicorn -w 4 -b 0.0.0.0:3000 --timeout 120 --daemon app:app > ~/cloud/server.log 2>&1
EOF

chmod +x ~/.termux/boot/start-cloud.sh

# Создание скрипта остановки
cat > ~/cloud/stop.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
echo "🛑 Остановка Home Cloud сервера..."
pkill -f "gunicorn.*app:app"
pkill -f "python app.py"
termux-wake-unlock
echo "✅ Сервер остановлен"
EOF

chmod +x ~/cloud/stop.sh

# Завершение
echo ""
echo "✅ Установка завершена!"
echo ""
echo "📋 Команды для работы:"
echo "   ~/cloud/start.sh       - Запустить сервер (БЫСТРО с Gunicorn)"
echo "   ~/cloud/start-debug.sh - Запустить в режиме отладки (медленно)"
echo "   ~/cloud/stop.sh        - Остановить сервер"
echo ""
echo "🌐 После запуска откройте в браузере:"
echo "   http://localhost:3000"
echo ""
echo "💡 Для автозапуска при загрузке телефона установите Termux:Boot из F-Droid"
echo ""
echo "⚡ Установлен Gunicorn - работа в 3-5 раз быстрее стандартного Flask!"
echo ""
echo "🚀 Хотите запустить сервер сейчас? (y/n)"
read -r answer
if [ "$answer" = "y" ]; then
    ~/cloud/start.sh
fi
