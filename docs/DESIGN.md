# Fakturama Image-to-Cash — Design

## 1. Goal, scope and principles

**Input:** one order image (scan, screenshot or photo of a sales order).
**Output:** inside Fakturama, one saved and verified **Order**, plus a **linked Invoice** created from
that Order with the extracted payment method and paid status. Missing master data (Debtor, terms of
payment, VAT rate, Product) is created through Fakturama's own UI, and nothing else is touched. The
run stops after the Invoice is verified (no Delivery, Correction or Dunning, PDF 5.7).

The design follows six rules:

1. **Order first.** The New Order is opened before anything else and stays open the whole time
   (PDF 1.8). The Order's own Debtor and Product selectors are the existence checks. Master data is
   created only when an exact selection is unavailable, and the flow then returns to the *same*
   open Order and selects the new record from it.
2. **Fail closed.** Any doubt stops the run for manual review with a precise reason and evidence:
   a value the image does not support, totals that do not reconcile, an ambiguous match, a
   conflicting definition or an unreadable list. Wrong financial data is worse than a stopped run.
3. **Verify every step before the next.** Every write is read back from the UI. Every selection is
   confirmed by what Fakturama then displays. Every save is confirmed in Data > Documents.
4. **Save exactly once.** Each Save is clicked once and then verified, never blindly retried, so a
   slow or failed save can never produce duplicates.
5. **No coordinates, no fixed layout.** Controls are found by meaning (names, labels, structure)
   and their position is read live at run time. Pixels are used only where UI Automation is blind.
6. **The UI is the only interface.** Fakturama's database is never read or written; the run
   verifies what a user would see.

## 2. Assumptions and interpretations

Where the PDF is silent or Fakturama behaves differently than it implies, I made these choices.
All of them are visible in the run's evidence and listed in the README.

| # | Topic | Assumption / interpretation |
|---|---|---|
| A1 | Input | One image is one order in one currency. The image is the only source of truth: nothing is guessed, defaulted or looked up elsewhere. |
| A2 | Fakturama setup | Fakturama 2.x with the English UI, a workspace initialised by the first-start wizard (so default shipping, VAT and preferences exist), and the main window visible. Nobody uses the mouse or keyboard during a run. |
| A3 | Locale | The display date format is read from the field itself. The decimal separator is learned from the Order's own Total field, so numbers are always typed in the format Fakturama expects. All UI strings sit in one labels module; a German UI means swapping that file. |
| A4 | Contact name | "Marta Klein" → First Name "Marta", Name "Klein" (the last token is the family name). Salutation stays "---" (PDF 2.6). |
| A5 | Customer ID | The source's Customer ID (e.g. CUST-1007) is extracted but not used; Fakturama keeps its proposed ID (PDF 2.6). |
| A6 | Billing ≠ delivery | PDF 2.8 only defines the identical case. If they differ, the Main address gets the *Invoice address* role and an additional address gets the *Delivery address* role. The delivery block's first line ("Northstar Office Warehouse") goes into *additional name*. |
| A7 | Payment method timing | Fakturama fills the Debtor editor's Payment dropdown once, when the editor opens, so a method created while it is open can never be selected. The terms-of-payment lookup/create (2.10.1–2.10.6, unchanged rules) therefore runs **just before** New Contact, and the Debtor editor then selects it. This is the one deliberate reordering of the PDF. |
| A8 | Existing Debtor, other method | Payment methods are created only in the Debtor-creation branch (PDF 2.10). If an existing Debtor is selected and the Invoice cannot be set to the extracted method, 5.2 applies literally: stop for manual review. |
| A9 | "Exact" match | Exact means equal after collapsing whitespace and ignoring case. Nothing is fuzzy except the tolerance for OCR-truncated grid cells (an ellipsis-ended cell matches only as a prefix, and only after an attempt to widen the column). |
| A10 | Conflict | A conflict is a row that shares the identity but differs elsewhere: the same company in another city, the same SKU with another name, "VAT 19%" with another value or E-Invoice code, or "Bank Transfer" with another payment code. Several exact rows are also a conflict. Both stop the run. |
| A11 | Product price | Gross = unit net × (1 + VAT/100), rounded half-up to 2 decimals (250.00 → 297.50, 40.00 → 47.60). The line discount is never applied to the master price (PDF 3.9). |
| A12 | Line discount | Entered as the extracted percentage. Fakturama shows it as a negative value ("-10.00 %"), which counts as equal. |
| A13 | Order-level values | Order discount 0 % and "Free of shipping costs" / 0.00 (PDF 4.2). The extraction has no order-level discount or shipping field: on an image that has them, the lines would not add up to the totals, so reconciliation stops the run instead of guessing. |
| A14 | Paid status | Only the status "PAID" ticks *paid*. Then the date is the extracted Payment Date and Value is the full Invoice Total. Any other status leaves *paid* clear, with no invented date or value (PDF 5.3). |
| A15 | Product selector | With Fakturama's preference "immediately take over a clearly found item number", a search with a single hit adds the line and closes the dialog. That is accepted only if exactly one new line appeared and its Item No. equals the SKU. |
| A16 | Delivery address check | Switching the address tabs of an unsaved document breaks its save (a NullPointerException in Fakturama). Before the single save only the visible Invoice address is checked; both tabs are checked immediately after the save. |
| A17 | 5.6 | The Invoice editor stays open after saving and shows the persisted state, so the payment fields are read there; it is reopened only when it is not already open. |
| A18 | Re-running | One External Reference produces at most one Order and one Invoice. A second normal run for the same reference stops; `--resume` is the explicit way to continue it (§9). |

