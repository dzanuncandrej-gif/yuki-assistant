# Запуск Джарвиса.
#   .\start.ps1                      десктопное приложение
#   .\start.ps1 -Silent              без окна консоли (живёт в трее)
#   .\start.ps1 -Web                 старый режим: сервер плюс браузер
#   .\start.ps1 -Devices             список аудиоустройств
#   .\start.ps1 -InstallShortcut     ярлыки на рабочем столе и в меню «Пуск»
#   .\start.ps1 -InstallShortcut -Autostart   плюс запуск при входе в систему
#   .\start.ps1 -UninstallShortcut   удалить все ярлыки
#   .\start.ps1 -Admin               с правами администратора (нужно, если антивирус
#                                    блокирует ввод в мессенджеры и защищённые окна)
param(
    [switch]$Silent,
    [switch]$Web,
    [switch]$Devices,
    [switch]$InstallShortcut,
    [switch]$UninstallShortcut,
    [switch]$Autostart,
    [switch]$Shortcut,          # старое имя -InstallShortcut, оставлено для совместимости
    [switch]$Admin
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$venvPythonw = Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe"
$shortcutScript = Join-Path $PSScriptRoot "scripts\create_shortcut.ps1"

if ($UninstallShortcut) {
    & powershell -ExecutionPolicy Bypass -File $shortcutScript -Remove
    exit $LASTEXITCODE
}

if (-not (Test-Path $venvPython)) {
    Write-Host "Окружение не найдено. Сначала: .\install.ps1" -ForegroundColor Red
    exit 1
}

if ($InstallShortcut -or $Shortcut) {
    if ($Autostart) {
        & powershell -ExecutionPolicy Bypass -File $shortcutScript -Autostart
    } else {
        & powershell -ExecutionPolicy Bypass -File $shortcutScript
    }
    exit $LASTEXITCODE
}

if ($Devices) { & $venvPython main.py --devices; exit $LASTEXITCODE }
if ($Web) { & $venvPython run.py; exit $LASTEXITCODE }

if ($Admin) {
    Start-Process -FilePath $venvPython -ArgumentList "main.py" -WorkingDirectory $PSScriptRoot -Verb RunAs
    Write-Host "Джарвис запущен с правами администратора." -ForegroundColor Green
    exit 0
}

# Ollama держит модель агента. Если служба не поднята — поднимаем в фоне.
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    try { $null = Invoke-WebRequest "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 -UseBasicParsing }
    catch {
        Write-Host "==> Поднимаю Ollama" -ForegroundColor DarkGray
        Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
        Start-Sleep -Seconds 2
    }
}

if ($Silent) {
    Start-Process -FilePath $venvPythonw -ArgumentList "main.py" -WorkingDirectory $PSScriptRoot
    Write-Host "Джарвис запущен в фоне — иконка в трее." -ForegroundColor Green
    exit 0
}

& $venvPython main.py
