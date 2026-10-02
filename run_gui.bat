@echo off
rem Starts the desktop GUI (run setup.bat once before). Open Fakturama before clicking Run.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo The environment is not installed yet - run setup.bat first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m fakturama_i2c gui
