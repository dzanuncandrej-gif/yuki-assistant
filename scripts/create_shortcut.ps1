# Ярлыки Юки: рабочий стол, меню «Пуск», автозапуск.
#   .\scripts\create_shortcut.ps1                создать ярлыки на рабочем столе и в «Пуске»
#   .\scripts\create_shortcut.ps1 -Autostart     плюс автозапуск при входе в систему
#   .\scripts\create_shortcut.ps1 -NoStartMenu   только рабочий стол
#   .\scripts\create_shortcut.ps1 -Remove        удалить все ярлыки Юки
param(
    [switch]$Autostart,
    [switch]$NoStartMenu,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$names = @("Юки.lnk", "Джарвис.lnk")  # второе — прежнее имя проекта, такие ярлыки убираем
$folders = @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"),
             [Environment]::GetFolderPath("Startup"))

function Remove-Links([string[]]$which) {
    $removed = 0
    foreach ($folder in $folders) {
        foreach ($name in $which) {
            $path = Join-Path $folder $name
            if (Test-Path $path) { Remove-Item $path -Force; $removed++ }
        }
    }
    return $removed
}

if ($Remove) {
    $removed = Remove-Links $names
    if ($removed -eq 0) { Write-Host "Ярлыков Юки не найдено." -ForegroundColor DarkGray }
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
    & (Join-Path $root ".venv\Scripts\python.exe") (Join-Path $root "scripts\make_icon.py")
}

function New-YukiShortcut([string]$path) {
    $parent = Split-Path -Parent $path
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $pythonw
    $link.Arguments = "main.py"
    $link.WorkingDirectory = $root
    $link.Description = "Юки — голосовой ИИ-ассистент"
    if (Test-Path $icon) { $link.IconLocation = "$icon,0" }
    $link.Save()
    Write-Host "Ярлык создан: $path" -ForegroundColor Green
}

Remove-Links @("Джарвис.lnk") | Out-Null
New-YukiShortcut (Join-Path $folders[0] "Юки.lnk")
if (-not $NoStartMenu) { New-YukiShortcut (Join-Path $folders[1] "Юки.lnk") }
if ($Autostart) {
    New-YukiShortcut (Join-Path $folders[2] "Юки.lnk")
    Write-Host "Юки будет запускаться при входе в систему." -ForegroundColor DarkGray
}
