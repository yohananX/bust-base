@echo off
REM Start the school portal stack (Technitium + Caddy + Django + QCluster).
REM Safe to run anytime. Self-elevates for admin rights.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator rights...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

set NSSM=%~dp0..\tools\nssm\nssm.exe

echo Starting DNS server (Technitium)...
%NSSM% start GHSS-Technitium
echo Starting reverse proxy (Caddy)...
%NSSM% start GHSS-Caddy
echo Starting web app (Django / waitress)...
%NSSM% start GHSS-Portal
echo Starting async worker (QCluster)...
%NSSM% start GHSS-QCluster

echo.
echo Portal started. Open  http://portal.ghis.sch  or  http://127.0.0.1:8000
pause