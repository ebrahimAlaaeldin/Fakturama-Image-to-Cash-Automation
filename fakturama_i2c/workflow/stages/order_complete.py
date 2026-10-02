"""PDF 4.1-4.7: verify and save the Order, check it in Data > Documents, start the linked Invoice."""

from __future__ import annotations

import re

from ...errors import ManualReviewRequired, VerificationFailed
from ...extraction.normalize import key
from ...fakturama.documents_view import DocumentsView
from ...fakturama.items_grid import ItemsGrid
from ...ui.datefield import detect_layout
from .. import pricing
from ..context import RunContext
from ..matching import ref_matches, state_matches
from .debtor import verify_order_addresses
from .vat_mode import keep_with_vat
from .lines import discount_eq, num_eq


def complete_order(ctx: RunContext) -> None:
    o, ed = ctx.order, ctx.editor
    verify_order_addresses(ctx, "4.1")
    keep_with_vat(ctx, "4.1")
    with ctx.step("4.1 verify item lines"):
        verify_lines(ctx, "4.1")
    with ctx.step("4.2 discount 0%, free shipping"):
        ed.ensure_no_discount_free_shipping("4.2")
    with ctx.step("4.3 verify totals", net=o.totals.net, vat=o.totals.vat, gross=o.totals.gross):
        verify_totals(ctx, ed, "4.3")
    with ctx.step("4.4 save Order"):
        ctx.app.save(ed.root, "4.4")
        ctx.order_no = ed.number()
    verify_order_addresses(ctx, "4.4", switch_tabs=True)  # saved now: safe to read both tabs
    with ctx.step("4.5 verify Order in Documents", number=ctx.order_no):
        verify_document_row(ctx, ctx.order_no, "open", o.totals.gross, "4.5")
    with ctx.step("4.6-4.7 follow-up Invoice"):
        ctx.app.activate(ed.root)
        ctx.invoice = ed.create_followup_invoice()


def verify_lines(ctx: RunContext, step: str, editor=None) -> None:
    """Every source item appears exactly once with the source qty, unit price, discount and price."""
    rows = ItemsGrid(editor or ctx.editor).rows()
    if len(rows) != len(ctx.order.items):
        raise VerificationFailed(step, "number of item lines", len(ctx.order.items), len(rows))
    for item in ctx.order.items:
        hits = [r for r in rows if key(r.get("Item No.")) == key(item.sku)]
        if len(hits) != 1:
            raise VerificationFailed(step, f"line for {item.sku}", 1, len(hits))
        r = hits[0]
        expected = {
            "Qty.": (f"{item.quantity}", num_eq),
            "U.Price": (f"{item.unit_net}", num_eq),
            "Discount": (f"{item.discount_pct}", discount_eq),
            "Price": (f"{pricing.line_net(item.quantity, item.unit_net, item.discount_pct)}", num_eq),
        }
        for col, (value, eq) in expected.items():
            if not eq(value, r.get(col)):
                raise VerificationFailed(step, f"{item.sku} {col}", value, r.get(col))


def verify_totals(ctx: RunContext, editor, step: str) -> None:
    t, src = editor.totals(), ctx.order.totals
    for label, shown, expected in (("Total Net", t["net"], src.net), ("VAT", t["vat"], src.vat), ("Total", t["total"], src.gross)):
        if not num_eq(f"{expected}", shown):
            raise VerificationFailed(step, label, expected, shown)
    ctx.evidence.record(f"{step} totals", "ok", shown=t)


def verify_document_row(ctx: RunContext, number: str, state: str, total, step: str, check_date: bool = True) -> dict:
    """Data > Documents: the row with ``number`` has the expected Cust.Ref., state, Total (and the
    Order Date - an Invoice keeps its own proposed date, PDF 5.1)."""
    rows = DocumentsView(ctx.app).search(ctx.order.external_reference, step)
    hits = [r for r in rows if key(r.get("number", "")) == key(number)]
    ctx.evidence.record(f"{step} documents", "found" if hits else "missing", rows=rows)
    if len(hits) != 1:
        raise ManualReviewRequired(step, f"expected one Documents row for {number}", {"rows": rows})
    row = hits[0]
    checks = {
        "Cust.Ref.": ref_matches(row.get("cust_ref"), ctx.order.external_reference),
        "State": state_matches(row.get("state"), state),
        "Total": num_eq(f"{total}", row.get("total", "")),
    }
    if check_date:
        checks["Date"] = _same_day(row.get("date", ""), ctx.order)
    failed = [k for k, ok in checks.items() if not ok]
    if failed:
        raise VerificationFailed(step, f"Documents row {number}: {failed}", {"state": state, "total": total}, row)
    return row


def _same_day(text: str, order) -> bool:
    """Date cell of a Documents row. A fully parsed date must match exactly; if OCR lost part of
    a small cell (e.g. '14,2026' for 'Jul 14, 2026'), day and year must still be present and no
    other number may contradict them. Number, Cust.Ref., state and total are checked strictly."""
    d = order.order_date
    try:
        return detect_layout(text).parse(text) == {"Y": d.year, "M": d.month, "D": d.day}
    except ValueError:
        numbers = {int(n) for n in re.findall(r"\d+", text)}
        return {d.day, d.year} <= numbers and numbers <= {d.day, d.year, d.month}
