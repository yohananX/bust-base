@echo off
REM Run as Administrator. Registers the school portal stack to auto-start
REM at Windows startup (before login) as SYSTEM:
REM   - GHSS-Technitium : DNS server (portal.ghis.sch resolution)
REM   - GHSS-Caddy      : reverse proxy (port 80 -> 127.0.0.1:8000)
REM   - GHSS-Portal     : Django app (waitress + qcluster)
REM Safe to re-run (tasks are overwritten with /f).

set BASE=%~dp0..

echo === Stopping any manually-running Caddy to avoid port conflict ===
taskkill /f /im caddy.exe >nul 2>&1
echo   done.

echo.
echo === Registering scheduled tasks (system startup) ===
schtasks /create /tn "GHSS-Technitium" /tr "%BASE%\scripts\start_technitium.bat" /sc onstart /ru SYSTEM /rl highest /f
schtasks /create /tn "GHSS-Caddy" /tr "%BASE%\scripts\start_caddy.bat" /sc onstart /ru SYSTEM /rl highest /f
schtasks /create /tn "GHSS-Portal" /tr "%BASE%\scripts\start_lan.bat" /sc onstart /ru SYSTEM /rl highest /f

echo.
echo === Done. Task list: ===
schtasks /query /fo list | findstr /i "GHSS"

echo.
echo Test immediately with:  schtasks /run /tn "GHSS-Technitium"
pause