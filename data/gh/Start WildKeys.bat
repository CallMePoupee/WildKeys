@echo off
setlocal
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
set "PYW=%~dp0.venv\Scripts\pythonw.exe"
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

"%PY%" -c "import webview, pynput, pyperclip" >nul 2>&1
if errorlevel 1 (
  echo Installing dependencies...
  "%PY%" -m pip install -r "%~dp0requirements.txt"
  if errorlevel 1 (
    echo Failed to install requirements.
    pause
    exit /b 1
  )
)

REM App-launch shortcut with logo.ico (taskbar pin / double-click icon)
if exist "%ICON%" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$p='%~dp0'; $lnk=Join-Path $p 'WildKeys.lnk'; $ico=Join-Path $p 'ui\logo.ico'; $ws=New-Object -ComObject WScript.Shell; $s=$ws.CreateShortcut($lnk); $s.TargetPath=(Join-Path $p 'Start WildKeys.bat'); $s.WorkingDirectory=$p.TrimEnd('\'); $s.IconLocation=$ico; $s.Description='WildKeys'; $s.Save()" >nul 2>&1
)

if exist "%PYW%" (
  start "" "%PYW%" "%~dp0main.py"
) else (
  "%PY%" "%~dp0main.py"
)
endlocal
