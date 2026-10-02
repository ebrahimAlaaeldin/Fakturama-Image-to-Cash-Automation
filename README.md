# Fakturama Image-to-Cash

One order image in, one saved and verified **Order** plus a linked, **paid Invoice** out. The run
drives Fakturama's UI through Windows UI Automation (pywinauto) and resolves or creates the
Debtor, terms of payment, VAT and Products along the way. It uses no hardcoded coordinates.

* Design document (Part 1): [docs/DESIGN.md](docs/DESIGN.md)
* Annotated screenshots (create branches, select branches, a manual-review stop and its resume):
  [docs/screenshots/](docs/screenshots/)
* Every run also writes a one-page `report.html` (outcome, created master data, each PDF step with
  its decision and screenshot)

```
order.png ─► PaddleOCR ─► layout rows ─► Groq gpt-oss-120b (verbatim strings) ─► grounding check
          ─► normalise (Decimal/date) ─► arithmetic reconciliation ─► OrderExtraction
          ─► Fakturama: New Order ─► Debtor ─► Products (+VAT) ─► lines ─► save ─► Documents
          ─► follow-up Invoice ─► payment method + paid ─► save ─► Documents  ─► report.json/.html
```

## Quick start for a reviewer (Windows)

Everything is installed by one script, and the GUI is started by another.

1. **Install Fakturama 2.1.x** from https://www.fakturama.info/download/ (English UI), start it once,
   and complete the **first-start wizard** (it creates a workspace with the default settings).
   Use the wizard, not *File > Select Workspace*: a workspace created that way lacks default
   shipping and preferences.
2. **Install Python 3.12 (64-bit)** from https://www.python.org/downloads/windows/ (3.10 and 3.11 also
   work; 3.13 does not, because PaddlePaddle has no wheels for it). Tick *"Add python.exe to PATH"* or
   keep the *py* launcher.
3. **Run `setup.bat`** (double-click it, or run it from a terminal in this folder). It:
   1. finds Python 3.10-3.12,
   2. creates the virtual environment `.venv`,
   3. installs all packages from `pyproject.toml` (PaddlePaddle 3.0, PaddleOCR 3.1, pywinauto, openai,
      pydantic, python-dotenv, pillow, pytest; about 1 GB, a few minutes),
   4. downloads the PP-OCRv5 OCR models (about 200 MB, into `%USERPROFILE%\.paddlex`),
   5. runs the offline unit tests.
4. **The Groq API key is already in `.env`** (committed for this review), so nothing needs to be
   configured. To use another key, edit `GROQ_API_KEY` in `.env`.
5. **Open Fakturama** (main window visible, maximised is best), then **run `run_gui.bat`**:
   pick an image (e.g. from `samples\cases`), click *Extract & check*, then *Run*. Don't touch the
   mouse or keyboard until the GUI window comes back; the automation drives Fakturama with real
   clicks and keystrokes.

Each run writes its evidence to `runs\<timestamp>\` (open `report.html`). Note that one External
Reference can be imported only once per workspace: running the same image twice stops at the safety
check by design. Use another test case, or delete that Order/Invoice in Data > Documents.

### Manual setup (what `setup.bat` does)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m fakturama_i2c gui
```

`paddlex` is pinned below 3.2 because newer versions break `paddleocr 3.1`. `.env` holds
`GROQ_API_KEY`, `GROQ_MODEL` (default `openai/gpt-oss-120b`) and optionally `FAKTURAMA_EXE` (only
used to start Fakturama when it is not running).

## Run

```powershell
# full flow (image -> verified Order + paid Invoice)
.venv\Scripts\python -m fakturama_i2c run samples\order_WEB-2026-0714-A17.png

# extraction only (no UI): prints the validated OrderExtraction
.venv\Scripts\python -m fakturama_i2c run samples\order_WEB-2026-0714-A17.png --extract-only

# replay a previous extraction without OCR/LLM, pausing before every Save (for a recording)
.venv\Scripts\python -m fakturama_i2c run --from-json runs\<ts>\extraction.json --confirm
```

### Desktop GUI

```powershell
.venv\Scripts\python -m fakturama_i2c gui
```

1. **Order image**: *Open image…*, *Paste screenshot* (clipboard), *Snip screen…* (Windows snipping
   overlay), or pick one of the generated **test cases**.
