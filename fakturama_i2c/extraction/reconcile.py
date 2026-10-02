"""Arithmetic cross-check of an extraction. A mismatch means OCR/LLM misread something -> stop."""

from __future__ import annotations

from ..errors import ExtractionError
from ..models import OrderExtraction
from ..workflow import pricing


def reconcile(order: OrderExtraction) -> list[str]:
    """Return a list of human-readable inconsistencies (empty == consistent)."""
    issues: list[str] = []
    for it in order.items:
        expected = pricing.line_net(it.quantity, it.unit_net, it.discount_pct)
        if expected != it.line_net:
            issues.append(
                f"item {it.position} {it.sku}: {it.quantity} x {it.unit_net} - {it.discount_pct}% = {expected},"
                f" source says {it.line_net}"
            )
    net, vat, gross = pricing.document_totals((it.line_net, it.vat_pct) for it in order.items)
    t = order.totals
    if net != t.net:
        issues.append(f"net total: lines sum to {net}, source says {t.net}")
    if vat != t.vat:
        issues.append(f"VAT total: computed {vat}, source says {t.vat}")
    if t.net + t.vat != t.gross:
        issues.append(f"gross total: {t.net} + {t.vat} != {t.gross}")
    return issues


def ensure_reconciled(order: OrderExtraction) -> None:
    issues = reconcile(order)
    if issues:
        raise ExtractionError("extracted numbers do not reconcile", issues)
