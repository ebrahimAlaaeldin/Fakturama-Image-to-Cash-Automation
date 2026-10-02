"""PDF 5.1-5.7: complete and verify the linked Invoice."""

from __future__ import annotations

from ...errors import ManualReviewRequired, VerificationFailed
from ...extraction.normalize import key
from ...fakturama import labels as L
from ...models import PaidStatus
from ...ui.datefield import detect_layout
from ..context import RunContext
from .debtor import verify_order_addresses
from .vat_mode import keep_with_vat
from .lines import num_eq
from .order_complete import verify_document_row, verify_lines, verify_totals


def complete_invoice(ctx: RunContext) -> None:
    """The new follow-up Invoice: check, pay, save once, verify."""
    inv = ctx.invoice
    with ctx.step("5.1 keep proposed No./dates") as _:
        proposed = {"no": inv.number(), "date": inv.date_text(), "service_date": inv.labelled_date(L.SERVICE_DATE)}
        ctx.evidence.record("5.1 proposed", "ok", **proposed)
    check_copied_data(ctx)
    apply_payment(ctx)
    save_invoice(ctx)
    verify_invoice(ctx)
    # 5.7: the flow ends here - no Delivery, Correction or Dunning document.


def check_copied_data(ctx: RunContext, saved: bool = False) -> None:
    """5.1: Cust.Ref., Order Date, VAT mode, lines, totals and addresses come from the Order."""
    o, inv = ctx.order, ctx.invoice
    keep_with_vat(ctx, "5.1", editor=inv)
    with ctx.step("5.1 verify data copied from the Order"):
        _check(inv.cust_ref_text(), o.external_reference, "5.1", "Cust.Ref.")
        _check_date(inv.labelled_date(L.ORDER_DATE), o.order_date, "5.1", "Order Date")
        _check(inv.vat_mode(), L.VAT_MODE_WITH_VAT, "5.1", "VAT mode")
        verify_lines(ctx, "5.1", editor=inv)
        verify_totals(ctx, inv, "5.1")
    verify_order_addresses(ctx, "5.1", editor=inv, switch_tabs=saved)


def apply_payment(ctx: RunContext) -> None:
    """5.2 payment method, 5.3 paid status (idempotent: an already-correct field is left alone)."""
    o, inv = ctx.order, ctx.invoice
    with ctx.step("5.2 payment method", method=o.payment.method):
        if key(inv.payment_method()) != key(o.payment.method):
            options = inv.payment_options()
            if not any(key(x) == key(o.payment.method) for x in options):
                raise ManualReviewRequired("5.2", f"payment method {o.payment.method!r} not available", {"options": options})
            inv.set_payment_method(o.payment.method, "5.2")
    with ctx.step("5.3 payment status", paid_status=o.payment.status.value, paid_on=o.payment.date):
        if o.payment.status is PaidStatus.PAID:
            if _already_paid(inv.paid_state(), o):  # resume: never re-enter (and re-save) equal values
                ctx.evidence.record("5.3 payment status", "ok", note="already paid with these values")
            else:
                inv.mark_paid(o.payment.date, o.totals.gross, "5.3")
        elif inv.paid_state()["paid"]:
            raise VerificationFailed("5.3", "paid left clear", False, True)


def save_invoice(ctx: RunContext, only_if_changed: bool = False) -> None:
    inv = ctx.invoice
    with ctx.step("5.4 save Invoice"):
        if only_if_changed and not ctx.app.is_dirty(inv.root):
            ctx.evidence.record("5.4 save Invoice", "ok", note="already saved with these values")
        else:
            ctx.app.save(inv.root, "5.4")
        ctx.invoice_no = inv.number()
    verify_order_addresses(ctx, "5.4", editor=inv, switch_tabs=True)


def verify_invoice(ctx: RunContext) -> None:
    """5.5 Documents rows, 5.6 persisted payment fields."""
    o, inv = ctx.order, ctx.invoice
    paid = o.payment.status is PaidStatus.PAID
    with ctx.step("5.5 verify Invoice and Order in Documents", invoice=ctx.invoice_no, order=ctx.order_no):
        verify_document_row(ctx, ctx.invoice_no, L.STATE_PAID if paid else L.STATE_UNPAID, o.totals.gross, "5.5", check_date=False)
        verify_document_row(ctx, ctx.order_no, L.STATE_OPEN, o.totals.gross, "5.5")
    with ctx.step("5.6 verify persisted payment fields"):
        state = inv.paid_state()  # the editor shows the saved document
        ctx.evidence.record("5.6 payment", "ok", **{k: str(v) for k, v in state.items()})
        _check(state["method"], o.payment.method, "5.6", "payment method")
        if state["paid"] != paid:
            raise VerificationFailed("5.6", "paid", paid, state["paid"])
        if paid:
            _check_date(str(state["date"]), o.payment.date, "5.6", "payment date")
            if not num_eq(f"{o.totals.gross}", str(state["value"])):
                raise VerificationFailed("5.6", "Value", o.totals.gross, state["value"])


def _already_paid(state: dict, o) -> bool:
    if not state.get("paid"):
        return False
    try:
        _check_date(str(state.get("date", "")), o.payment.date, "5.3", "payment date")
    except VerificationFailed:
        return False
    return num_eq(f"{o.totals.gross}", str(state.get("value", "")))


def _check(actual: str, expected: str, step: str, what: str) -> None:
    if key(actual) != key(expected):
        raise VerificationFailed(step, what, expected, actual)


def _check_date(text: str, expected, step: str, what: str) -> None:
    try:
        parsed = detect_layout(text).parse(text)
    except ValueError:
        parsed = None
    if parsed != {"Y": expected.year, "M": expected.month, "D": expected.day}:
        raise VerificationFailed(step, what, expected.isoformat(), text)
