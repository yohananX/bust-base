@echo off
REM Start the Caddy reverse proxy (foreground).
REM Requires a Caddyfile in the project root.
cd /d "%~dp0.."
"%~dp0..\tools\caddy\caddy.exe" run --config Caddyfile --adapter caddyfile