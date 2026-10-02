# Fakturama Image-to-Cash — Design

## 1. Goal and principles

One order image in; one saved, verified **Order** and its **linked, paid Invoice** out. Missing
master data (Debtor, payment method, VAT, Product) is created through Fakturama's own UI.

1. **Order first.** The New Order stays open throughout. Its Debtor and Product selectors are the
   existence checks; after creating a record, the flow returns to the same Order and selects it.
2. **Fail closed.** Any doubt stops the run for manual review, with the reason and evidence.
3. **Verify every step.** Every write is read back; every save is confirmed in Data > Documents.
4. **Save exactly once.** A save is verified, never retried, so it cannot create duplicates.
5. **No coordinates.** Controls are found by meaning; pixels only where UI Automation is blind.

## 2. Key assumptions

* English Fakturama 2.x with a wizard-initialised workspace; nobody touches the desktop during a run.
* The image is the only source of truth: nothing is guessed or defaulted.
* "Exact" means equal after ignoring case and extra spaces. A row that shares the identity but
  differs elsewhere (same company in another city, same SKU with another name) is a conflict and stops.
* Contact "Marta Klein" → First Name / Name by the last word. The source Customer ID is not used.
* Billing ≠ delivery: the Main address gets the Invoice role; an extra address gets the Delivery role.
* Payment methods are looked up/created **before** opening New Contact, because the Debtor editor
  loads its Payment list only once (the one reordering of the PDF).
* Product gross price = unit net × (1 + VAT %), rounded to 2 decimals; line discounts stay on the line.
* Only "PAID" ticks *paid* (with the payment date and the full total); otherwise nothing is invented.
* One External Reference → at most one Order and one Invoice.

## 3. Architecture

| Layer | Responsibility |
|---|---|
| **extraction** | image → validated, typed order |
| **workflow** | the PDF procedure: stages, matching rules, stop/resume decisions |
| **fakturama** | page objects for Fakturama's screens (editors, selectors, lists) |
| **ui** | generic UI Automation: find, wait, act-and-verify, read grids, evidence |

Rules such as matching, pricing, reconciliation and resume are pure functions, unit-tested without
Fakturama. All UI strings live in one labels file. A CLI and a small GUI drive the same flow.

## 4. Image extraction

OCR finds the text; an LLM only decides which text is which field; Python checks everything.

1. **PaddleOCR** (local) reads text with positions and confidence.
2. Text is grouped into **layout rows**, so tables and label/value pairs keep their structure.
3. **Groq gpt-oss-120b** (text only) maps rows to a schema, copying values **verbatim**: no
   reformatting, no arithmetic.
4. **Grounding:** every value must exist in the OCR text with good confidence.
5. **Layout check:** each labelled value must sit under its own label. One targeted retry, then stop.
6. **Normalise** to decimals and dates, and **reconcile**: line totals, net, VAT and gross must add up.

## 5. Finding and using Fakturama's controls

Fakturama is a Java SWT app driven through Windows UI Automation (pywinauto). Controls are found by,
in order: **UIA name/type** (SWT exposes tooltips as names) → **the nearest input to a visible
label** → **position within a container** (e.g. the *upper* icon beside "Addresses", never the
green +). Positions are always read live.

Lists and selector dialogs are custom-drawn **NatTable** grids with no rows in UIA. Their container
is found through UIA; inside it, grid lines are detected and **each cell is OCR'd separately**.

Every action is verified by reading it back. Combos are set with the keyboard (UIA selection often
changes only the display), dates are typed segment by segment, and waits poll real conditions
instead of sleeping.

## 6. The flow

1. **Extract** the image; check that the External Reference is not already in Documents.
2. **New Order:** keep the proposed number; set date, Cust.Ref., Net, With VAT.
3. **Debtor:** search from the Order. One exact match → select; none → create (with its payment
   method) and select it from the Order; conflict → stop. Verify both addresses.
4. **Products,** for each line: search the SKU; none → make sure the VAT exists (create it if
   missing), create the Product, select it. Set Qty, price, VAT and discount; verify the line price.
5. **Order:** verify lines and totals, save once, confirm the row in Documents.
6. **Invoice** from the Order's follow-up area: verify the copied data, set the payment method and
   paid status, save once, confirm Invoice and Order in Documents and the persisted payment fields.

## 7. Manual review and resume

A manual review is a safe stop: it names the step, the reason and the evidence, leaves nothing
half-saved, and exits with code 2. Typical causes: an unreadable or inconsistent image, an
ambiguous or conflicting match, a payment method that is not available, an unreadable list.

After a person fixes the cause, **Resume** continues from **what is actually saved** in Documents,
never from a local state file:

| Already saved | Resume does |
|---|---|
| nothing | the normal flow; master data created earlier is found and reused |
| the Order | re-verify it read-only, create the linked Invoice, finish |
| Order + Invoice | re-verify; change and save only what differs |
| anything unexpected | stop for manual review |

Resume never creates a second Order or Invoice: documents are matched by exact number, and
Fakturama's own "already has a follow-up" warning is a second guard.

## 8. Evidence and testing

Each step leaves a screenshot and a log line with the values compared; each run produces a
one-page HTML report. Unit tests cover the rules and grid reading on real screenshots; six
generated order images test extraction end to end; live runs covered the create, select, unpaid,
manual-review and resume paths.

## 9. Trade-offs

| Choice | Benefit | Cost |
|---|---|---|
| OCR + text-only LLM | every value traceable to pixels; deterministic checks | table layout rebuilt from boxes |
| Fail closed | never posts wrong financial data | more manual reviews on messy images |
| UIA first, OCR for grids | robust to layout and resolution | grid reads are slower and need a clear screen |
| Real mouse and keyboard | the events SWT actually listens to | the desktop is busy during a run |
| UI-only verification | checks what a user sees; no DB coupling | slower than a database query |

## 10. Next steps

Read NatTable rows without OCR (accessibility layer or a Fakturama plugin); run in a dedicated
Windows session on a disposable workspace; exercise every conflict branch live; test harder images
(photos, blur, more lines, other VAT rates).
