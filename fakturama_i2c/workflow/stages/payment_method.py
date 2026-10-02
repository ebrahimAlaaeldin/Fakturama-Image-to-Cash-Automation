"""PDF 2.10-2.10.6: the Debtor's payment method, created under Data > terms of payment if missing.

Deviation (README): Fakturama 2.1 fills the Debtor editor's Payment dropdown once, when the
editor opens - a method created while the Debtor editor is open never appears in it. So the
lookup/create part (2.10.1-2.10.6, same rules) runs just *before* 'New Contact', and the
Debtor editor then selects the method (2.10).
"""

from __future__ import annotations

from ...errors import ManualReviewRequired
from ...extraction.normalize import key
from ...fakturama import labels as L
from ...fakturama.debtor_editor import DebtorEditor
from ...fakturama.master_data import PaymentList, fill_payment, payment_definition
from ..context import RunContext, outcome
from ..matching import MatchKind, match_payment, payment_conflicts


def ensure_payment_method_exists(ctx: RunContext) -> None:
    """2.10.1 search Data > terms of payment; 2.10.2 reuse one exact row / stop on conflict /
    green + when missing; 2.10.3-2.10.5 fill; 2.10.6 save once."""
    method = ctx.order.payment.method
    with ctx.step("2.10.1 terms of payment lookup", method=method):
        payments = PaymentList(ctx.app)
        records = payments.search(method, "2.10.1")
        m = match_payment(records, method)
        ctx.evidence.record("2.10.2 payment match", outcome(m), rows=records)
    if m.kind is MatchKind.AMBIGUOUS:
        raise ManualReviewRequired("2.10.2", m.reason, {"candidates": m.candidates})
    if m.kind is MatchKind.EXACT:
        # 2.10.2 'conflicting definition': the list does not show the payment code, so open it
        with ctx.step("2.10.2 payment definition check", method=method):
            editor = payments.open_row(m.index, method)
            definition = payment_definition(editor)
            ctx.app.close_editor(editor.root)
            issues = payment_conflicts(definition, method, L.PAYMENT_CODE_MAP)
            ctx.evidence.record("2.10.2 payment definition", "ok" if not issues else "conflict", **definition)
        if issues:
            raise ManualReviewRequired("2.10.2", "; ".join(issues), {"definition": definition})
        return
    with ctx.step("2.10.3-2.10.5 create payment method", method=method, code=L.PAYMENT_CODE_MAP.get(key(method))):
        editor = payments.create(L.EDITOR_NEW_PAYMENT)
        fill_payment(editor, method, "2.10.3")
    with ctx.step("2.10.6 save payment method"):
        ctx.app.save(editor.root, "2.10.6")
        ctx.created.append(f"payment:{method}")


def select_payment_method(ctx: RunContext, debtor: DebtorEditor) -> None:
    """2.10 / 2.10.6: select the exact method in the Debtor's Payment tab."""
    method = ctx.order.payment.method
    debtor.open_tab(L.TAB_MISC)
    options = debtor.payment_options()
    if not any(key(o) == key(method) for o in options):
        raise ManualReviewRequired("2.10", f"payment method {method!r} not offered by the Debtor editor", {"options": options})
    debtor.select_payment(method, "2.10")
