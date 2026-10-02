"""Cross-check simple labelled fields against the OCR layout.

Grounding only proves a value occurs *somewhere* in the image; the LLM once put the e-mail
address into the alias field (both are in the image, so grounding passed). For key/value
fields printed as a small caption with the value directly below it, the value under the label
is compared with the LLM's answer. A label that is not found is skipped, so other layouts are
not rejected - they just get no extra check.
"""

from __future__ import annotations

import re

from ..models import RawOrder
from ..vision.ocr import OcrToken

FIELD_LABELS = {
    "external_reference": "EXTERNAL REFERENCE",
    "order_date": "ORDER DATE",
    "company": "COMPANY",
    "contact_name": "CONTACT NAME",
    "customer_alias": "CUSTOMER ALIAS",
    "email": "EMAIL",
    "phone": "PHONE",
    "payment_method": "PAYMENT METHOD",
    "paid_status": "PAID STATUS",
    "payment_date": "PAYMENT DATE",
}


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def value_below(tokens: list[OcrToken], label: str) -> str | None:
    """Text of the token directly below ``label`` (same left edge, within ~3 label heights)."""
    labels = [t for t in tokens if _compact(t.text) == _compact(label)]
    if len(labels) != 1:
        return None
    lab = labels[0]
    below = [t for t in tokens
             if t is not lab and t.y0 >= lab.y1 - 2 and t.y0 <= lab.y1 + 3 * lab.h and abs(t.x0 - lab.x0) <= 25]
    if not below:
        return None
    return min(below, key=lambda t: t.y0).text


def layout_conflicts(raw: RawOrder, tokens: list[OcrToken]) -> dict[str, str]:
    """{field: value printed under its label} where the LLM answer differs."""
    out = {}
    for field, label in FIELD_LABELS.items():
        shown = value_below(tokens, label)
        if shown is None or shown.casefold() in {lbl.casefold() for lbl in FIELD_LABELS.values()}:
            continue  # label not found, or the next thing below is another label (empty value)
        if _compact(getattr(raw, field)) != _compact(shown):
            out[field] = shown
    return out
