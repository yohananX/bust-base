$log = "C:\Users\pasto\bust-base\scripts\run_tasks.log"
Start-Transcript -Path $log -Force
foreach ($t in "GHSS-Technitium","GHSS-Caddy","GHSS-Portal") {
    Write-Host "===== $t ====="
    schtasks /query /tn "$t" /v /fo list 2>&1 | Select-String -Pattern "TaskName|Task To Run|Status|Last Run Time|Last Result|Run As User"
    Write-Host "-- running --"
    schtasks /run /tn "$t" 2>&1
}
Start-Sleep -Seconds 15
Write-Host "===== post-run processes ====="
Get-Process dotnet,caddy -ErrorAction SilentlyContinue | Select-Object Id,ProcessName
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match "waitress|qcluster" } | ForEach-Object { $_.CommandLine }
Write-Host "===== ports ====="
netstat -ano | findstr "LISTENING" | findstr ":8000 :80 :5380 :53"
Stop-Transcript