## 3. Architecture

Four layers, each depending only on the one below. The workflow never touches UIA directly, and
the extraction knows nothing about Fakturama.

| Layer | Knows about | Responsibility |
|---|---|---|
| **extraction** | the image | image → validated, typed order (OCR, LLM structuring, grounding, layout cross-check, normalisation, reconciliation) |
| **workflow** | the PDF procedure | one stage per PDF section, exact-match and pricing rules, stop/continue decisions, resume plan |
| **fakturama** | Fakturama's screens | page objects: shell (toolbar, navigation, tabs, Save), Order/Invoice editor, item grid, selector dialogs, Debtor editor, terms of payment, VATs, Product editor, Documents view |
| **ui** | Windows UI Automation | locating, waiting, verified actions (text, combos, dates, checkboxes), grid reading, evidence, on-screen captions |

A shared **vision** module (PaddleOCR) serves both the order image and Fakturama's custom-drawn
grids. Matching, pricing, normalisation, reconciliation and the resume decision are **pure
functions**, so they are unit-tested without Fakturama.

```
order image ─► OCR ─► layout rows ─► LLM (verbatim strings) ─► grounding + layout check
            ─► normalise ─► reconcile ─► typed order
            ─► duplicate check ─► New Order (1.3–1.8) ─► Debtor (2.x) ─► Products + VAT (3.x)
            ─► totals, Save, Documents (4.1–4.5) ─► follow-up Invoice (4.6–4.7)
            ─► payment + paid, Save, Documents, persisted fields (5.1–5.7) ─► report
```

**Ways to run it:** a CLI and a small desktop GUI (open, paste or snip an image; *Extract & check*,
*Run*, *Resume*, *Stop*). Options: extraction only; replay a saved extraction without OCR/LLM;
pause before every Save (`--confirm`); on-screen step captions for recordings (`--narrate`); a fast
mode that drops captions, pacing and non-milestone screenshots but **keeps every check**; and
`--resume`. Exit codes: 0 done, 2 stopped for manual review, 1 verification failed.

## 4. Image-extraction strategy

The extraction is split so that no single component can silently produce a wrong value.

1. **OCR (PaddleOCR, local, PP-OCRv5).** Returns text fragments with bounding boxes and confidences.
   Images narrower than 1400 px are upscaled first. Local OCR keeps pixels on the machine, and the
   boxes and confidences it returns are what grounding and the layout check rely on.
2. **Layout rows.** Fragments are grouped into visual rows by vertical position and printed with
   their horizontal positions. This keeps the table structure: "2 · pcs · 250.00 · 10% · 19% ·
   450.00" stays aligned under its column headers, and a label stays above its value.
3. **LLM structuring (Groq, gpt-oss-120b, text only, temperature 0, strict JSON schema).** The model
   maps the rows onto a schema in which **every field is a string copied verbatim**. It never sees
   pixels, never reformats, never translates and never computes. Its only job is "which text is
   which field", which is what OCR alone cannot do reliably.
4. **Grounding check.** Every returned value must appear in the OCR text, backed by fragments above
   the confidence threshold (0.80). An invented, "corrected" or mis-copied value fails here.
