@echo off
chcp 65001 >nul
setlocal

rem Запуск веб-консультанта Hattatsu Group одним щелчком.
rem
rem Скрипт нарочно проверяет всё сам и объясняет, чего не хватает. Человек,
rem которому это переслали, не должен разбираться в устройстве проекта: он
rem запускает файл и либо видит сайт, либо читает, что доустановить.

cd /d "%~dp0\.."
title Hattatsu — виртуальный консультант

echo.
echo   HATTATSU GROUP — виртуальный консультант
echo   ========================================
echo.

rem --- 1. Python ---
set PY=.venv\Scripts\python.exe
if not exist "%PY%" (
    where python >nul 2>&1
    if errorlevel 1 (
        echo   [!] Python не найден.
        echo       Установите Python 3.11 или новее: https://python.org/downloads
        echo       При установке отметьте "Add Python to PATH".
        echo.
        pause
        exit /b 1
    )
    echo   Создаю окружение и ставлю зависимости, это разово...
    python -m venv .venv || goto :fail
    "%PY%" -m pip install --quiet --upgrade pip
    "%PY%" -m pip install --quiet -r web\requirements.txt || goto :fail
    echo   Готово.
    echo.
)

rem --- 2. Ollama ---
curl -s -o nul --max-time 3 http://127.0.0.1:11434/api/tags
if errorlevel 1 (
    echo   [!] Ollama не отвечает на 127.0.0.1:11434
    echo.
    echo       1. Установите: https://ollama.com/download
    echo       2. Запустите Ollama ^(значок в трее^)
    echo       3. Скачайте модели ^(около 5.4 ГБ, разово^):
    echo.
    echo             ollama pull qwen2.5:7b
    echo             ollama pull bge-m3
    echo.
    pause
    exit /b 1
)

rem --- 3. модели на месте? ---
curl -s --max-time 5 http://127.0.0.1:11434/api/tags | findstr /C:"qwen2.5:7b" >nul
if errorlevel 1 (
    echo   [!] Нет модели qwen2.5:7b. Выполните:  ollama pull qwen2.5:7b
    echo.
    pause
    exit /b 1
)
curl -s --max-time 5 http://127.0.0.1:11434/api/tags | findstr /C:"bge-m3" >nul
if errorlevel 1 (
    echo   [!] Нет модели bge-m3. Выполните:  ollama pull bge-m3
    echo.
    pause
    exit /b 1
)

rem --- 4. запуск ---
echo   Поднимаю консультанта. Первый запуск греется около минуты.
echo   Когда откроется браузер — самурай справа внизу, щёлкните по нему.
echo.
echo   Остановить: закройте это окно.
echo.

start "" http://127.0.0.1:8770
"%PY%" -X utf8 -m web.server --character hattatsu --port 8770

goto :eof

:fail
echo.
echo   [!] Не удалось поставить зависимости. Проверьте подключение к интернету.
echo.
pause
exit /b 1
