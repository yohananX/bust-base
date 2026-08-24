# ============================================================
# repoint_lan.ps1  -  Point portal.ghis.sch at your CURRENT IP.
#
# Run this after joining a NEW network (or if your IP changes).
# It:
#   1. Detects your current IPv4
#   2. Updates the Technitium A record so portal.ghis.sch
#      resolves to the right address
#   3. Adds your IP to Django's ALLOWED_HOSTS / CSRF origins
#      in .env so browsing http://<your-ip> also works
#   4. Restarts the web app service so the change takes effect
#
# Devices must still use this machine as their DNS server
# (router DHCP or per-device).
#
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\repoint_lan.ps1
# ============================================================
$ErrorActionPreference = "Stop"

# --- 0. Self-elevate (needed to restart the portal service) ---
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Requesting administrator rights..." -ForegroundColor Yellow
    Start-Process -FilePath "powershell.exe" -ArgumentList "-ExecutionPolicy","Bypass","-File","`"$PSCommandPath`"","`"$($args[0])`"" -Verb RunAs
    exit
}

$apiBase = "http://127.0.0.1:5380/api"
$username = "admin"
$password = $args[0]  # optional: pass as first argument; otherwise prompts
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)  # repo root
$envFile = Join-Path $root ".env"
$nssm = Join-Path $root "tools\nssm\nssm.exe"

# --- 1. Detect current IPv4 (prefer a private 192.168.x / 10.x / 172.16.x) ---
$ip = Get-CimInstance Win32_NetworkAdapterConfiguration -Filter "IPEnabled=True" |
    Where-Object { $_.IPAddress } |
    ForEach-Object { $_.IPAddress } |
    Where-Object { $_ -match "^10\.|^192\.168\.|^172\.(1[6-9]|2[0-9]|3[01])\." } |
    Select-Object -First 1

if (-not $ip) {
    Write-Host "Could not find a private IPv4 address. Are you connected to Wi-Fi?" -ForegroundColor Red
    exit 1
}
Write-Host "Current IP: $ip" -ForegroundColor Cyan

# --- 1b. Detect the router / gateway for this network ---
$gw = Get-CimInstance Win32_NetworkAdapterConfiguration -Filter "IPEnabled=True" |
    Where-Object { $_.DefaultIPGateway } |
    ForEach-Object { $_.DefaultIPGateway } |
    Where-Object { $_ -match "^\d+\.\d+\.\d+\.\d+$" } |
    Select-Object -First 1
if ($gw) { Write-Host "Router (gateway): $gw" -ForegroundColor Cyan }

if (-not $password) {
    $sec = Read-Host "Technitium admin password" -AsSecureString
    $password = [System.Net.NetworkCredential]::new("", $sec).Password
}

# --- 2. Log in to Technitium ---
$login = Invoke-RestMethod -Method Post -Uri "$apiBase/user/login" -Body "user=$username&pass=$password&totp=&includeInfo=false" -ContentType "application/x-www-form-urlencoded"
if ($login.status -ne "ok") { Write-Host "Technitium login failed: $($login.errorMessage)" -ForegroundColor Red; exit 1 }
$token = $login.token

# --- 3. Update (overwrite) the A record for portal.ghis.sch ---
$body = "zone=ghis.sch&domain=portal.ghis.sch&type=A&ttl=3600&overwrite=true&comments=auto&expiryTtl=0&ipAddress=$ip&ptr=false&createPtrZone=false&updateSvcbHints=false"
try {
    $resp = Invoke-RestMethod -Method Post -Uri "$apiBase/zones/records/add?token=$token" -Body $body -ContentType "application/x-www-form-urlencoded"
    if ($resp.status -ne "ok") { throw $resp.errorMessage }
    Write-Host "OK: portal.ghis.sch -> $($resp.response.addedRecord.rData.ipAddress)" -ForegroundColor Green
} catch {
    Write-Host "Failed to update record: $_" -ForegroundColor Red
    exit 1
}

# --- 4. Add the current IP to Django ALLOWED_HOSTS + CSRF origins ---
$envText = Get-Content $envFile -Raw
foreach ($pair in @(
        @{ key = "ALLOWED_HOSTS"; value = $ip },
        @{ key = "CSRF_TRUSTED_ORIGINS"; value = "http://$ip" }
    )) {
    $line = ($envText -split "`r?`n") | Where-Object { $_ -like "$($pair.key)=*" } | Select-Object -First 1
    if ($line -and $line -notmatch [regex]::Escape($pair.value)) {
        $updated = $line + "," + $pair.value
        $envText = $envText.Replace($line, $updated)
        Write-Host "Added $($pair.value) to $($pair.key)" -ForegroundColor Green
    } else {
        Write-Host "$($pair.value) already in $($pair.key) - skipping" -ForegroundColor DarkGray
    }
}
Set-Content -Path $envFile -Value $envText -NoNewline

# --- 5. Restart the web app so waitress picks up ALLOWED_HOSTS ---
Write-Host "Restarting web app service (GHSS-Portal)..." -ForegroundColor Yellow
& $nssm restart GHSS-Portal
Start-Sleep -Seconds 5

# --- 6. Instructions (tailored to the network we are on) ---
Write-Host ""
Write-Host "Done. To make portal.ghis.sch work on THIS network, devices must"
Write-Host "use $ip (this machine) as their DNS server:"
Write-Host ""
if ($gw) {
    Write-Host "  [BEST] Router method (all devices at once):" -ForegroundColor Green
    Write-Host "    Open your router admin page:  http://$gw"
    Write-Host "    In DHCP settings, set Primary/Preferred DNS to  $ip"
    Write-Host "    (secondary 1.1.1.1). Devices that reconnect will resolve"
    Write-Host "    portal.ghis.sch automatically."
    Write-Host ""
}
Write-Host "  [Per device] On the phone/tablet: Wi-Fi -> this network ->"
Write-Host "    set DNS to  $ip  (secondary 1.1.1.1)"
Write-Host ""
Write-Host "  [Quick test, no DNS needed] just browse:  http://$ip"