5. **Layout cross-check.** Each labelled value (CUSTOMER ALIAS, ORDER DATE, EXTERNAL REFERENCE,
   PAYMENT METHOD, …) must be the text printed under its own label. Grounding alone is not enough:
   the model once returned the e-mail address as the alias. That value was grounded, but in the
   wrong place.
6. **One targeted retry.** If required fields are empty or the cross-check fails, the LLM is called
   once more with a hint naming exactly what was wrong. If it is still wrong, the run stops.
7. **Deterministic normalisation.** Strings become Decimal amounts (either decimal separator),
   ISO dates, percentages, a split contact name, and a split "10117 Berlin" (ZIP / city).
8. **Arithmetic reconciliation.** Each line must satisfy qty × unit net × (1 − discount/100) = line
   total. The lines must sum to the net total, VAT per rate must match the VAT total, and net + VAT
   must equal gross. A single misread digit breaks this, which makes it the strongest check.

**Extracted fields (PDF 1.2):** order date, external reference, currency, customer ID
(informational); company, contact first/last name, alias, e-mail, phone; billing and delivery
address (name line, street, ZIP, city, country); payment method, paid status, payment date; and
per item the SKU, description, quantity, unit, unit net price, discount %, VAT % and line total;
plus net, VAT and gross totals.

Any failure produces an `ExtractionError` or a manual review listing the failing fields. The OCR
fragments, the row text sent to the LLM, the raw LLM answer and the final typed order are all
saved with the run.

## 5. Control-discovery (grounding) strategy in Fakturama

Fakturama is a Java SWT / Eclipse RCP application. Windows UI Automation (pywinauto, UIA
backend) sees most native controls but not all. Each control is found with the strongest signal
available:

1. **Semantic properties.** Control type plus UIA Name, AutomationId or HelpText. SWT exposes
   tooltips as names, so toolbar buttons are found as "Save the current contents" or "Create a new
   tax rate". Many inputs carry their label as name ("Cust.Ref.", "Street").
2. **Label adjacency.** For unnamed inputs ("No.", "Date", "Price (gross)", "ZIP - City") the
   visible label is found, then the nearest input on the same line or directly below it. Positions
   come from live UIA rectangles, never from constants.
3. **Structure.** Nameless icons are identified by their place in the label's own container. The
   *upper* contact icon beside "Addresses" and the *upper* product icon beside "Items" are the
   first icon; the PDF's "do not click the green +" becomes "never the second one".
4. **Scope.** Searches are limited to the right container: the active editor pane, the open
   dialog, or the lower view folder. A "Name" field in the Debtor editor is never confused with
   one in a dialog behind it. Editor tabs are addressed by their exact title or document number.
5. **Pixels only where UIA is blind.** Fakturama's lists and selector dialogs are NatTable grids,
   which are custom-drawn and expose no rows to UIA. The grid's *container* is still located through
   UIA. Inside that rectangle, grid lines are detected in a screenshot (thin-line and row-pitch
   analysis, which works for light, dark, selected and low-contrast rows). **Each cell is then OCR'd
   on its own**, so neighbouring cells can never merge. Headers snap to a known vocabulary (OCR
   "Oty." → "Qty."). A cell ending in "…" triggers NatTable's own auto-fit (a double-click on that
   column's border) and a re-read. Only the columns a check needs are read. Rows are clicked at
   centres computed from that analysis, relative to the container located through UIA.

**Acting, then verifying.** Every setter reads the control back and raises on a mismatch.

* **Text:** UIA ValuePattern where SWT accepts it, otherwise real typing. Keys are sent only if the
  target has keyboard focus, so keystrokes can never land in another window.
* **Combos:** UIA selection often changes only the *displayed* text, while the record keeps the old
  value. Combos are therefore set with the keyboard (first-letter cycling, then a verified arrow
  walk) and read back after leaving the field.
* **Dates:** the field is segmented (month/day/year). Values are typed one segment per focus cycle,
  after checking which segment is selected.
* **Scrolling:** the mouse wheel changes any combo under the pointer, so the wheel is used only
  over the scrollbar.
* **Waiting:** waits poll observable conditions (dialog open, tab title, list unchanged for N
  polls, dirty marker gone), never fixed sleeps.
* **Saving:** a save counts as successful when the tab is no longer dirty and no error dialog
  appeared. Error dialogs are detected and turned into failures.

