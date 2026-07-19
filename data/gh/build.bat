@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
set "ICON=%~dp0ui\logo.ico"

if not exist "%PY%" (
  echo Creating virtual environment...
  where python >nul 2>&1
  if errorlevel 1 (
    echo Python was not found on PATH.
    pause
    exit /b 1
  )
  python -m venv "%~dp0.venv"
  if errorlevel 1 (
    echo Failed to create .venv
    pause
    exit /b 1
  )
)

echo Installing / updating dependencies...
"%PY%" -m pip install -q -r "%~dp0requirements.txt" pyinstaller
if errorlevel 1 (
  echo Failed to install build dependencies.
  pause
  exit /b 1
)

if not exist "%ICON%" (
  echo Missing icon: %ICON%
  pause
  exit /b 1
)

echo.
echo === [1/2] Building WildKeys app (onedir) ===
"%PY%" -m PyInstaller --noconfirm --clean "%~dp0WildKeys.spec"
if errorlevel 1 (
  echo App build failed
  pause
  exit /b 1
)

if not exist "%~dp0dist\WildKeys\WildKeys.exe" (
  echo dist\WildKeys\WildKeys.exe not found
  pause
  exit /b 1
)

echo.
echo === [2/2] Building WildKeys-Setup.exe (installer) ===
"%PY%" -m PyInstaller --noconfirm --clean "%~dp0WildKeys-Setup.spec"
if errorlevel 1 (
  echo Installer build failed
  pause
  exit /b 1
)

echo.
echo ============================================================
echo  App:       dist\WildKeys\WildKeys.exe
echo  Installer: dist\WildKeys-Setup.exe
echo ============================================================
echo  Double-click WildKeys-Setup.exe to install shortcuts + app.
echo  User data is stored in %%LOCALAPPDATA%%\WildKeys
echo ============================================================
endlocal
