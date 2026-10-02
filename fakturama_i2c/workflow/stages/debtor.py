"""PDF 2.1-2.13: select the Debtor from the open Order, or create it and come back."""

from __future__ import annotations

from ...errors import ManualReviewRequired, VerificationFailed
from ...extraction.normalize import key
from ...fakturama import labels as L
from ...fakturama.debtor_editor import DebtorEditor
from ...models import Address
from ..context import RunContext, outcome
from ..matching import MatchKind, match_debtor
from .payment_method import ensure_payment_method_exists, select_payment_method
from .vat_mode import keep_with_vat


def resolve_debtor(ctx: RunContext) -> None:
    """2.1-2.3 try to select; 2.5-2.11 create when no exact row; 2.12-2.13 select the new one."""
    m = _search_and_select(ctx, "2.1-2.3")
    if m.kind is MatchKind.NONE:
        create_debtor(ctx)
        m = _search_and_select(ctx, "2.12")
        if m.kind is not MatchKind.EXACT:
            raise ManualReviewRequired("2.12", "newly saved Debtor not selectable from the Order", {"match": m.reason})
    step = "2.13" if "debtor" in ctx.created else "2.4"
    verify_order_addresses(ctx, step)
    keep_with_vat(ctx, step)


def _search_and_select(ctx: RunContext, step: str):
    c, billing = ctx.order.customer, ctx.order.billing_address
    with ctx.step(f"{step} select Debtor", search=c.company) as _:
        dlg = ctx.editor.open_address_selector()
        records = dlg.search(c.company, step)
        if dlg.closed:
            raise ManualReviewRequired(step, "address selector closed itself during search", {})
        m = match_debtor(records, c, billing)
        ctx.evidence.record(f"{step} debtor match", outcome(m), rows=records, reason=m.reason)
        if m.kind is MatchKind.EXACT:
            dlg.choose(m.index)
        else:
            dlg.cancel()
        if m.kind is MatchKind.AMBIGUOUS:
            raise ManualReviewRequired(step, m.reason, {"candidates": m.candidates})
        if m.kind is MatchKind.NONE and any(r.confidence < 0.8 for r in dlg.rows):
            # an unreadable row might be the Debtor - never create a duplicate on a guess
            raise ManualReviewRequired(step, "list has low-confidence OCR rows; cannot rule out a match", {"rows": records})
    return m


def create_debtor(ctx: RunContext) -> None:
    o, c = ctx.order, ctx.order.customer
    ensure_payment_method_exists(ctx)  # 2.10.1-2.10.6, see payment_method.py for why it runs first
    with ctx.step("2.5 New Contact"):
        ed = DebtorEditor.new(ctx.app)
    with ctx.step("2.6 identity", customer_id=ed.customer_id()):
        ed.fill_identity(c.company, c.first_name, c.last_name, "2.6")
    with ctx.step("2.7 main address"):
        ed.open_tab(L.TAB_ADDRESSES)
        ed.fill_address(o.billing_address, "2.7", email=c.email, phone=c.phone, additional_name=_extra_name(o.billing_address, c.company))
    with ctx.step("2.8 address roles", billing_equals_delivery=o.billing_equals_delivery):
        if o.billing_equals_delivery:
            ed.set_roles(invoice=True, delivery=True, step="2.8")
        else:
            # Interpretation (README): PDF 2.8 only covers identical addresses. A different
            # delivery address goes into an additional address with the Delivery role.
            ed.set_roles(invoice=True, delivery=False, step="2.8")
            ed.add_address_tab("2.8")
            d = o.delivery_address
            ed.fill_address(d, "2.8", additional_name=_extra_name(d, c.company))
            ed.set_roles(invoice=False, delivery=True, step="2.8")
    with ctx.step("2.9 miscellaneous", alias=c.alias):
        ed.fill_misc(c.alias, "2.9")
    with ctx.step("2.10 payment method", method=o.payment.method):
        select_payment_method(ctx, ed)
    with ctx.step("2.11 save Debtor"):
        ctx.app.save(ed.root, "2.11")
        ctx.created.append("debtor")
    ctx.app.activate(ctx.editor.root)  # back to the same open Order (1.8)


def _extra_name(addr: Address, company: str) -> str:
    """'additional name' only when the source supplies one (PDF 2.7): an address line-1 that
    differs from the company, e.g. 'Northstar Office Warehouse'."""
    return addr.name if addr.name and key(addr.name) != key(company) else ""


def verify_order_addresses(ctx: RunContext, step: str, editor=None, switch_tabs: bool = False) -> None:
    """The populated address boxes must contain the source street/ZIP/city (PDF 2.4 / 2.13 / 5.1).

    Before a document's single save only the visible (Invoice) address is read - see
    ``DocumentEditor.addresses``; after the save both tabs are read and compared.
    """
    editor = editor or ctx.editor
    with ctx.step(f"{step} verify addresses", both_tabs=switch_tabs):
        shown = editor.addresses(switch_tabs=switch_tabs)
        o = ctx.order
        expected = {L.TAB_INVOICE_ADDRESS: o.billing_address}
        if not o.billing_equals_delivery:
            expected[L.TAB_DELIVERY_ADDRESS] = o.delivery_address
            if L.TAB_DELIVERY_ADDRESS not in shown:
                raise VerificationFailed(step, "Delivery address tab present", True, list(shown))
        for tab, addr in expected.items():
            text = shown.get(tab)
            if text is None:  # not read yet (unsaved document) - verified after the save
                continue
            missing = [v for v in (addr.street, addr.zip, addr.city) if key(v) not in key(text)]
            if missing:
                raise VerificationFailed(step, f"{tab} contains {missing}", addr.model_dump(), text)
        ctx.evidence.record(f"{step} addresses", "ok", shown=shown)