2. **Extract & check**: OCR + LLM; the table shows exactly what will be entered (grounded and
   reconciled). The run then uses this extraction, so what you checked is what gets entered.
3. **Run**, or **Resume** after a manual review. *Continue (Save)* appears when *Pause before each
   Save* is on; *Stop* kills the run. The window minimises while the automation needs the screen.
   The result (done / manual review / failed) is shown when the run ends, and *Open last run folder*
   shows the evidence.

### Fast mode

`--fast` (GUI: *⚡ Fast mode*) turns off the on-screen captions and pacing and keeps screenshots only
for failures and milestones (saves, Documents checks, the final payment check). **Every check still
runs.** It doesn't skip any PDF verification, the extraction safeguards or the manual-review stops.
Those checks are what caught the email-in-alias, wrong-product and duplicate-Invoice cases.

General speed-ups (all modes): grids are OCR'd in one batch and only in the columns a check uses;
a field that ignores UIA SetValue is typed after 0.6 s instead of after a 3 s wait; search boxes
are typed directly. Measured on the resume path: 63.9 s -> 48 s of step time (-25 %). A full run
also saves the ~45 s of caption pacing.

### Resume after a manual review

```powershell
.venv\Scripts\python -m fakturama_i2c run --from-json runs\<ts>\extraction.json --resume
```

`--resume` never creates a second Order or Invoice. It looks the reference up in Data > Documents:

| What is saved | What resume does |
|---|---|
| nothing | normal flow; master data saved before the stop is found and reused |
| the Order | reopen it, re-verify read-only (addresses, lines, totals, Documents row), create the follow-up Invoice, run section 5 |
| Order + Invoice | reopen both, re-verify, apply 5.2/5.3 only where a value differs, save only if something changed, verify 5.5/5.6 |
| several Orders/Invoices, an Invoice without an Order | stop for manual review |

The stopped run's own unsaved *New Order / New Invoice* drafts are discarded first; any other
unsaved editor (e.g. a Debtor a person is fixing) makes resume stop and ask to save or close it.
If the list misses an Invoice, Fakturama's own "there's already a follow-up" warning is answered
**No** and resume continues with that Invoice.

### Test cases from the sample

`python tools/make_test_cases.py` repaints values in the sample (using its OCR boxes) into
`samples/cases/*.png` + `expected.json`:

| Case | Exercises |
|---|---|
| 01_original | full create path on an empty workspace |
| 02_degraded_scan | skewed, blurred, low-res JPEG: extraction must still be exact |
| 03_unpaid | PDF 5.3 "leave paid clear" (status OPEN, no payment date) |
| 04_same_address | PDF 2.8 billing == delivery (both roles on the Main address) |
| 05_new_product_credit_card | Debtor + one Product reused, one Product created; "Credit Card" missing on the Debtor -> 5.2 manual review -> create it -> `--resume` |
| 06_line_total_wrong | arithmetic mismatch: extraction fails closed |

`set RUN_INTEGRATION=1` then `pytest tests/test_cases_extraction.py` runs OCR + LLM on every case
and compares with `expected.json` (all 6 pass).

### Recording a demo

```powershell
.venv\Scripts\python -m fakturama_i2c run samples\order_WEB-2026-0714-A17.png --narrate --pace 2 --confirm
```

