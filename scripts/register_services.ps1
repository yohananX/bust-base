$log = "C:\Users\pasto\bust-base\scripts\services_install.log"
Start-Transcript -Path $log -Force
$nssm = "C:\Users\pasto\bust-base\tools\nssm\nssm.exe"
$BASE = "C:\Users\pasto\bust-base"
$logs = "$BASE\logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null

$services = @(
  @{
    Name = "GHSS-Technitium"
    Exe  = "$BASE\tools\dotnet\dotnet.exe"
    Args = "DnsServerApp.dll"
    Dir  = "$BASE\tools\technitium"
    Env  = "DOTNET_ROOT=$BASE\tools\dotnet DOTNET_BUNDLE_EXTRACT_BASE_DIR=$BASE\tools\dotnet\bundles"
  },
  @{
    Name = "GHSS-Caddy"
    Exe  = "$BASE\tools\caddy\caddy.exe"
    Args = "run --config `"$BASE\Caddyfile`" --adapter caddyfile"
    Dir  = $BASE
    Env  = $null
  },
  @{
    Name = "GHSS-Portal"
    Exe  = "$BASE\venv\Scripts\python.exe"
    Args = "-m waitress --listen=0.0.0.0:8000 --threads=8 school.wsgi:application"
    Dir  = $BASE
    Env  = $null
  },
  @{
    Name = "GHSS-QCluster"
    Exe  = "$BASE\venv\Scripts\python.exe"
    Args = "$BASE\manage.py qcluster"
    Dir  = $BASE
    Env  = $null
  }
)

foreach ($s in $services) {
    Write-Host "===== Installing service: $($s.Name) ====="
    & $nssm stop $s.Name 2>$null | Out-Null
    & $nssm remove $s.Name confirm 2>$null | Out-Null
    & $nssm install $s.Name $s.Exe $s.Args
    & $nssm set $s.Name AppDirectory $s.Dir
    if ($s.Env) { & $nssm set $s.Name AppEnvironmentExtra $s.Env }
    & $nssm set $s.Name AppStdout "$logs\$($s.Name).out.log"
    & $nssm set $s.Name AppStderr "$logs\$($s.Name).err.log"
    & $nssm set $s.Name Start SERVICE_AUTO_START
    & $nssm set $s.Name AppExit Default Restart
    & $nssm set $s.Name AppRestartDelay 2000
    & $nssm set $s.Name DisplayName $s.Name
    Write-Host "  installed."
}

Write-Host "===== Starting services ====="
foreach ($s in $services) {
    Write-Host "  starting $($s.Name)"
    & $nssm start $s.Name
}
Stop-Transcript