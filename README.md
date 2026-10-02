# Fakturama Image-to-Cash

Turns one order image into a saved, verified **Order** and a linked, **paid Invoice** in Fakturama.
It extracts the data with PaddleOCR + Groq `gpt-oss-120b`, then drives Fakturama through Windows UI
Automation: it selects or creates the Debtor, payment method, VAT and Products, then builds the
Order and Invoice. Each step is verified, nothing uses hardcoded coordinates, and any doubt stops
the run for manual review.

📄 Design: [fakturama_design.pdf](fakturama_design.pdf) · 🖼 Screenshots: [docs/screenshots/](docs/screenshots/)

## Setup (Windows)

1. Install **Fakturama 2.1.x** ([download](https://www.fakturama.info/download/)), start it once and
   finish the **first-start wizard**.
2. Install **Python 3.12 (64-bit)** ([download](https://www.python.org/downloads/windows/)).
3. Install everything:

```powershell
.\setup.bat      # creates .venv, installs packages (~1 GB), downloads OCR models, runs tests
```

The Groq API key is already in `.env`.

## Run the GUI

Open Fakturama first, then:

```powershell
.\run_gui.bat
# or: .venv\Scripts\python -m fakturama_i2c gui
```

1. Pick an order image (*Open image*, *Paste*, *Snip*, or a file from `samples\cases`).
2. **Extract & check** shows what will be entered.
3. **Run**. Don't touch the mouse or keyboard until the window comes back.
4. After a manual-review stop: fix the issue in Fakturama, then click **Resume**.

## Command line

```powershell
.venv\Scripts\python -m fakturama_i2c run samples\order_WEB-2026-0714-A17.png
```

| Option | Effect |
|---|---|
| `--extract-only` | extraction only, no UI |
| `--resume` | continue after a manual review, never creating a second Order or Invoice |
| `--narrate` | on-screen captions (for recordings) |
| `--fast` | no captions or pacing; all checks still run |
| `--confirm` | pause before every Save |

Exit codes: `0` done, `2` manual review, `1` verification failed. Every run writes
`runs\<timestamp>\report.html` (each step, its decision and a screenshot).

## Tests

```powershell
.venv\Scripts\python -m pytest -q                              # offline unit tests
$env:RUN_INTEGRATION=1; .venv\Scripts\python -m pytest -q      # + 6 extraction cases (Groq)
```

## Project layout

```
fakturama_i2c/
  extraction/   image → validated order (OCR, LLM, grounding, reconciliation)
  ui/           generic UI Automation: find, act + verify, grid OCR, evidence
  fakturama/    page objects for Fakturama's screens
  workflow/     PDF steps, matching rules, resume
samples/cases/  six test images + expected.json
```

## Notes

* Each order reference can be imported **once per workspace**. Running the same image again stops at
  the safety check.
* Tested with the English UI only. A full run takes about 3–4 minutes.
* **If I had 3 more hours:** read Fakturama's grids without OCR, run every manual-review branch live,
  use a disposable workspace per run, and test harder images (photos, blur, more lines).
