from decimal import Decimal as D

from fakturama_i2c.workflow.matching import MatchKind, match_debtor, match_payment, match_product, match_vat

DEBTOR = {"company": "Northstar Office GmbH", "first_name": "Marta", "name": "Klein", "zip": "10117", "city": "Berlin"}


def test_debtor_exact(order):
    m = match_debtor([{"company": "Other AG"}, DEBTOR], order.customer, order.billing_address)
    assert m.kind is MatchKind.EXACT and m.index == 1


def test_debtor_none(order):
    assert match_debtor([], order.customer, order.billing_address).kind is MatchKind.NONE


def test_debtor_duplicate_is_ambiguous(order):
    assert match_debtor([DEBTOR, dict(DEBTOR)], order.customer, order.billing_address).kind is MatchKind.AMBIGUOUS


def test_debtor_same_company_other_city_is_conflict(order):
    other = {**DEBTOR, "zip": "80331", "city": "Muenchen"}
    assert match_debtor([other], order.customer, order.billing_address).kind is MatchKind.AMBIGUOUS


def test_debtor_case_and_whitespace_insensitive(order):
    row = {k: f"  {v.upper()} " for k, v in DEBTOR.items()}
    assert match_debtor([row], order.customer, order.billing_address).kind is MatchKind.EXACT


def test_product(order):
    item = order.items[0]
    row = {"item_number": "CHR-ERG-01", "name": "Ergonomic Desk Chair"}
    assert match_product([row], item).kind is MatchKind.EXACT
    assert match_product([{"item_number": "CHR-ERG-011"}], item).kind is MatchKind.NONE
    assert match_product([{"item_number": "CHR-ERG-01", "name": "Stool"}], item).kind is MatchKind.AMBIGUOUS


def test_vat():
    rows = [{"name": "Tax-free", "value": "0.00 %"}, {"name": "VAT 19%", "value": "19.00 %"}]
    assert match_vat(rows, D("19")).kind is MatchKind.EXACT
    assert match_vat(rows[:1], D("19")).kind is MatchKind.NONE
    assert match_vat([{"name": "VAT 19%", "value": "16.00 %"}], D("19")).kind is MatchKind.AMBIGUOUS
    assert match_vat([{"name": "VAT 19%", "value": "19 %", "code": "AE (Reverse charge)"}], D("19")).kind is (
        MatchKind.AMBIGUOUS
    )


def test_payment():
    assert match_payment([{"name": "Bank Transfer"}], "bank transfer").kind is MatchKind.EXACT
    assert match_payment([{"name": "Bank Transfer"}, {"name": "Bank Transfer"}], "Bank Transfer").kind is (
        MatchKind.AMBIGUOUS
    )
    assert match_payment([{"name": "Cash"}], "Bank Transfer").kind is MatchKind.NONE


def test_truncated_cell_matches_on_visible_prefix(order):
    row = {"item_number": "CHR-ERG-01", "name": "Ergonomic Des.."}
    assert match_product([row], order.items[0]).kind is MatchKind.EXACT
    assert match_product([{"item_number": "CHR-ERG-01", "name": "Ergonomic Sto.."}], order.items[0]).kind is (
        MatchKind.AMBIGUOUS
    )


def test_payment_conflicting_definition():
    from fakturama_i2c.fakturama.labels import PAYMENT_CODE_MAP
    from fakturama_i2c.workflow.matching import payment_conflicts

    assert payment_conflicts({"code": "Credit transfer "}, "Bank Transfer", PAYMENT_CODE_MAP) == []
    assert payment_conflicts({"code": "In cash"}, "Bank Transfer", PAYMENT_CODE_MAP) == [
        "payment code is 'In cash', expected 'Credit transfer'"
    ]


def test_partly_read_document_date(order):
    from fakturama_i2c.workflow.stages.order_complete import _same_day

    assert _same_day("Jul 14, 2026", order)
    assert _same_day("14,2026", order)  # OCR lost the month name
    assert not _same_day("15,2026", order)
    assert not _same_day("Jul 14, 2025", order)


def test_ref_matches_tolerates_ocr_noise():
    from fakturama_i2c.workflow.matching import ref_matches

    ref = "WEB-2026-0714-A17"
    assert ref_matches("WEB-2026-0714-A17", ref)
    assert ref_matches("WVEB-2026-0714-A17", ref)  # OCR stutter seen live
    assert ref_matches("WEB-2026-0714-A..", ref)  # truncated cell
    assert not ref_matches("WEB-2026-0815-B02", ref)
    assert not ref_matches("", ref)


def test_document_state_is_a_whole_word():
    from fakturama_i2c.workflow.matching import state_matches
    assert state_matches("V paid", "paid")  # check-mark icon OCR'd as 'V'
    assert state_matches("0unpaid", "unpaid")  # icon OCR'd as '0', glued to the word
    assert state_matches("圈open", "open")  # icon OCR'd as a CJK glyph
    assert not state_matches("0unpaid", "paid")  # seen live: a substring check would pass this
    assert not state_matches("", "open")