## 6. The flow, step by step (PDF → action → verification → stop condition)

| PDF | Action | Verified by | Stops when |
|---|---|---|---|
| 1.1–1.2 | Extract (§4) | grounding, layout check, reconciliation | any check fails after one retry |
| pre-check | Data > Documents, search the External Reference | list read twice, recognised grid | a document already exists (A18) |
| 1.3 | Toolbar **Order**, wait for the new editor tab | new tab appears | timeout |
| 1.4 | Leave the proposed No. | number recorded for later checks | — |
| 1.5–1.6 | Date = Order Date; Cust.Ref. = External Reference | read back | mismatch |
| 1.7 | Price mode Net, VAT With VAT | read back (re-checked at 2.4, 3.14, 4.1, 5.1) | mismatch |
| 1.8 | Order tab kept open; every side trip returns to it by title | active tab = the Order | — |
| 2.1–2.2 | Upper contact icon → *Select the address*, search Company, wait until stable | list stable | — |
| 2.3 | Exact = Company, First Name, Name, ZIP, City | one exact → select + OK | ambiguous or conflicting rows |
| 2.4 | Invoice and Delivery address vs image | address text compared line by line | mismatch |
| 2.10.1–2.10.2 | (before 2.5, A7) Data > terms of payment, search the method; open an exact row to check its payment code | name + code | several exact rows, or a conflicting definition |
| 2.10.3–2.10.6 | If missing: green +, Name = Description = method, Account blank, code from the PDF mapping, cash discount and days 0, texts blank, no "Set as standard"; Save once | read back, save confirmed | — |
| 2.5–2.9 | New Contact; Company, First Name, Last Name; Main address (street, ZIP, city, country, e-mail, phone); roles (A6); Misc: alias, discount 0 %, Net | every field read back | mismatch |
| 2.10 | Payment tab: select the method | read back | not offered |
| 2.11–2.13 | Save the Debtor once; back to the Order; search again, select, OK | addresses populate = proof of save | not found after save |
| 3.1 | For every item, in source order | — | — |
| 3.2–3.3 | Upper product icon → *Select a product*, search the SKU | one exact → OK (or a verified auto-pick, A15) | conflicting rows |
| 3.4–3.6 | Data > VATs, search "VAT n%"; reuse only if Name, Value and code S match; else create (Name = Description, code S, Value, Standard VAT unchanged), Save once | read back | conflicting setting |
| 3.7–3.11 | New product: Item Number = SKU, Name = Description = description, gross price (A11), cost 0.00, exact VAT, stock 0.00, rest untouched; Save once | read back | mismatch |
| 3.12 | Back to the Order, search the SKU again, select | line added with that Item No. | product does not appear |
| 3.13–3.15 | Qty, U.Price = unit net, VAT %, Discount | each cell read back | mismatch |
| 3.16 | Price = qty × price × (1 − d/100) | cell value vs Decimal calculation | mismatch |
| 4.1–4.3 | Addresses and every line vs image; order discount 0 %, free shipping; Total Net / VAT / Total | read back | any mismatch |
| 4.4 | Save once | not dirty, no error, both address tabs now checked (A16) | save error |
| 4.5 | Data > Documents: exactly one Order row with number, date, Cust.Ref., *open*, total | OCR'd row vs expected | missing, duplicate or different |
| 4.6–4.7 | Follow-up area **Invoice** (not the toolbar), wait for the linked editor | new Invoice tab | Fakturama warns a follow-up exists (§9) |
| 5.1 | Keep No./dates; check Cust.Ref., addresses, Order Date, VAT mode, lines, totals | read back | mismatch |
| 5.2 | Payment method = extracted | read back | method not available |
| 5.3 | PAID → paid ✓, date, Value = Invoice Total; otherwise leave clear | read back | mismatch |
| 5.4–5.5 | Save once; Documents: Invoice state + total, Order still *open*, same Cust.Ref. and total | OCR'd rows | mismatch |
| 5.6–5.7 | Persisted payment method, paid, date, Value (A17); end | read back | mismatch |

## 7. Matching and decision rules

All selector and list decisions use one three-way rule over the rows read from the grid:

* **exactly one exact row** → select it;
* **no row sharing the identity** → create (or, for 3.12 / 2.12, stop: the just-saved record must
  be found);
* **several exact rows, or a row sharing the identity but differing elsewhere** → manual review.

