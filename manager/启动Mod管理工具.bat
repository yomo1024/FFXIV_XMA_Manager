@echo off
cd /d "%~dp0"
if exist "%~dp0ModManager.exe" (
    start "" "%~dp0ModManager.exe"
    exit /b 0
)
REM 无控制台启动（pythonw）：免得双击后留一个黑的 python 窗口
set "PYW="
for %%I in (pythonw.exe) do if not defined PYW if exist "%%~$PATH:I" set "PYW=%%~$PATH:I"
if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"
if defined PYW (
    start "" "%PYW%" "%~dp0mod_manager.py" %*
    exit /b 0
)
set "PY=C:\Users\qwe26\AppData\Local\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0mod_manager.py" %*
if errorlevel 1 pause
