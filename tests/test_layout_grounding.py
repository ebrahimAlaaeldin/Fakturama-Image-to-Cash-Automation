from fakturama_i2c.extraction.grounding_check import check_grounding
from fakturama_i2c.extraction.grounding_check import iter_values
from fakturama_i2c.vision.layout import group_rows, render
from fakturama_i2c.vision.ocr import OcrToken


def tok(text, x, y, conf=0.99, w=40, h=10):
    return OcrToken(text, conf, x, y, x + w, y + h)


def test_rows_group_by_y_and_sort_by_x():
    tokens = [tok("19%", 500, 101), tok("CHR-ERG-01", 50, 99), tok("250.00", 400, 100), tok("Total", 50, 200)]
    rows = group_rows(tokens)
    assert [[t.text for t in r] for r in rows] == [["CHR-ERG-01", "250.00", "19%"], ["Total"]]
    assert render(rows).splitlines()[0].startswith('y=105 | x=50 "CHR-ERG-01"')


def _tokens_for(raw, conf=0.99):
    return [tok(v, 0, i * 20, conf) for i, (_, v) in enumerate(iter_values(raw)) if v]


def test_grounded_sample_passes(raw_order):
    assert check_grounding(raw_order, _tokens_for(raw_order), 0.8) == []


def test_hallucinated_value_is_flagged(raw_order):
    tokens = _tokens_for(raw_order)
    raw_order.items[1].sku = "MAT-DESK-03"
    issues = check_grounding(raw_order, tokens, 0.8)
    assert issues == ["items[1].sku='MAT-DESK-03' not found in OCR text"]


def test_low_confidence_is_flagged(raw_order):
    issues = check_grounding(raw_order, _tokens_for(raw_order, conf=0.5), 0.8)
    assert any("external_reference" in i and "low-confidence" in i for i in issues)


def test_multi_token_value_is_found(raw_order):
    tokens = [*_tokens_for(raw_order), tok("Acme", 0, 999), tok("Widgets AG", 60, 999)]
    raw_order.company = "Acme Widgets AG"
    assert not [i for i in check_grounding(raw_order, tokens, 0.8) if i.startswith("company")]


def test_accent_conflict_is_detected():
    from fakturama_i2c.extraction.grounding_check import accent_conflicts
    from fakturama_i2c.vision.ocr import OcrToken

    def tok(text):
        return OcrToken(text=text, conf=0.95, x0=0, y0=0, x1=10, y1=10)

    assert accent_conflicts([tok("Müller & Söhne GmbH"), tok("Muller&Sohne GmbH")])  # blurry photo, seen live
    assert not accent_conflicts([tok("Müller & Söhne GmbH"), tok("80331 München")])  # consistent
    assert not accent_conflicts([tok("Northstar Office GmbH"), tok("Friedrichstrasse 88")])  # no accents
