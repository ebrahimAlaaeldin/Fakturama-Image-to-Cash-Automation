# Fakturama Image-to-Cash

Order image in → saved, verified **Order** + linked **paid Invoice** out. Fakturama is driven through
Windows UI Automation (pywinauto); Debtor, payment method, VAT and Products are selected or created
on the way. No hardcoded coordinates.

* Design (Part 1): [fakturama_design.pdf](fakturama_design.pdf) · summary [docs/DESIGN.md](docs/DESIGN.md)
* Annotated screenshots: [docs/screenshots/](docs/screenshots/)
* Every run writes `runs\<timestamp>\report.html` (outcome, each step, decision, screenshot)

```
image ─► PaddleOCR ─► layout rows ─► Groq gpt-oss-120b (verbatim) ─► grounding + layout check
      ─► normalise ─► reconcile ─► New Order ─► Debtor ─► Products (+VAT) ─► save ─► Documents
      ─► follow-up Invoice ─► payment + paid ─► save ─► Documents ─► report
```

## Quick start (Windows)

1. **Fakturama 2.1.x** ([download](https://www.fakturama.info/download/)), English UI. Start it once and
   finish the **first-start wizard** (not *File > Select Workspace*, which skips the defaults).
2. **Python 3.12, 64-bit** ([download](https://www.python.org/downloads/windows/)); 3.10/3.11 work, 3.13 does not.
3. **`setup.bat`**: creates `.venv`, installs `pyproject.toml` (PaddlePaddle 3.0, PaddleOCR 3.1,
   pywinauto, openai, pydantic, pillow, pytest; ~1 GB), downloads the OCR models (~200 MB), runs the tests.
4. **Groq key** is already in `.env` (committed for review). Change `GROQ_API_KEY` there if needed.
5. **Open Fakturama, then `run_gui.bat`**: pick an image (e.g. `samples\cases`) → *Extract & check* → *Run*.
   Don't touch mouse/keyboard until the GUI returns.

One External Reference can be imported once per workspace; a second run of the same image stops at
the safety check. Use another case or delete that Order/Invoice in Data > Documents.

Manual equivalent: `py -3.12 -m venv .venv` → `.venv\Scripts\python -m pip install -e ".[dev]"` →
`.venv\Scripts\python -m fakturama_i2c gui`. (`paddlex` is pinned < 3.2; newer breaks `paddleocr 3.1`.)

## Usage

```powershell
.venv\Scripts\python -m fakturama_i2c run IMAGE                 # full flow
.venv\Scripts\python -m fakturama_i2c run IMAGE --extract-only  # extraction only, no UI
.venv\Scripts\python -m fakturama_i2c run --from-json runs\<ts>\extraction.json   # skip OCR/LLM
```

| Option | Effect |
|---|---|
| `--resume` | continue after a manual review (below) |
| `--narrate --pace 2` | on-screen captions + pause per step (recordings) |
| `--confirm` | pause before every Save |
| `--fast` | no captions/pacing, milestone screenshots only; **all checks still run** |

**GUI** (`run_gui.bat`): open / paste / snip an image or pick one from a folder; *Extract & check*
shows exactly what will be entered; *Run*, *Resume*, *Stop*, *Continue (Save)*; *Open last run folder*.

Exit codes: `0` done, `2` manual review, `1` verification failed.

**Run folder** `runs\<ts>\`: `ocr_rows.txt`, `raw_order.json`, `extraction.json`, `steps.jsonl`
(values compared, rows read per match), `screenshots\`, `report.json`, `report.html`.

### Resume after manual review

Fix the cause in Fakturama, then *Resume* (or `--resume`). It decides from what is saved in Documents
and never creates a second Order or Invoice.

| Saved | Resume does |
|---|---|
| nothing | normal flow; earlier master data is found and reused |
| Order | re-verify it read-only → linked Invoice → section 5 |
| Order + Invoice | re-verify; change and save only what differs |
| anything else | manual review |

The stopped run's unsaved drafts are closed first; other unsaved editors stop resume.

### Test cases

`tools/make_test_cases.py` repaints the sample into `samples/cases/` + `expected.json`.
`set RUN_INTEGRATION=1` then `pytest tests/test_cases_extraction.py` checks all six (all pass).

| Case | Exercises |
|---|---|
| 01_original | full create path on an empty workspace |
| 02_degraded_scan | skewed, blurred, low-res JPEG |
| 03_unpaid | 5.3 UNPAID: *paid* stays clear |
| 04_same_address | 2.8 billing = delivery |
| 05_new_product_credit_card | one new Product; Credit Card missing → 5.2 review → create → resume |
| 06_line_total_wrong | totals don't reconcile → extraction stops |

Offline tests: `.venv\Scripts\python -m pytest -q` (pricing, normalisation, reconciliation, grounding,
matching, grid reading on real screenshots, resume decisions).

## Code layout

```
fakturama_i2c/
  extraction/  OCR → LLM → grounding, layout check, normalise, reconcile   (image → OrderExtraction)
  vision/      PaddleOCR + row grouping (shared)
  ui/          generic UIA: locate, act, wait, dates, grid OCR, evidence, report
  fakturama/   page objects; labels.py holds all UI wording
  workflow/    matching + pricing (pure), orchestrator, stages/ (one per PDF section), resume
tools/         dump_uia_tree.py (UIA explorer), make_test_cases.py
```

Layering: `workflow → fakturama → ui`; `extraction` and `ui` share only `vision`.

## PDF traceability

| PDF | Requirement | Code |
|---|---|---|
| 1.1–1.2 | extract + normalise | `extraction/pipeline.py` |
| — | no second Order per reference | `stages/order_open.ensure_not_already_imported` |
| 1.3–1.8 | New Order, No., Date, Cust.Ref., Net / With VAT, tab stays open | `stages/order_open.py`, `ui/datefield.py` |
| 2.1–2.4, 2.13 | address selector, exact match, verify addresses | `stages/debtor.py`, `matching.match_debtor` |
| 2.5–2.9, 2.11–2.12 | create Debtor, roles, Misc, save, re-select | `stages/debtor.create_debtor`, `fakturama/debtor_editor.py` |
| 2.10–2.10.6 | payment method lookup / create / select | `stages/payment_method.py`, `labels.PAYMENT_CODE_MAP` |
| 3.1–3.3, 3.12 | product selector, exact SKU, re-select | `stages/product.py`, `matching.match_product` |
| 3.4–3.6 | VAT reuse (name, value, code S) or create | `stages/product.ensure_vat`, `matching.match_vat` |
| 3.7–3.11 | create Product (gross price, cost 0, stock 0) | `stages/product.create_product`, `pricing.gross_price` |
| 3.13–3.17 | Qty, U.Price, VAT, Discount, line Price | `stages/lines.py`, `fakturama/items_grid.py` |
| 4.1–4.5 | verify, discount/shipping, totals, save, Documents | `stages/order_complete.py` |
| 4.6–4.7 | follow-up Invoice (not toolbar) | `document_editor.create_followup_invoice` |
| 5.1–5.6 | copied data, payment, paid, save, Documents, persisted fields | `stages/invoice.py` |
| 5.7 | stop, no further documents | `workflow/orchestrator.py` |

## Deviations and interpretations

* **Payment method before New Contact (2.10):** the Debtor editor loads its Payment list once, so a
  method created while it is open can't be selected. Same rules, run just before 2.5.
* **Billing ≠ delivery (2.8 covers only "identical"):** Main address = Invoice role; an additional
  address = Delivery role.
* **Delivery tab checked after save:** switching address tabs on an unsaved document breaks Fakturama's
  save (NullPointerException).
* **Product auto-pick:** a single search hit is added automatically; accepted only if exactly that SKU
  was added.
* **5.6:** payment fields are read in the still-open Invoice editor after saving.
* Customer ID is not used (2.6 keeps Fakturama's). Contact split: last word = family name.

## Status and evidence

| What | Result | Evidence |
|---|---|---|
| Extraction of the sample | ✅ all fields; totals reconcile | `docs/extraction_sample.json` |
| Create branches: payment method, Debtor, VAT | ✅ | screenshots 02–06 |
| Select branches + new Product (case 05) through Invoice creation | ✅ | screenshots 01, 07–13 |
| 5.2 manual review: Credit Card missing | ✅ exit 2 | screenshot 14 |
| Resume → PO000004 → INV000004 paid; second resume changes nothing | ✅ | screenshots 15–17 |
| Unpaid order (case 03) end to end | ✅ PO000005 → INV000005 unpaid | live run |
| Full uninterrupted narrated run | ✅ 58 steps, 0 failures, PO000006 → INV000006 | live run |

## Fakturama behaviours found (handled)

* **Combos:** UIA selection changes only the display → keyboard selection + read-back.
* **Mouse wheel over a form changes combo values** (caused "Tax-free" lines) → wheel only on scrollbars.
* **Date field** is segmented → typed one segment at a time.
* **Documents view keeps a tree filter** (e.g. *Invoices/unpaid*) → cleared before every lookup;
  states compared as whole words (*paid* ≠ *unpaid*).
* **Background editor tabs** expose no controls → reached through their tab.
* **Locale numbers** (`297.50` → `29.750,00`) → decimal separator learned from the Total field.
* **Tooltips / captions** get OCR'd as grid rows → pointer parked, caption hidden during capture.
* **LLM variance** (ZIP+city merged, e-mail as alias) → ZIP split, layout check, one targeted retry.

## Not verified / skipped

* Live: conflict and ambiguous-match branches, identical addresses, low-confidence list rows (unit-tested only).
* Only the English UI / US date display.
* A full run takes ~3–4 min, mostly OCR of NatTable lists.
* Phone OCR may drop a space (digits correct); phone formatting isn't normalised.

## If I had 3 more hours

1. **Read NatTable without OCR** (accessibility layer or a small Fakturama plugin): the biggest source
   of latency and OCR noise.
2. **Run every manual-review branch live:** conflicting VAT or payment code, duplicate Debtor or SKU,
   identical addresses, each as a test image with its expected stop.
3. **Disposable workspace per run** in a dedicated Windows session, for repeatable scheduled live tests.
4. **Harder images** (photos, rotation, blur, more lines, a second VAT rate) with deskewing and
   per-field accuracy metrics.
