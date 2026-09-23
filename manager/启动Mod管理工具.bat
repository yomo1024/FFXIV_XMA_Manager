@echo off
cd /d "%~dp0"
if exist "%~dp0ModManager.exe" (
    start "" "%~dp0ModManager.exe"
    exit /b 0
)
set "PY=C:\Users\qwe26\AppData\Local\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0mod_manager.py" %*
if errorlevel 1 pause
