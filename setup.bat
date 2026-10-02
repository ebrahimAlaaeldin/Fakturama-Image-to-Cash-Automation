@echo off
rem One-time setup: Python venv, all packages, OCR models, offline tests.
rem Run from the repository folder:  setup.bat     (then start the GUI with run_gui.bat)
setlocal
cd /d "%~dp0"

echo === 1/5  Looking for Python 3.10 - 3.12 ===
set "PY="
for %%V in (3.12 3.11 3.10) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
    )
)
if not defined PY (
    python -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo Python 3.10, 3.11 or 3.12 is required ^(PaddlePaddle has no wheels for 3.13^).
    echo Install Python 3.12 from https://www.python.org/downloads/windows/ and run setup.bat again.
    exit /b 1
)
%PY% --version

echo === 2/5  Creating the virtual environment .venv ===
if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv || exit /b 1
)

echo === 3/5  Installing packages (PaddleOCR, PaddlePaddle, pywinauto, openai, ...) - takes a few minutes ===
".venv\Scripts\python.exe" -m pip install --upgrade pip || exit /b 1
".venv\Scripts\python.exe" -m pip install -e ".[dev]" || exit /b 1

echo === 4/5  Downloading the OCR models (first time only, about 200 MB) ===
".venv\Scripts\python.exe" -c "from fakturama_i2c.vision.ocr import _engine; _engine(False); _engine(True); print('OCR models ready')" || exit /b 1

if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo NOTE: .env was missing - created from .env.example. Put a Groq API key in it.
)

echo === 5/5  Running the offline tests ===
".venv\Scripts\python.exe" -m pytest -q || exit /b 1

echo.
echo Setup complete. Open Fakturama, then start the GUI with:  run_gui.bat
endlocal