* `--narrate`: a caption bottom-left (over Fakturama's navigation panel) names the PDF step and
  what happens ("PDF 2.3 – 0 row(s) in the list: no exact match -> create it"), and the console
  prints the same as coloured banners. The caption window is click-through and never takes focus,
  so it cannot disturb the automation, and it appears in every evidence screenshot, which makes
  them self-annotating.
* `--pace 2`: 2 s pause after each step so viewers can follow.
* `--confirm`: stops before every Save; press Enter in the terminal to continue (talk-over moments).

Suggested recording: the order image first, then Fakturama full screen with the terminal visible
in a corner, then the run, and finally `runs/<ts>/report.html` and Data > Documents.

While it runs, **don't use the mouse or keyboard**: SWT widgets need real clicks and keystrokes.
The window is maximised automatically.

Exit codes: `0` done, `2` stopped for manual review (the reason and its evidence are in the
report), `1` failed verification. Each run writes `runs/<timestamp>/` containing:

| file | content |
|---|---|
| `ocr_tokens.json`, `ocr_rows.txt` | what OCR read, and the row text given to the LLM |
| `raw_order.json`, `extraction.json` | LLM output (verbatim strings) and the normalised, reconciled order |
| `steps.jsonl` | one line per PDF step: status, values, the OCR'd list rows each match was decided on |
| `screenshots/NNN-<pdf step>.png` | screenshot after every step (`-FAILED` on failure) |
| `report.json` | final status + extraction + all steps |
| `report.html` | the same as a readable page: outcome cards, step table with decision and screenshot thumbnails (`python -m fakturama_i2c.ui.report_html runs/<ts>` regenerates it) |

Tests (offline, no Fakturama or network needed):

```powershell
.venv\Scripts\python -m pytest -q
```

They cover pricing, normalisation, reconciliation, grounding, the layout cross-check, the matching
rules, grid-line detection on real Fakturama screenshots, and the resume decisions (which saved
documents count, what resume does, OCR-tolerant but exact document-number matching).
`RUN_INTEGRATION=1` adds the six extraction test cases (needs the Groq key).

## Code layout

```
fakturama_i2c/
  models.py, errors.py, config.py, cli.py
  extraction/   llm_structurer, grounding_check, normalize, reconcile, pipeline   (image -> OrderExtraction)
  vision/       ocr (PaddleOCR), layout (row grouping)                            (shared OCR engine)
  ui/           locate, act, wait, datefield, grid, evidence                      (generic UIA toolkit)
  fakturama/    labels, shell, page, document_editor, items_grid, select_dialogs,
                debtor_editor, master_data, documents_view, grids                 (page objects)
  workflow/     matching, pricing (pure rules), context, orchestrator,
                stages/{order_open, debtor, payment_method, product, lines, order_complete, invoice}
tools/dump_uia_tree.py   live UIA tree dumper used to build the page objects
```

Layering: `workflow` → `fakturama` → `ui`. `extraction` and `ui` never import each other; both
use `vision`. Only `fakturama/labels.py` contains Fakturama wording.

## Requirements traceability

| PDF | Requirement | Implemented in |
|---|---|---|
| 1.1–1.2 | OCR/LLM extraction of order, debtor, addresses, payment, items, totals | `extraction/pipeline.py` (+ `grounding_check`, `normalize`, `reconcile`) |
| — | idempotency: refuse a second Order for the same reference | `stages/order_open.ensure_not_already_imported` |
| 1.3–1.7 | toolbar Order, keep No., Date, Cust.Ref., Net + With VAT | `stages/order_open.open_order`, `fakturama/document_editor.py`, `ui/datefield.py` |
| 1.8 | Order tab stays open; return to it after every side-trip | `fakturama/shell.activate` (editors tracked by their UIA element) |
| 2.1–2.3 | upper address icon, search company, exact match on Company/First/Name/ZIP/City | `stages/debtor._search_and_select`, `workflow/matching.match_debtor` |
| 2.4 / 2.13 | verify Invoice + Delivery address on the Order | `stages/debtor.verify_order_addresses` |
| 2.5–2.9 | New Contact; identity; main address + roles; additional delivery address; Misc (alias, 0 %, Net) | `stages/debtor.create_debtor`, `fakturama/debtor_editor.py` |
| 2.10–2.10.6 | terms of payment lookup / create (code mapping, 0 days, blank texts), select it | `stages/payment_method.py`, `fakturama/master_data.fill_payment`, `labels.PAYMENT_CODE_MAP` |
| 2.11–2.12 | save Debtor once, re-select it from the Order | `stages/debtor.resolve_debtor` |
| 3.1–3.3 | every item, upper product icon, exact SKU | `stages/product.resolve_items/_search_and_select`, `matching.match_product` |
| 3.4–3.6 | Data > VATs: reuse exact (name, value, code S) or create | `stages/product.ensure_vat`, `matching.match_vat`, `master_data.fill_vat` |
| 3.7–3.12 | New product (gross = net × (1+VAT), cost 0, stock 0), save once, re-select | `stages/product.create_product`, `master_data.ProductEditor`, `pricing.gross_price` |
| 3.13–3.17 | Qty, U.Price, VAT, Discount; verify line Price | `stages/lines.complete_line`, `fakturama/items_grid.py`, `pricing.line_net` |
| 4.1–4.3 | verify addresses, lines, discount 0 % / free shipping, totals | `stages/order_complete.complete_order` |
| 4.4–4.5 | save once; Documents row (number, date, Cust.Ref., open, total) | `shell.save`, `order_complete.verify_document_row` |
| 4.6–4.7 | follow-up Invoice from the Order (not the toolbar) | `document_editor.create_followup_invoice` |
| 5.1 | keep proposed No./dates; verify copied Cust.Ref., addresses, Order Date, VAT mode, lines, totals | `stages/invoice.complete_invoice` |
| 5.2–5.3 | payment method; paid + payment date + Value = total (or leave clear) | `document_editor.set_payment_method / mark_paid` |
| 5.4–5.6 | save once; Documents: Invoice paid + total, Order still open; persisted payment fields | `stages/invoice.complete_invoice` |
| 5.7 | stop — no Delivery/Correction/Dunning | `workflow/orchestrator.py` |

## Deviations and interpretations

* **Payment method created before New Contact (PDF 2.10).** Fakturama 2.1 fills the Debtor
  editor's Payment dropdown once, when the editor opens, so a method created while the Debtor
  editor is open can never be selected in it. The lookup/create (2.10.1–2.10.6, same rules) runs
  just before 2.5; the Debtor editor then selects the method.
* **Billing ≠ delivery address (PDF 2.8 only covers "identical").** The Main address gets the
  *Invoice address* role; an additional address with the *Delivery address* role holds the
  delivery address. Its first line ("Northstar Office Warehouse") goes into *additional name*.
* **Delivery address verified after the save.** Selecting the address tabs of an unsaved
  document makes Fakturama's save fail (NullPointerException in `SaveHandler`; reproduced in
  isolation). Before the single save only the visible Invoice address is checked; both tabs are
  checked right after it.
