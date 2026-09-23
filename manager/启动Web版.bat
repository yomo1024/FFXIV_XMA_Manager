@echo off
REM  FFXIV Mod Manager - Web UI launcher (ASCII only on purpose)
setlocal
cd /d "%~dp0"

REM 0) packaged exe first
if exist "ModManagerWeb.exe" (
  start "" "ModManagerWeb.exe"
  exit /b 0
)

REM 1) prefer the py launcher (always on PATH, works without pythonw)
set "PYW="
for %%I in (pyw.exe) do if not defined PYW if exist "%%~$PATH:I" set "PYW=%%~$PATH:I"
for %%I in (pythonw.exe) do if not defined PYW if exist "%%~$PATH:I" set "PYW=%%~$PATH:I"
if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"

REM 2) console fallback (skip the Microsoft Store stub)
set "PY="
for %%I in (python.exe) do if not defined PY if exist "%%~$PATH:I" set "PY=%%~$PATH:I"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if defined PY echo %PY% | find /i "WindowsApps" >nul && set "PY="

echo.
echo   FFXIV Mod Manager - Web UI
echo   opening: http://127.0.0.1:8765
echo   (click Quit in the page, or run the stop bat in this folder, to stop it)
echo.

if not defined PYW goto conly
start "" "%PYW%" mod_manager_web.py
call :nap 2
exit /b 0

:conly
if not defined PY goto nopy
echo   [i] pythonw/pyw not found - starting with a console window
start "" "%PY%" mod_manager_web.py
call :nap 2
exit /b 0

:nopy
echo   [X] Python not found and ModManagerWeb.exe is missing.
echo       Install Python 3.10+ from https://www.python.org/downloads/
echo       and tick "Add python.exe to PATH" during setup.
echo.
pause
exit /b 1

:nap
ping -n 3 127.0.0.1 >nul
exit /b 0