The identity and the "exact" fields come from the PDF:

| Record | Identity | Exact match also needs |
|---|---|---|
| Debtor | Company | First Name, Name, ZIP, City |
| Product | SKU | Name |
| VAT | Name "VAT n%" | Value n % and E-Invoice code S (checked in the editor, since the list does not show it) |
| Payment method | Name | payment code from the PDF mapping (checked in the editor) |

**An unreadable list never means "missing".** If a grid is not recognised, or a row is below the
OCR confidence, the run stops instead of creating anything, because creating on a guess would
duplicate master data. Lists are re-read when a row looks implausible (for example, a document
number that does not fit the pattern).

## 8. Manual review: when and how the run stops

A manual review is a deliberate, safe stop, not a crash. The run raises it with the PDF step, a
one-line reason and the evidence (rows read, values compared). It leaves Fakturama as it is, with
nothing half-saved, and exits with code 2. The report shows the reason at the top.

Typical stops:

* **Extraction:** a value is not grounded, a label/value conflict persists after the retry, a
  required field is missing, or the totals do not reconcile.
* **Pre-check:** a document already exists for this External Reference.
* **Matching:** an ambiguous or conflicting Debtor (2.3), payment method (2.10.2), Product (3.3)
  or VAT (3.5); a just-saved record does not reappear (2.12, 3.12).
* **5.2:** the extracted payment method is not available on the Invoice.
* **Safety:** unsaved editors are open before a run; a list cannot be read reliably.

A **verification failure** (exit 1) is different: something was written and does not read back as
expected. Because every check runs before the next step and saves happen only after the checks,
this almost always happens before anything is saved.

## 9. Resume after manual review

A person fixes the cause in Fakturama (or corrects the extraction), then runs the same order again
with **`--resume`** (CLI or the GUI's *Resume* button). Resume never creates a second Order or
Invoice. It decides what to do from **what is actually saved**, never from a local state file that
might be stale.

**1. Clean up.** The stopped run's own unsaved drafts ("New Order", "New Invoice") are closed
without saving, and the run checks they are really gone. Any *other* unsaved editor, such as a
Debtor a person is still fixing, stops resume and asks to save or close it.

**2. Look up** the External Reference in Data > Documents and classify the rows. Anything that is
not clearly an Order counts as an Invoice, so an OCR-misread number can never cause a second
Invoice.

**3. Choose the plan** (a pure, unit-tested decision):

| Saved for this reference | Plan |
|---|---|
| nothing | the normal flow; master data saved before the stop (e.g. a created Debtor or Product) is now found by the selectors and reused |
| one Order | reopen it, **re-verify it read-only** (addresses, lines, totals, Documents row), create the follow-up Invoice (4.6), run section 5 |
| one Order + one Invoice | reopen both, re-verify, apply 5.2/5.3 only where a value differs, save only if something changed, verify 5.5/5.6 |
| an Invoice without its Order, or several Orders/Invoices | manual review |

**Guards.**

* Reopened documents are matched by their exact document number. The OCR noise tolerance only
  covers the letter prefix (0/O, I/T); "PO000003" never matches "PO000004".
* If the Documents list misses an existing Invoice, Fakturama's own warning "There's already a
  follow-up of this document" is answered **No**, and resume continues with that Invoice instead.
* Resuming a finished order changes nothing: it re-verifies everything and saves nothing.

**What can be resumed after which stop:**

| Stop | Saved at that point | The person… | Resume then… |
|---|---|---|---|
| Extraction | nothing | corrects the saved extraction (or provides a better image) | runs from the corrected extraction |
| 2.3 / 3.3 / 3.5 / 2.10.2 conflict | maybe earlier master data, no documents | merges or fixes the conflicting record | runs the normal flow; the draft Order is discarded |
| 2.12 / 3.12 record not found | the created record | checks why it is not listed | runs the normal flow, finds and selects it |
| 4.x verification | nothing (checks run before the save) | fixes the data | runs the normal flow |
| 5.2 method unavailable | **the Order** | creates the payment method | continues from the saved Order: verify, follow-up Invoice, section 5 |
| 5.5 / 5.6 mismatch | Order + Invoice | corrects the Invoice or confirms it | re-applies only the differences, saves only if needed |

**Verified live:** a run stopped at 5.2 ("Credit Card" missing, Order PO000004 saved). After
the method was created, `--resume` reopened and re-verified PO000004, created INV000004, set it
paid and verified both in Documents. A second `--resume` created and saved nothing.

## 10. Idempotency, evidence and testing

**Idempotency.** There are three layers: the External Reference pre-check before a New Order;
"save exactly once, then verify"; and resume's rule that saved documents are the truth.

**Evidence.** Every PDF step is one evidence entry, with a screenshot afterwards (marked *FAILED*
on failure) and a JSON line holding the values compared and the grid rows each match was decided
on. Each run folder holds the extraction artefacts (OCR fragments, row text, raw LLM answer, typed
order), `report.json` and a one-page `report.html`. The HTML shows the outcome, the created
master data, and each step with its decision ("no exact match → create it") and screenshot. With
`--narrate`, every step's PDF number and plain-language caption are shown on screen (and hidden
while a grid is captured) for recordings.