* **Product selector auto-pick.** When the SKU search leaves exactly one product, Fakturama adds
  it and closes the dialog. This is accepted only if exactly one new line appears and its Item
  No. equals the SKU; anything else → manual review.
* **"Keep VAT as With VAT" (1.7) is re-asserted** after the Debtor (2.4/2.13), at 3.14, 4.1 and
  5.1 (`stages/vat_mode.py`), and 3.14 *sets* the line VAT through the cell drop-down if it differs
  ("set or confirm").
* **5.6.** The Invoice editor stays open after saving and shows the persisted state, so the
  payment fields are read there instead of reopening the document.
* The source *Customer ID* (CUST-1007) is extracted but not used (PDF 2.6 keeps Fakturama's own ID).
* Contact name split: last token = family name ("Marta Klein" → Marta / Klein).

## Status and evidence

| What | Result | Evidence |
|---|---|---|
| Extraction from the sample image (PaddleOCR → Groq → grounding → reconcile) | ✅ all fields correct; totals reconcile | `docs/extraction_sample.json`, `docs/extraction_ocr_rows.txt` |
| Create branches on an empty database: payment method, Debtor (roles, additional delivery address, Misc), save + re-select, VAT 19 % | ✅ | `docs/screenshots/02–06` |
| Select branches + one created Product (case 05): header, existing Debtor, VAT 19 % reused, LMP-DESK-03 created, lines, totals, Save, Documents, follow-up Invoice | ✅ 0 failures | `docs/screenshots/01, 07–13` |
| §5.2 manual review: "Credit Card" not available → stop, nothing saved on the Invoice | ✅ exit 2 | `docs/screenshots/14` |
| `--resume` after a person created "Credit Card": Order reopened and re-verified, Invoice created, paid, saved, Documents (INV *paid*, PO *open*) | ✅ PO000004 → INV000004 | `docs/screenshots/15–17` |
| A second `--resume` on the finished reference | ✅ nothing created, nothing re-saved ("already saved with these values") | that run's `report.html` (not committed) |
| Idempotency and leftover-editor guards | ✅ stop for manual review | `steps.jsonl` of the respective runs |
| **One uninterrupted image → paid Invoice run** (wizard-initialised workspace, `--narrate`) | ✅ 66 steps, 0 failures: PO000001 → INV000001 paid 2026-07-18, 678,30 € | run folder (not committed; `docs/screenshots/`) |

**Root cause of the earlier "Tax-free line" failures (fixed):** `scroll_into_view` used to turn the
mouse wheel over the middle of the form. On Windows, the wheel changes the value of whatever combo
box is under the pointer, so it silently switched the Order's VAT mode to "Free of Tax" and the
in-memory Product's VAT. The wheel is now turned only over the viewport's own scrollbar.

## Fakturama behaviours found (and handled)

* **Combos:** UIA `SelectionItem.Select()`, and for some combos even clicking the drop-down entry,
  changes only the *displayed* value, so the record silently keeps the old one.
  `ui/act.select_combo` uses keyboard selection (first-letter cycling, then a verified arrow walk)
  and reads the value back. Walking a long list can trigger side effects: passing "Canary Islands"
  in the currency-locale list raised a Fakturama *Internal Error*.
* **Date field:** segmented (month/day/year), auto-advances after a full segment, remembers the last
  segment. ValuePattern only repaints it, so it is typed one segment per focus cycle.
* **Address tabs:** selecting the Delivery address tab of an unsaved document makes its Save fail
  (NullPointerException in `SaveHandler`).
* **Debtor editor:** the Payment drop-down is filled once, when the editor opens.
* **Product selector:** with *Preferences > Documents > "immediately take over a clearly found item
  number"*, a search with a single hit adds the product and closes the dialog. This is handled
  and verified against the item grid.
* **Mouse wheel over a form changes combo values**, so scrolling only happens with the pointer on the
  scrollbar (see above).
* **Recording caption over a grid** would be OCR'd as rows, so it is hidden while a grid is captured.
* **Number format follows the locale** (de-DE: '297.50' becomes 29.750,00 €). The decimal separator
  is learned from the Order's own Total field and used for every typed number.
* **LLM variance:** gpt-oss once returned ZIP+city in one field and dropped the alias. That is now
  repaired deterministically (ZIP split) plus one targeted retry for empty required fields or values
  that are not the ones printed under their label (layout cross-check); it still fails closed if
  they stay wrong.
* **The Documents view keeps a category filter.** A category selected in its left tree (e.g.
  *Invoices/unpaid*) hides every other document, so a saved Order looked missing. The lookup clears it
  (first tree entry) and refuses to continue if it cannot. Unpaid Invoices show the state *unpaid*,
  and states are compared as whole words ('paid' never matches 'unpaid').
* **Background editor tabs have no UIA pane**; only the visible editor exposes its controls.
  Closing or reusing a background editor therefore goes through its tab first.
* **Hover tooltips** over grids are OCR'd as rows, so the pointer is parked on the title bar first.
* **Workspaces:** *File > Select Workspace* creates a database without the first-start defaults
  (missing preferences, "No default value found for Shippings"). Use the first-start wizard for a
  clean workspace.

## What was skipped / not verified

* **Branches only unit-tested, not exercised live:** identical billing/delivery
  address, VAT/payment/debtor *conflicts*, ambiguous matches, and a low-confidence OCR list row.
  (Live: the create and select branches, a NOT PAID order, the §5.2 manual review, and both resume paths.)
* **Locale:** only the English UI and US date/number display were run (`labels.py` and
  `ui/datefield.py` are ready for others, but untested).
* **Speed:** a full run takes about 3–4 minutes, mostly OCR of NatTable lists and polite waits.
* The OCR of the phone number dropped a space (`+49 30 55501420` vs `+49 30 5550 1420`).
  The digits are correct and grounded; no normalisation of phone formatting was added.

## Written question — if I had 3 more hours

1. **Read NatTable without OCR.** Every list read (selector dialogs, Data views, the item grid) is a
   screenshot plus OCR. That is the largest source of latency and of the noise the
   code has to tolerate ('TNV000001', 'WVEB-...'). Next I would try NatTable's accessibility support or a
   small Fakturama plugin that exposes the rows, and keep the UIA locators for everything else.
2. **Run every manual-review branch live**, not only in unit tests: conflicting VAT code, a payment
   method with the wrong code, two Debtors with the same company, two Products with the same SKU, a
   NOT PAID order, identical billing/delivery address. Each becomes a test case image like `samples/cases/`,
   with the expected stop recorded in `expected.json`.
3. **A disposable workspace per run.** A script that copies a clean, wizard-initialised workspace and
   starts Fakturama on it, so live tests are repeatable and can run on a schedule (VM or separate
   Windows session that owns the desktop), with flake statistics per step.
4. **Harder input images:** photos (rotation, perspective, blur), more lines, a second VAT rate. I would
   add a deskew step before OCR and measure field accuracy per case rather than pass/fail.
