@echo off
REM Run as Administrator. Opens Windows Firewall for LAN serving.
REM   - TCP 80    : Caddy reverse proxy (http://portal.ghis.sch)
REM   - TCP 8000  : Waitress directly (fallback, if you skip Caddy)
REM   - TCP+UDP 53: Technitium DNS Server (local name resolution)

netsh advfirewall firewall add rule name="GHSS Caddy 80" dir=in action=allow protocol=TCP localport=80
netsh advfirewall firewall add rule name="GHSS Waitress 8000" dir=in action=allow protocol=TCP localport=8000
netsh advfirewall firewall add rule name="GHSS Technitium DNS 53" dir=in action=allow protocol=TCP localport=53
netsh advfirewall firewall add rule name="GHSS Technitium DNS 53 UDP" dir=in action=allow protocol=UDP localport=53

echo.
echo Firewall rules added. Verify with: netsh advfirewall firewall show rule name="GHSS*"