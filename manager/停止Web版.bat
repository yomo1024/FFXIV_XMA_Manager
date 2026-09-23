@echo off
setlocal
powershell -NoProfile -Command "$c=Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue; if($c){ Stop-Process -Id $c.OwningProcess -Force; Write-Host '[OK] web service stopped' } else { Write-Host '[--] web service is not running' }"
ping -n 3 127.0.0.1 >nul
exit /b 0
