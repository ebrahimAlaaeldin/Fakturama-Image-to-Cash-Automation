"""PDF 1.3-1.8: open a New Order and fill its header. Plus the idempotency pre-check."""

from __future__ import annotations

from ...errors import ManualReviewRequired
from ...fakturama.document_editor import DocumentEditor
from ...fakturama.documents_view import DocumentsView
from ...ui import act
from ..context import RunContext
from ..matching import ref_matches


def ensure_not_already_imported(ctx: RunContext) -> None:
    """Re-running must not create a second Order for the same External Reference."""
    ref = ctx.order.external_reference
    with ctx.step("0 idempotency check", cust_ref=ref):
        rows = DocumentsView(ctx.app).search(ref, "0")
        hits = [r for r in rows if ref_matches(r.get("cust_ref"), ref)]
        if hits:
            raise ManualReviewRequired("0", f"documents with Cust.Ref. {ref} already exist", {"rows": hits})


def open_order(ctx: RunContext) -> DocumentEditor:
    o = ctx.order
    with ctx.step("1.3 open New Order"):
        ctx.editor = DocumentEditor.new_order(ctx.app)
    with ctx.step("1.4 keep proposed No.") as _:
        ctx.order_no = ctx.editor.number()
        sep = act.learn_decimal_separator(ctx.editor.totals()["total"])  # e.g. '0,00 EUR' -> ','
        ctx.evidence.record("1.4 number format", "ok", decimal_separator=sep)
    with ctx.step("1.5 set Date", value=o.order_date):
        ctx.editor.set_date(o.order_date, "1.5")
    with ctx.step("1.6 set Cust.Ref.", value=o.external_reference):
        ctx.editor.set_cust_ref(o.external_reference, "1.6")
    with ctx.step("1.7 price mode Net, VAT With VAT"):
        ctx.editor.set_price_mode_net("1.7")
        ctx.editor.ensure_with_vat("1.7")
    return ctx.editor
