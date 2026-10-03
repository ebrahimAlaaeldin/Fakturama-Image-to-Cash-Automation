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

Then put a Groq API key in `.env` (`setup.bat` creates it from `.env.example`):

```
GROQ_API_KEY=your-key-here
```

A free key: https://console.groq.com/keys

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

## Resume after a manual review

When the run stops for manual review (exit code `2`), fix the cause in Fakturama, for example by
creating a missing payment method, then click **Resume** (or add `--resume`). Resume checks what is
already saved in **Data > Documents** and continues from there:

| Already saved | Resume does |
|---|---|
| nothing | runs the normal flow; master data created before the stop is found and reused |
| the Order | re-checks the Order read-only, creates the linked Invoice, finishes |
| Order + Invoice | re-checks both; changes and saves only what differs |
| anything unexpected | stops for manual review |

Assumptions: Fakturama's saved documents are the source of truth (no local state file); one
External Reference means at most one Order and one Invoice; the stopped run's unsaved drafts are
discarded first, while any other unsaved editor stops Resume. Tested live: a run stopped at 5.2
(payment method "Credit Card" missing), the method was created, and Resume finished the Invoice; a
second Resume changed nothing.

## Test cases

Six images in `samples/cases` are edits of the original order; six in `samples/stress` are new
orders in the same layout.

| Image | What it tests | Expected |
|---|---|---|
| 01_original | the supplied order | full create path |
| 02_degraded_scan | skewed, blurred, low-resolution JPEG | same data as 01 |
| 03_unpaid | status UNPAID | *paid* left clear |
| 04_same_address | billing = delivery | one address with both roles |
| 05_new_product_credit_card | new product + Credit Card | 5.2 manual review → Resume |
| 06_line_total_wrong | totals don't add up | stops at extraction |
| s1_four_items_mixed_vat | 4 lines, VAT 19 % + 7 %, 1,250.00 | all values exact |
| s2_not_paid_sepa | SEPA Direct Debit, NOT PAID | all values exact |
| s3_umlauts_same_address | "Müller & Söhne", three-part name, Credit Card | all values exact |
| s4_five_items_7pct | 5 lines, 7 % VAT | all values exact |
| s5_photo_of_s1 | phone photo (tilted, blurred) | same data as s1 |
| s6_tilted_photo_of_s3 | very blurry photo | stops: accents unreadable |

All 12 pass the extraction tests. Cases 01, 03 and 05 were also run end to end in Fakturama.

## Tests

```powershell
.venv\Scripts\python -m pytest -q                              # offline unit tests
$env:RUN_INTEGRATION=1; .venv\Scripts\python -m pytest -q      # + 12 extraction cases (Groq)
```

## Project layout

```
fakturama_i2c/
  extraction/   image → validated order (OCR, LLM, grounding, reconciliation)
  ui/           generic UI Automation: find, act + verify, grid OCR, evidence
  fakturama/    page objects for Fakturama's screens
  workflow/     PDF steps, matching rules, resume
samples/cases/   six test images + expected.json
samples/stress/  six more test images + expected.json
```

## Notes

* Each order reference can be imported **once per workspace**. Running the same image again stops at
  the safety check.
* Tested with the English UI only. A full run takes about 3–4 minutes.
