"""Extraction on rendered stress orders (samples/stress, see tools/render_order.py): more lines,
mixed VAT, thousands separators, other payment methods/statuses, umlauts, a phone photo.

Integration test (PaddleOCR + Groq), opt-in:
    $env:RUN_INTEGRATION=1; .venv\\Scripts\\python -m pytest tests/test_stress_extraction.py -v
"""

import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from fakturama_i2c.config import settings
from fakturama_i2c.errors import ExtractionError
from fakturama_i2c.extraction.pipeline import extract

STRESS = Path(__file__).resolve().parents[1] / "samples" / "stress"
EXPECTED = json.loads((STRESS / "expected.json").read_text(encoding="utf-8")) if (STRESS / "expected.json").exists() else {}

pytestmark = pytest.mark.skipif(not os.environ.get("RUN_INTEGRATION"), reason="set RUN_INTEGRATION=1 (OCR + LLM)")


def _num(text: str) -> str:
    return format(Decimal(text).normalize(), "f")


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_stress(name, tmp_path):
    e = EXPECTED[name]["expected"]
    if EXPECTED[name].get("expect_error"):  # an image that must stop for manual review, never guess
        with pytest.raises(ExtractionError):
            extract(STRESS / EXPECTED[name]["image"], settings, tmp_path)
        return
    o = extract(STRESS / EXPECTED[name]["image"], settings, tmp_path)
    method, status, paid_on = e["payment"]
    checks = {
        "reference": (o.external_reference, e["external_reference"]),
        "order date": (o.order_date, date.fromisoformat(e["order_date"])),
        "company": (o.customer.company, e["company"]),
        "contact last name": (o.customer.last_name, e["contact_last"]),
        "alias": (o.customer.alias, e["alias"]),
        "billing": ([o.billing_address.street, o.billing_address.zip, o.billing_address.city], e["billing"]),
        "delivery": ([o.delivery_address.street, o.delivery_address.zip, o.delivery_address.city], e["delivery"]),
        "payment method": (o.payment.method, method),
        "paid": (o.payment.status.value == "PAID", status == "PAID"),
        "payment date": (o.payment.date, date.fromisoformat(paid_on) if paid_on else None),
        "items": ([[i.sku, i.description, _num(str(i.quantity)), f"{i.unit_net:.2f}", _num(str(i.discount_pct)),
                    _num(str(i.vat_pct)), f"{i.line_net:.2f}"] for i in o.items],
                  [[s, d, _num(q), u, _num(di), _num(v), ln] for s, d, q, u, di, v, ln in e["items"]]),
        "totals": ([o.totals.net, o.totals.vat, o.totals.gross], [Decimal(x) for x in e["totals"]]),
    }
    wrong = {k: {"got": g, "expected": x} for k, (g, x) in checks.items() if g != x}
    assert not wrong, json.dumps(wrong, indent=1, default=str, ensure_ascii=False)
