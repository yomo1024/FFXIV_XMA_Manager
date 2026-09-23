@echo off
cd /d "%~dp0"
set "PY=C:\Users\qwe26\AppData\Local\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"
if not exist "%PY%" (
    echo [X] Python not found - cannot build the package.
    pause
    exit /b 1
)
"%PY%" "%~dp0make_package.py"
pause
