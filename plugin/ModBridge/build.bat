@echo off
REM Build ModBridge (Dalamud plugin). ASCII only on purpose.
setlocal
cd /d "%~dp0"

where dotnet >nul 2>nul
if errorlevel 1 (
  echo [X] dotnet not found. Install the .NET 10 SDK first:
  echo     https://dotnet.microsoft.com/download/dotnet/10.0
  exit /b 1
)

if not exist "%APPDATA%\XIVLauncher\addon\Hooks\dev\Dalamud.dll" (
  echo [i] Dalamud dev libs not found at %%APPDATA%%\XIVLauncher\addon\Hooks\dev
  echo     If Dalamud is installed elsewhere, pass it explicitly:
  echo         build.bat -p:DalamudLibPath^="D:\path\to\Hooks\dev\"
  echo     or set the DALAMUD_HOME environment variable to that folder.
  echo.
)

dotnet build -c Release %*
if errorlevel 1 (
  echo.
  echo [X] Build failed.
  exit /b 1
)

echo.
echo [OK] Built:
echo     bin\Release\ModBridge.dll
echo     bin\Release\ModBridge.json      (Dalamud manifest, DalamudApiLevel 15)
echo     bin\Release\ModBridge\latest.zip (packaged)
echo.
echo To load it in-game, copy the whole bin\Release folder to:
echo     %%APPDATA%%\XIVLauncher\devPlugins\ModBridge\
echo then use /xlplugins and enable "Mod Bridge".
exit /b 0
