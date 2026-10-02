# OCR-сервер для Юки: встроенное распознавание текста Windows (Windows.Media.Ocr).
#
# Живёт одним процессом весь сеанс: читает из stdin путь к картинке, отвечает
# одной строкой JSON со строками текста и их прямоугольниками в пикселях
# картинки. Компоненты подписаны Microsoft, поэтому «Умная защита приложений»
# их не блокирует, а видеопамять не занимается вовсе.

$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.Encoding]::UTF8
[Console]::OutputEncoding = [Text.Encoding]::UTF8

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
$null = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType = WindowsRuntime]

$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
} | Select-Object -First 1

function MediaInfo($session) {
    $props = Await ($session.TryGetMediaPropertiesAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties])
    $status = $session.GetPlaybackInfo().PlaybackStatus.ToString()
    return @{ title = [string]$props.Title; artist = [string]$props.Artist; app = [string]$session.SourceAppUserModelId; status = $status }
}

# Управление тем, что сейчас играет: «следующий», «предыдущий», «пауза».
# Ответ — что играло до и после, чтобы Юки не говорила «переключила» вслепую.
function MediaCommand($action) {
    $manager = Await ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
    $session = $manager.GetCurrentSession()
    if (-not $session) { return @{ ok = $false; error = 'nothing' } }
    $before = MediaInfo $session
    if ($action -eq 'info') { return @{ ok = $true; before = $before; after = $before; done = $true } }
    $done = switch ($action) {
        'next' { Await ($session.TrySkipNextAsync()) ([bool]) }
        'previous' { Await ($session.TrySkipPreviousAsync()) ([bool]) }
        'play_pause' { Await ($session.TryTogglePlayPauseAsync()) ([bool]) }
        default { $false }
    }
    $after = $before
    for ($i = 0; $i -lt 12; $i++) {
        Start-Sleep -Milliseconds 150
        $current = $manager.GetCurrentSession()
        if ($current) { $after = MediaInfo $current }
        if ($action -ne 'next' -and $action -ne 'previous') { break }
        if ($after.title -ne $before.title) { break }
    }
    return @{ ok = $true; done = [bool]$done; before = $before; after = $after }
}

function Await($operation, [Type]$type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($operation))
    $null = $task.Wait(15000)
    return $task.Result
}

$engines = @{}
foreach ($tag in @('ru', 'en-US')) {
    try {
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($tag))
        if ($engine) { $engines[$tag] = $engine }
    } catch { }
}
[Console]::Out.WriteLine((ConvertTo-Json @{ ready = $true; languages = @($engines.Keys) } -Compress))
[Console]::Out.Flush()

while ($true) {
    $line = [Console]::In.ReadLine()
    if ($null -eq $line) { break }
    $request = $line.Trim()
    if (-not $request) { continue }
    $stream = $null
    if ($request.StartsWith('media|')) {
        try {
            $reply = MediaCommand ($request.Substring(6))
            [Console]::Out.WriteLine((ConvertTo-Json $reply -Compress -Depth 4))
        } catch {
            [Console]::Out.WriteLine((ConvertTo-Json @{ ok = $false; error = $_.Exception.Message } -Compress))
        }
        [Console]::Out.Flush()
        continue
    }
    try {
        $parts = $request.Split('|')
        $path = $parts[0]
        $lang = if ($parts.Count -gt 1 -and $engines.ContainsKey($parts[1])) { $parts[1] } else { 'ru' }
        if (-not $engines.ContainsKey($lang)) { $lang = @($engines.Keys)[0] }
        $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
        $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
        $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $result = Await ($engines[$lang].RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
        $lines = @()
        foreach ($row in $result.Lines) {
            $left = 1e9; $top = 1e9; $right = 0; $bottom = 0
            foreach ($word in $row.Words) {
                $r = $word.BoundingRect
                if ($r.X -lt $left) { $left = $r.X }
                if ($r.Y -lt $top) { $top = $r.Y }
                if ($r.X + $r.Width -gt $right) { $right = $r.X + $r.Width }
                if ($r.Y + $r.Height -gt $bottom) { $bottom = $r.Y + $r.Height }
            }
            $lines += @{ t = $row.Text; r = @([int]$left, [int]$top, [int]$right, [int]$bottom) }
        }
        [Console]::Out.WriteLine((ConvertTo-Json @{ ok = $true; lines = $lines } -Compress -Depth 4))
    } catch {
        [Console]::Out.WriteLine((ConvertTo-Json @{ ok = $false; error = $_.Exception.Message } -Compress))
    } finally {
        if ($stream) { $stream.Dispose() }
        [Console]::Out.Flush()
    }
}
