@echo off
REM Run as Administrator. One-time LAN setup:
REM   1. Add portal.ghis.sch to the hosts file (so THIS machine browses the name locally)
REM   2. Open Windows Firewall for the school portal + DNS
REM Safe to run again: entries are added only if missing.

echo === 1. Hosts entry for portal.ghis.sch ===
findstr /c:"portal.ghis.sch" "%SystemRoot%\System32\drivers\etc\hosts" >nul
if %errorlevel%==0 (
  echo   Already present - skipping.
) else (
  echo   127.0.0.1   portal.ghis.sch>> "%SystemRoot%\System32\drivers\etc\hosts"
  echo   Added "127.0.0.1 portal.ghis.sch"
)
echo.

echo === 2. Windows Firewall rules ===
netsh advfirewall firewall add rule name="GHSS Caddy 80" dir=in action=allow protocol=TCP localport=80
netsh advfirewall firewall add rule name="GHSS Waitress 8000" dir=in action=allow protocol=TCP localport=8000
netsh advfirewall firewall add rule name="GHSS Technitium DNS 53" dir=in action=allow protocol=TCP localport=53
netsh advfirewall firewall add rule name="GHSS Technitium DNS 53 UDP" dir=in action=allow protocol=UDP localport=53
echo.

echo Done. Verify firewall rules with:  netsh advfirewall firewall show rule name="GHSS*"
pause