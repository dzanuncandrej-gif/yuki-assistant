# Установка Юки. Запуск:  powershell -ExecutionPolicy Bypass -File install.ps1
# Скрипт ничего не удаляет и ставит всё только в папку проекта (.venv) — кроме Ollama,
# которую предлагает установить через winget, если её нет.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }
function Warn($text) { Write-Host "!!  $text" -ForegroundColor Yellow }
function Fail($text) { Write-Host "XX  $text" -ForegroundColor Red; exit 1 }
# необязательный шаг: если он сломался, установка идёт дальше
function Optional([string]$title, [scriptblock]$action) {
    Step $title
    try { & $action } catch { Warn "$title — не получилось ($($_.Exception.Message)). Это не мешает запуску." }
}

# ---------------------------------------------------------------- проверки до установки
Step "Проверяю компьютер"
$freeGb = [math]::Round((Get-PSDrive (Get-Location).Drive.Name).Free / 1GB, 1)
if ($freeGb -lt 12) { Fail "Нужно хотя бы 12 ГБ свободного места на диске, сейчас $freeGb ГБ." }

$python = $null; $pyArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($version in "3.12", "3.11") {
        & py "-$version" -c "import sys" 2>$null
        if ($LASTEXITCODE -eq 0) { $python = "py"; $pyArgs = @("-$version"); break }
    }
}
if (-not $python -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $ver = & python -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>$null
    if ($ver -in "3.11", "3.12") { $python = "python" }
}
if (-not $python) {
    Fail "Нужен Python 3.12 (или 3.11). Скачай с https://www.python.org/downloads/ и при установке отметь «Add python.exe to PATH»."
}

if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    $gpu = (& nvidia-smi --query-gpu=name,memory.total --format=csv,noheader) -join ", "
    Write-Host "    Видеокарта: $gpu" -ForegroundColor DarkGray
} else {
    Warn "Видеокарта NVIDIA не найдена. Юки будет работать, но модель на процессоре отвечает в разы медленнее."
}

# Системный SOCKS-прокси ломает pip. Если рядом есть HTTP-прокси — используем его.
$sys = Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings" -ErrorAction SilentlyContinue
if ($sys.ProxyEnable -eq 1 -and "$($sys.ProxyServer)" -match "socks" -and -not $env:HTTPS_PROXY) {
    foreach ($port in 10809, 10808, 8080) {
        if (Test-NetConnection 127.0.0.1 -Port $port -InformationLevel Quiet -WarningAction SilentlyContinue) {
            $env:HTTP_PROXY = "http://127.0.0.1:$port"; $env:HTTPS_PROXY = "http://127.0.0.1:$port"
            Write-Host "    Использую HTTP-прокси 127.0.0.1:$port" -ForegroundColor DarkGray
            break
        }
    }
}

# ---------------------------------------------------------------- окружение и зависимости
if (-not (Test-Path ".venv")) {
    Step "Создаю виртуальное окружение (.venv)"
    & $python @pyArgs -m venv .venv
}
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

Step "Обновляю pip"
& $venvPython -m pip install --upgrade pip --quiet
Step "Ставлю зависимости (5–15 минут, качается около 2 ГБ)"
& $venvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { Fail "pip не смог поставить зависимости — посмотри ошибку выше." }

if (-not (Test-Path "config.json")) {
    Copy-Item "config.example.json" "config.json"
    Write-Host "    Создал config.json из примера — настройки потом меняются в меню Юки." -ForegroundColor DarkGray
}

Optional "Качаю модель распознавания речи" { & $venvPython scripts\download_whisper.py }
Optional "Качаю офлайн-голос (Silero) на случай, если нет интернета" { & $venvPython scripts\download_voice_model.py }
Optional "Качаю запасные голоса Piper" { & $venvPython scripts\download_piper_voice.py }
Optional "Качаю модели распознавания лиц" { & $venvPython scripts\download_face_models.py }
Optional "Рисую иконку и ставлю ярлыки (рабочий стол и «Пуск»)" {
    & $venvPython scripts\make_icon.py
    & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "scripts\create_shortcut.ps1")
}

# ---------------------------------------------------------------- модель (Ollama)
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Warn "Ollama не найдена — без неё Юки понимает только прямые команды."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        $answer = Read-Host "Установить Ollama через winget? (д/н)"
        if ($answer -match "^(д|y)") {
            winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
            $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
        }
    } else {
        Warn "Установи её с https://ollama.com и запусти install.ps1 ещё раз."
    }
}
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    $model = (Get-Content config.json -Raw -Encoding UTF8 | ConvertFrom-Json).brain.model
    $installed = (& ollama list) -join "`n"
    if ($installed -notmatch [regex]::Escape($model)) {
        Step "Качаю модель $model (около 6 ГБ): она и думает, и видит экран"
        & ollama pull $model
    } else {
        Write-Host "    Модель $model уже установлена" -ForegroundColor DarkGray
    }
}

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) { Copy-Item ".env.example" ".env" }

Write-Host ""
Write-Host "Готово. Запуск: ярлык «Юки» на рабочем столе или .\start.ps1" -ForegroundColor Green
Write-Host "При первом запуске Юки сама проверит микрофон, голос и модель и проведёт обучение." -ForegroundColor DarkGray
Write-Host "Если что-то не работает: data\yuki.log и раздел «Если не работает» в README." -ForegroundColor DarkGray
