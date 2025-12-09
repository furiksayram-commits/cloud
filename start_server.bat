@echo off
chcp 65001 > nul
echo ====================================
echo   Домашнее Облако - Запуск сервера
echo ====================================
echo.
echo Сервер будет доступен по адресам:
echo.
echo   Локально:  http://127.0.0.1:3000
echo   В сети:    http://192.168.229.110:3000
echo.
echo Для остановки нажмите Ctrl+C
echo ====================================
echo.

cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
    echo Виртуальное окружение не найдено!
    echo Создаем виртуальное окружение...
    python -m venv .venv
    echo Устанавливаем зависимости...
    .venv\Scripts\python.exe -m pip install -r requirements.txt
)

.venv\Scripts\python.exe app.py

pause
