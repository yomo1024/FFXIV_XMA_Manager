@echo off
REM Build ModManagerWeb.exe (single file, no console)
cd /d "%~dp0"
set NODE_ENV=
set PY=C:\Users\qwe26\AppData\Local\Programs\Python\Python312\python.exe

echo [1/3] build web UI ...
pushd web-src
call npm run build
popd
if not exist "web\index.html" (
  echo   [X] web\index.html missing - UI build failed
  pause
  exit /b 1
)

echo [2/3] pyinstaller ...
"%PY%" -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name ModManagerWeb ^
  --icon app.ico ^
  --add-data "web;web" ^
  --exclude-module tkinter ^
  mod_manager_web.py
if errorlevel 1 (
  echo   [X] pyinstaller failed
  pause
  exit /b 1
)

echo [3/3] done
echo   Done: %CD%\dist\ModManagerWeb.exe
ping -n 4 127.0.0.1 >nul
