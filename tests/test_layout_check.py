"""Layout cross-check on the sample's real OCR tokens (no OCR/LLM needed)."""

import json

from fakturama_i2c.extraction.layout_check import layout_conflicts, value_below
from fakturama_i2c.vision.ocr import OcrToken
from tests.conftest import FIXTURES

TOKENS = [OcrToken(**t) for t in json.loads((FIXTURES / "sample_ocr_tokens.json").read_text(encoding="utf-8"))]


def test_values_below_labels():
    assert value_below(TOKENS, "CUSTOMER ALIAS") == "NORTHSTAR-BERLIN"
    assert value_below(TOKENS, "EMAIL") == "marta.klein@example.test"
    assert value_below(TOKENS, "PAYMENT DATE") == "2026-07-18"


def test_correct_extraction_has_no_conflicts(raw_order):
    raw_order.phone = "+49 30 55501420"  # as OCR read it
    assert layout_conflicts(raw_order, TOKENS) == {}


def test_alias_swapped_with_email_is_caught(raw_order):
    raw_order.phone = "+49 30 55501420"
    raw_order.customer_alias = "marta.klein@example.test"  # the mistake seen live
    assert layout_conflicts(raw_order, TOKENS) == {"customer_alias": "NORTHSTAR-BERLIN"}
