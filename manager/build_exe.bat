@echo off
cd /d "%~dp0"
set "PY=C:\Users\qwe26\AppData\Local\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"
if not exist "%PY%" (
    echo [X] Python not found - cannot build.
    pause
    exit /b 1
)
echo Building ModManager.exe ... please wait 1-2 minutes.
"%PY%" -m PyInstaller --noconfirm --onefile --windowed --name ModManager --icon "%CD%\app.ico" --add-data "%CD%\app.ico;." --distpath "%CD%" --workpath "%CD%\build" --specpath "%CD%\build" "%CD%\mod_manager.py"
if errorlevel 1 (
    echo.
    echo [X] Build failed. Send the error text to your assistant.
    pause
    exit /b 1
)
echo.
echo ============================================
echo   Done:  %CD%\ModManager.exe
echo ============================================
pause
