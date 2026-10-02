"""Extraction on the generated test-case images (samples/cases, see tools/make_test_cases.py).

Integration test: runs PaddleOCR + the Groq LLM, so it is opt-in:
    set RUN_INTEGRATION=1 & .venv\\Scripts\\python -m pytest tests/test_cases_extraction.py -v
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

CASES = Path(__file__).resolve().parents[1] / "samples" / "cases"
EXPECTED = json.loads((CASES / "expected.json").read_text(encoding="utf-8")) if (CASES / "expected.json").exists() else {}

pytestmark = pytest.mark.skipif(not os.environ.get("RUN_INTEGRATION"), reason="set RUN_INTEGRATION=1 (OCR + LLM)")


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_case(name, tmp_path):
    case = EXPECTED[name]
    image = CASES / case["image"]
    if case["expect_error"]:
        with pytest.raises(ExtractionError):
            extract(image, settings, tmp_path)
        return

    o = extract(image, settings, tmp_path)
    e = case["expected"]
    assert o.external_reference == e["external_reference"]
    assert o.order_date == date.fromisoformat(e["order_date"])
    assert o.customer.company == e["company"]
    assert [o.customer.first_name, o.customer.last_name] == e["contact"]
    assert o.customer.alias == e["alias"]
    assert [o.billing_address.street, o.billing_address.zip, o.billing_address.city] == e["billing"]
    assert [o.delivery_address.street, o.delivery_address.zip, o.delivery_address.city] == e["delivery"]
    method, status, paid_on = e["payment"]
    assert o.payment.method == method and o.payment.status.value == status
    assert o.payment.date == (date.fromisoformat(paid_on) if paid_on else None)
    got_items = [[i.sku, i.description, str(i.quantity), f"{i.unit_net:.2f}", format(i.discount_pct.normalize(), "f"),
                  format(i.vat_pct.normalize(), "f"), f"{i.line_net:.2f}"] for i in o.items]
    assert got_items == e["items"]
    assert [o.totals.net, o.totals.vat, o.totals.gross] == [Decimal(x) for x in e["totals"]]
