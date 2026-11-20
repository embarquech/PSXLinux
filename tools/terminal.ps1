# Terminal série pour la console PSXLinux (COM14, 115200 8N1, sans écho local : Linux fait l'écho).
# Usage : powershell -ExecutionPolicy Bypass -File PSXLinux\terminal.ps1 [-Port COM14]
# Quitter : Ctrl+Q   (Ctrl+C est envoyé à Linux)
param([string]$Port = "COM14", [int]$Baud = 115200)

$sp = New-Object System.IO.Ports.SerialPort $Port, $Baud, ([System.IO.Ports.Parity]::None), 8, ([System.IO.Ports.StopBits]::One)
$sp.Handshake = [System.IO.Ports.Handshake]::None
$sp.RtsEnable = $true          # la PS1 n'émet que si le PC lève RTS
$sp.DtrEnable = $true
$sp.ReadTimeout = 10
$sp.Encoding = [System.Text.Encoding]::GetEncoding(28591)   # octets bruts
try { $sp.Open() } catch { Write-Host "Impossible d'ouvrir $Port : $($_.Exception.Message)" -ForegroundColor Red; Write-Host "(ferme la fenêtre nops qui l'utilise encore)"; exit 1 }

[Console]::TreatControlCAsInput = $true
$Host.UI.RawUI.WindowTitle = "PSXLinux - $Port $Baud (Ctrl+Q pour quitter)"
Write-Host "Connecté à $Port ($Baud 8N1). Ctrl+Q pour quitter. Appuie sur Entrée pour avoir le prompt." -ForegroundColor Cyan

$buf = New-Object byte[] 4096
try {
    while ($true) {
        $n = $sp.BytesToRead
        if ($n -gt 0) {
            $n = $sp.Read($buf, 0, [Math]::Min($n, $buf.Length))
            [Console]::Write([System.Text.Encoding]::GetEncoding(28591).GetString($buf, 0, $n))
        }
        while ([Console]::KeyAvailable) {
            $k = [Console]::ReadKey($true)
            if ($k.Key -eq 'Q' -and ($k.Modifiers -band [ConsoleModifiers]::Control)) { return }
            $out = switch ($k.Key) {
                'Enter'      { [byte[]](13) }
                'Backspace'  { [byte[]](127) }
                'UpArrow'    { [byte[]](27, 91, 65) }
                'DownArrow'  { [byte[]](27, 91, 66) }
                'RightArrow' { [byte[]](27, 91, 67) }
                'LeftArrow'  { [byte[]](27, 91, 68) }
                default      { if ([int]$k.KeyChar -ne 0) { [byte[]]([int]$k.KeyChar -band 0xFF) } else { $null } }
            }
            if ($out) { $sp.Write($out, 0, $out.Length) }
        }
        if ($n -le 0) { Start-Sleep -Milliseconds 5 }
    }
} finally {
    $sp.Close()
    [Console]::TreatControlCAsInput = $false
    Write-Host "`nDéconnecté." -ForegroundColor Cyan
}
