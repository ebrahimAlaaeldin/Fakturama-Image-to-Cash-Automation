"""--resume: continue after a manual review without ever creating a second Order or Invoice.

The reference is looked up in Data > Documents:

* nothing saved yet         -> the normal flow (master data saved earlier is found and reused)
* Order saved, no Invoice   -> reopen the Order, re-verify it read-only (4.1-4.5), create the
                               follow-up Invoice (4.6) and run section 5
* Order and Invoice saved   -> reopen both, re-verify, apply 5.2-5.3 only where a value differs,
                               save only if something changed, verify 5.5-5.6
* more than one of either   -> stop for manual review

Safety: any saved document for this reference that is not clearly the Order counts as an
Invoice, documents are opened by double-click and identified by their real (UIA) tab title, and
Fakturama's own "there's already a follow-up" warning is always answered No.
"""

from __future__ import annotations

import re

from ...errors import FollowUpExists, ManualReviewRequired, VerificationFailed
from ...fakturama import labels as L
from ...fakturama.document_editor import DocumentEditor
from ...fakturama.documents_view import DocumentsView
from ..context import RunContext
from ..matching import ref_matches, same_document_number
from .debtor import verify_order_addresses
from .invoice import apply_payment, check_copied_data, complete_invoice, save_invoice, verify_invoice
from .order_complete import verify_document_row, verify_lines, verify_totals


def classify_documents(records: list[dict], reference: str) -> tuple[list[int], list[int]]:
    """Pure: Documents rows -> (indexes of Orders, indexes of other documents) for ``reference``.
    Anything that is not clearly an Order counts as 'other' (treated as an Invoice), so an
    OCR-misread invoice number can never make resume create a second Invoice."""
    mine = [i for i, r in enumerate(records) if ref_matches(r.get("cust_ref"), reference)]
    orders = [i for i in mine if re.match(L.ORDER_NUMBER_PATTERN, records[i].get("number", ""))]
    return orders, [i for i in mine if i not in orders]


def plan_resume(orders: int, others: int) -> str:
    """Pure: what resume does given how many Orders / other documents are saved."""
    if orders > 1 or others > 1:
        return "review: more than one saved Order/other document for this reference"
    if others and not orders:
        return "review: an Invoice exists without its Order"
    if orders and others:
        return "continue invoice"  # reopen both, apply 5.2-5.3 only where different, verify
    if orders:
        return "create invoice"  # reopen Order, verify read-only, follow-up Invoice, section 5
    return "normal"  # nothing saved: the normal flow, reusing master data


def find_saved_documents(ctx: RunContext) -> tuple[list[int], list[int], DocumentsView]:
    """Row indexes (in the filtered Documents list) of the saved Order(s) and other documents."""
    ref = ctx.order.external_reference
    with ctx.step("R resume: look up saved documents", cust_ref=ref):
        view = DocumentsView(ctx.app)
        records = view.search(ref, "R")
        orders, others = classify_documents(records, ref)
        ctx.evidence.record("R saved documents", "ok", rows=records, plan=plan_resume(len(orders), len(others)),
                            orders=[records[i]["number"] for i in orders], others=[records[i]["number"] for i in others])
    plan = plan_resume(len(orders), len(others))
    if plan.startswith("review"):
        raise ManualReviewRequired("R", plan.split(": ", 1)[1], {"rows": [records[i] for i in orders + others]})
    return orders, others, view


def resume_from_order(ctx: RunContext, order_index: int, invoice_index: int | None, view: DocumentsView) -> None:
    o = ctx.order
    with ctx.step("R reopen saved Order"):
        ctx.editor = _reuse_or_open(ctx, view, order_index)
        ctx.order_no = ctx.editor.number()
    # 4.1-4.3 read-only: a saved Order is never edited or saved again (PDF: save once)
    verify_order_addresses(ctx, "R 4.1", switch_tabs=True)
    with ctx.step("R 4.1-4.3 verify saved Order", number=ctx.order_no):
        # A docked Documents view can leave the Order grid only one row high. Maximize
        # its editor pane while checking saved lines, then restore the view layout for 4.5.
        ctx.app.set_editor_maximized(ctx.editor.root, True)
        try:
            if ctx.editor.vat_mode().strip() != L.VAT_MODE_WITH_VAT:
                raise VerificationFailed("R 4.1", "saved Order VAT mode", L.VAT_MODE_WITH_VAT, ctx.editor.vat_mode())
            verify_lines(ctx, "R 4.1")
            verify_totals(ctx, ctx.editor, "R 4.3")
        finally:
            ctx.app.set_editor_maximized(ctx.editor.root, False)
    with ctx.step("R 4.5 Order in Documents", number=ctx.order_no):
        verify_document_row(ctx, ctx.order_no, L.STATE_OPEN, o.totals.gross, "R 4.5")

    if invoice_index is None:
        try:
            with ctx.step("4.6-4.7 follow-up Invoice"):
                ctx.app.activate(ctx.editor.root)
                ctx.invoice = ctx.editor.create_followup_invoice()
        except FollowUpExists as exc:  # the list missed it, Fakturama did not: continue with it
            ctx.evidence.record("R existing follow-up", "ok", number=exc.number)
            _continue_invoice(ctx, _find_by_number(ctx, exc.number))
            return
        complete_invoice(ctx)
        return
    _continue_invoice(ctx, invoice_index)


def _continue_invoice(ctx: RunContext, invoice_index: int) -> None:
    view = DocumentsView(ctx.app)  # re-filter: verifying the Order used the same list
    view.search(ctx.order.external_reference, "R")
    with ctx.step("R reopen saved Invoice"):
        ctx.invoice = _reuse_or_open(ctx, view, invoice_index)
        ctx.invoice_no = ctx.invoice.number()
    if re.match(L.ORDER_NUMBER_PATTERN, ctx.invoice_no):
        raise ManualReviewRequired("R", f"expected an Invoice, opened {ctx.invoice_no}", {})
    check_copied_data(ctx, saved=True)
    apply_payment(ctx)
    save_invoice(ctx, only_if_changed=True)
    verify_invoice(ctx)


def _reuse_or_open(ctx: RunContext, view: DocumentsView, index: int) -> DocumentEditor:
    """Reuse an editor already open for this row's document, else double-click the row and take
    the tab that appears (its title comes from UIA, not from OCR)."""
    number = view.grid.as_records(view.rows)[index].get("number", "")
    for item in ctx.app.tab_items():
        title = (item.element_info.name or "").lstrip("*")
        if title and same_document_number(number, title):  # never a neighbouring number
            return DocumentEditor(ctx.app, ctx.app.show_tab(title))
    return DocumentEditor(ctx.app, view.open_row(index).root)


def _find_by_number(ctx: RunContext, number: str) -> int:
    view = DocumentsView(ctx.app)
    records = view.search(ctx.order.external_reference, "R")
    hits = [i for i, r in enumerate(records) if same_document_number(r.get("number"), number)]
    if len(hits) != 1:
        raise ManualReviewRequired("R", f"Fakturama names follow-up {number}, but it is not (once) in Documents",
                                   {"rows": records})
    return hits[0]
