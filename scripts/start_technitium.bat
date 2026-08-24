@echo off
REM Start Technitium DNS Server using the bundled .NET 10 runtime.
set DOTNET_ROOT=%~dp0..\tools\dotnet
set DOTNET_BUNDLE_EXTRACT_BASE_DIR=%~dp0..\tools\dotnet\bundles
cd /d "%~dp0..\tools\technitium"
echo [%date% %time%] starting technitium as %USERNAME% from %CD% >> "%~dp0technitium.log"
"%~dp0..\tools\dotnet\dotnet.exe" DnsServerApp.dll >> "%~dp0technitium.log" 2>&1