"""Resume decisions without Fakturama: which saved documents count, and what resume does."""

from fakturama_i2c.workflow.stages.resume import classify_documents, plan_resume

REF = "WEB-2026-0714-A17"


def row(number, ref=REF):
    return {"number": number, "cust_ref": ref}


def test_order_and_invoice():
    assert classify_documents([row("INV000001"), row("PO000001")], REF) == ([1], [0])


def test_ocr_noise_seen_live():
    # 'TNV000001' (I read as T) and 'WVEB-...' (stutter) must still count as this reference's Invoice
    assert classify_documents([row("TNV000001", "WVEB-2026-0714-A17"), row("P0000001")], REF) == ([1], [0])


def test_other_references_are_ignored():
    assert classify_documents([row("PO000002", "WEB-2026-0815-B02"), row("PO000001")], REF) == ([1], [])


def test_unknown_document_type_counts_as_invoice():
    # never let an unrecognised document make resume create another Invoice
    assert classify_documents([row("XYZ00009"), row("PO000001")], REF) == ([1], [0])


def test_plans():
    assert plan_resume(0, 0) == "normal"
    assert plan_resume(1, 0) == "create invoice"
    assert plan_resume(1, 1) == "continue invoice"
    assert plan_resume(0, 1).startswith("review")
    assert plan_resume(2, 0).startswith("review")
    assert plan_resume(1, 2).startswith("review")


def test_document_numbers():
    from fakturama_i2c.workflow.matching import same_document_number as same
    assert same("PO000004", "PO000004")
    assert same("P0000004", "PO000004")  # O read as 0
    assert same("TNV000001", "INV000001")  # I read as T
    assert not same("PO000003", "PO000004")  # a neighbouring Order - seen live, must never match
    assert not same("PO000001", "INV000001")  # same running number, other document type
    assert not same("", "PO000001")