**Testing.** Offline unit tests cover pricing, normalisation, reconciliation, grounding, the
layout check, every matching rule (including conflicts and truncated cells), grid-line detection
on real Fakturama screenshots, number formats and the resume decisions. Six order images generated
from the sample (original, degraded scan, unpaid, identical addresses, new product with Credit
Card, a wrong line total that must be rejected) run the extraction end to end against expected values. Live runs cover the create
branches, the select branches, the 5.2 stop and both resume paths.

## 11. Fakturama behaviours found, and how the design absorbs them

* **Combo selection:** UIA selection, and for some combos even a click, changes only the displayed
  value → keyboard selection plus a read-back. Walking long lists has side effects (one locale
  list raised an Internal Error), so the shortest key path is tried first.
* **Mouse wheel over a form changes combos.** This was the root cause of intermittent "Tax-free"
  lines → the wheel is used only over scrollbars.
* **Segmented date field:** ValuePattern only repaints it → typed one segment per focus cycle.
* **Address tabs of an unsaved document break its save** → the delivery address is verified
  after the save (A16).
* **The Debtor's Payment dropdown is loaded once** → the payment lookup/create runs before New
  Contact (A7).
* **The product selector auto-picks a single hit** → accepted only when verified (A15).
* **The Documents view remembers a category filter** (e.g. "Invoices/unpaid") that hides other
  documents → the filter is cleared before every lookup, and a lookup that cannot clear it stops.
  Document states are compared as whole words, so "paid" never matches "unpaid".
* **Only the visible editor tab exposes controls in UIA** → background editors are reached
  through their tab, matched by exact title.
* **Tooltips and the caption overlay would be OCR'd as grid rows** → the pointer is parked and
  the overlay hidden during grid capture.
* **Untranslated labels and display quirks:** the payment-code label is untranslated
  (`!editorPaymentPaymentcode!`), discounts are shown negative, and some combo entries have
  trailing spaces → matched by pattern or normalised.

## 12. Trade-offs

| Choice | Benefit | Cost |
|---|---|---|
| OCR + text-only LLM, not a vision LLM | every value is grounded in pixels and checkable; cheap; temperature 0 | two models; the table layout must be rebuilt from boxes |
| LLM copies strings, Python computes | no LLM arithmetic or formatting errors; deterministic checks | more code for normalisation |
| Fail closed | never posts wrong financial data | needs a person more often for messy images |
| UIA first, OCR only for NatTable | robust to layout, theme and resolution changes | grid reads take about a second each and need an unobstructed window |
| Real mouse and keyboard for SWT widgets | fires the events SWT listens to | the desktop must not be used during a run |
| Verification through the UI only | matches what a user sees; no coupling to the DB schema | slower; list reads depend on OCR |
| Resume from saved documents, not a state file | cannot be fooled by a stale checkpoint | one extra Documents lookup per resume |
| Payment lookup before New Contact | the only way the Debtor can select a newly created method | a small, documented reordering of the PDF |

## 13. Risks and next steps

The main remaining risks are OCR noise in NatTable lists (mitigated by re-reads and
exact-number rules), concurrent use of the desktop, and untested locales and themes. Next I would:

1. Read NatTable rows without OCR (its accessibility layer or a small Fakturama plugin).
2. Run on a disposable workspace in a dedicated Windows session.
3. Exercise every manual-review branch live (conflicting VAT code or payment code, duplicate Debtor
   or SKU, identical addresses).
4. Add harder input images (photos, rotation, blur, more lines, a second VAT rate) with
   per-field accuracy metrics.
