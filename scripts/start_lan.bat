@echo off
REM Start the school portal over the LAN.
REM   - Window 1: Django-Q2 async worker (notifications/bell tasks)
REM   - Foreground: Waitress serving the app on 0.0.0.0:8000
REM
REM Caddy (see Caddyfile) proxies portal.ghis.sch -> 127.0.0.1:8000 on port 80.
REM Edit the port here if you change the Caddyfile.

set PY=%~dp0..\venv\Scripts\python.exe
set BASE=%~dp0..
cd /d "%BASE%"

start "GHSS qcluster" "%PY%" "%BASE%\manage.py" qcluster

"%PY%" -m waitress --listen=0.0.0.0:8000 --threads=8 school.wsgi:application