$log = "C:\Users\pasto\bust-base\scripts\autostart_install.log"
Start-Transcript -Path $log -Force
$BASE = "C:\Users\pasto\bust-base"

$tasks = @(
  @{ Name = "GHSS-Technitium"; Tr = "$BASE\scripts\start_technitium.bat" },
  @{ Name = "GHSS-Caddy";      Tr = "$BASE\scripts\start_caddy.bat" },
  @{ Name = "GHSS-Portal";     Tr = "$BASE\scripts\start_lan.bat" }
)

foreach ($t in $tasks) {
    Write-Host "Creating task: $($t.Name)"
    $out = schtasks /create /tn "$($t.Name)" /tr "`"$($t.Tr)`"" /sc onstart /ru SYSTEM /rl highest /f 2>&1
    Write-Host "  $out"
}

Write-Host "=== Verification ==="
$query = schtasks /query /fo csv 2>&1
$query | Write-Host
Stop-Transcript