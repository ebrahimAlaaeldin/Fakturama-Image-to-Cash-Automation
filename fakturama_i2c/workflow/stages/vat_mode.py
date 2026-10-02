"""PDF 1.7 'keep VAT as With VAT' - re-asserted wherever Fakturama may have changed it."""

from __future__ import annotations

from ...fakturama import labels as L
from ..context import RunContext


def keep_with_vat(ctx: RunContext, step: str, editor=None) -> None:
    """PDF 1.7 'keep VAT as With VAT': selecting a Debtor whose country differs from the
    company's makes Fakturama switch the document to 'Free of Tax' (export rule), which would
    force every line to Tax-free. Restore it before any Product is added."""
    editor = editor or ctx.editor
    with ctx.step(f"{step} keep VAT mode With VAT"):
        before = editor.vat_mode()
        if before.strip() != L.VAT_MODE_WITH_VAT:
            editor.ensure_with_vat(step)
            ctx.evidence.record(f"{step} VAT mode restored", "ok", fakturama_set=before, now=editor.vat_mode())
