# Fakturama Image-to-Cash

Turns one order image into a saved, verified Order and linked paid Invoice in Fakturama (PaddleOCR + Groq LLM + Windows UI Automation). Design: [fakturama_design.pdf](fakturama_design.pdf).

**Setup (Windows):** install Fakturama 2.1.x (finish its first-start wizard) and Python 3.12 64-bit, then run `setup.bat` (creates `.venv`, installs all packages, downloads OCR models, runs tests). The Groq key is in `.env`.

**Run the GUI:** open Fakturama, run `run_gui.bat`, pick an order image (e.g. `samples\cases`), click *Extract & check*, then *Run* (after a manual review: *Resume*). Don't touch mouse/keyboard during a run.

**CLI:** `.venv\Scripts\python -m fakturama_i2c run samples\order_WEB-2026-0714-A17.png` (add `--resume`, `--narrate`, `--fast`). Each run's report: `runs\<timestamp>\report.html`.

**Note:** each order reference can be imported once per workspace; a repeated image stops at the safety check.
