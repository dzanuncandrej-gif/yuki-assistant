# Установка окружения Джарвиса. Запуск: powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = "py"
$pyArgs = @("-3.12")
if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    $python = "python"
    $pyArgs = @()
}

# Системный SOCKS-прокси ломает pip (нет PySocks). Если рядом есть HTTP-прокси — используем его.
$sys = Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings" -ErrorAction SilentlyContinue
if ($sys.ProxyEnable -eq 1 -and "$($sys.ProxyServer)" -match "socks" -and -not $env:HTTPS_PROXY) {
    foreach ($port in 10809, 10808, 8080) {
        if (Test-NetConnection 127.0.0.1 -Port $port -InformationLevel Quiet -WarningAction SilentlyContinue) {
            $env:HTTP_PROXY = "http://127.0.0.1:$port"
            $env:HTTPS_PROXY = "http://127.0.0.1:$port"
            Write-Host "==> Использую HTTP-прокси 127.0.0.1:$port" -ForegroundColor DarkGray
            break
        }
    }
}

if (-not (Test-Path ".venv")) {
    Write-Host "==> Создаю виртуальное окружение (.venv)" -ForegroundColor Cyan
    & $python @pyArgs -m venv .venv
}

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

Write-Host "==> Обновляю pip" -ForegroundColor Cyan
& $venvPython -m pip install --upgrade pip --quiet

Write-Host "==> Ставлю зависимости (несколько минут, качается ~400 МБ)" -ForegroundColor Cyan
& $venvPython -m pip install -r requirements.txt

Write-Host "==> Качаю основную модель голоса (Silero, ~38 МБ)" -ForegroundColor Cyan
& $venvPython scripts\download_voice_model.py

Write-Host "==> Качаю запасные голоса Piper" -ForegroundColor Cyan
& $venvPython scripts\download_piper_voice.py

Write-Host "==> Качаю модели распознавания лиц" -ForegroundColor Cyan
& $venvPython scripts\download_face_models.py

Write-Host "==> Качаю модель распознавания речи" -ForegroundColor Cyan
& $venvPython scripts\download_whisper.py

Write-Host "==> Рисую иконку и ставлю ярлыки (рабочий стол и «Пуск»)" -ForegroundColor Cyan
& $venvPython scripts\make_icon.py
& powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "scripts\create_shortcut.ps1")

# Модель-агент. Без неё работают только прямые команды.
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    $model = (Get-Content config.json -Raw | ConvertFrom-Json).brain.model
    $installed = (& ollama list) -join "`n"
    if ($installed -notmatch [regex]::Escape($model)) {
        Write-Host "==> Качаю модель агента $model (около 5 ГБ)" -ForegroundColor Cyan
        & ollama pull $model
    } else {
        Write-Host "==> Модель $model уже установлена" -ForegroundColor DarkGray
    }
    if ($installed -notmatch "llava") {
        Write-Host "==> Качаю модель зрения llava (нужна для «посмотри на экран»)" -ForegroundColor Cyan
        & ollama pull llava
    }
} else {
    Write-Host "!! Ollama не найдена. Установи с https://ollama.com — без неё агент не работает." -ForegroundColor Yellow
}

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host "==> Создал .env — впиши туда город и ключи, если нужно" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Готово. Запуск: ярлык «Джарвис» на рабочем столе или .\start.ps1" -ForegroundColor Green
Write-Host "Список микрофонов:  .\start.ps1 -Devices" -ForegroundColor DarkGray
