# Ярлыки Джарвиса: рабочий стол, меню «Пуск», автозапуск.
#   .\scripts\create_shortcut.ps1                создать ярлыки на рабочем столе и в «Пуске»
#   .\scripts\create_shortcut.ps1 -Autostart     плюс автозапуск при входе в систему
#   .\scripts\create_shortcut.ps1 -NoStartMenu   только рабочий стол
#   .\scripts\create_shortcut.ps1 -Remove        удалить все ярлыки Джарвиса
param(
    [switch]$Autostart,
    [switch]$NoStartMenu,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$linkName = "Джарвис.lnk"

$desktopLink = Join-Path ([Environment]::GetFolderPath("Desktop")) $linkName
$startMenuLink = Join-Path ([Environment]::GetFolderPath("Programs")) $linkName
$startupLink = Join-Path ([Environment]::GetFolderPath("Startup")) $linkName

if ($Remove) {
    $removed = 0
    foreach ($path in @($desktopLink, $startMenuLink, $startupLink)) {
        if (Test-Path $path) {
            Remove-Item $path -Force
            Write-Host "Удалён: $path" -ForegroundColor DarkGray
            $removed++
        }
    }
    if ($removed -eq 0) { Write-Host "Ярлыков Джарвиса не найдено." -ForegroundColor DarkGray }
    else { Write-Host "Удалено ярлыков: $removed" -ForegroundColor Green }
    exit 0
}

$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) {
    Write-Host "Окружение не найдено. Сначала: .\install.ps1" -ForegroundColor Red
    exit 1
}

$icon = Join-Path $root "assets\yuki.ico"
if (-not (Test-Path $icon)) {
    Write-Host "==> Рисую иконку" -ForegroundColor Cyan
    & (Join-Path $root ".venv\Scripts\python.exe") (Join-Path $root "scripts\make_icon.py")
}

function New-JarvisShortcut([string]$path) {
    $parent = Split-Path -Parent $path
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }

    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $pythonw
    $link.Arguments = "main.py"
    $link.WorkingDirectory = $root
    $link.Description = "Джарвис — голосовой ИИ-агент"
    if (Test-Path $icon) { $link.IconLocation = "$icon,0" }
    $link.Save()
    Write-Host "Ярлык создан: $path" -ForegroundColor Green
}

New-JarvisShortcut $desktopLink
if (-not $NoStartMenu) { New-JarvisShortcut $startMenuLink }
if ($Autostart) {
    New-JarvisShortcut $startupLink
    Write-Host "Джарвис будет запускаться при входе в систему." -ForegroundColor DarkGray
}
