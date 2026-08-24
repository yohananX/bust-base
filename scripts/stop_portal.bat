@echo off
REM Stop the school portal stack (Technitium + Caddy + Django + QCluster).
REM Safe to run anytime. Self-elevates for admin rights.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator rights...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

set NSSM=%~dp0..\tools\nssm\nssm.exe

echo Stopping web app (Django / waitress)...
%NSSM% stop GHSS-Portal
echo Stopping async worker (QCluster)...
%NSSM% stop GHSS-QCluster
echo Stopping reverse proxy (Caddy)...
%NSSM% stop GHSS-Caddy
echo Stopping DNS server (Technitium)...
%NSSM% stop GHSS-Technitium

echo.
echo Portal stopped.
pause