from fakturama_i2c.workflow.narration import caption_for, summarize


def test_longest_prefix_wins():
    assert caption_for("2.10.1 terms of payment lookup").startswith("Payment method: search")
    assert caption_for("2.10 payment method").startswith("Select the payment method")
    assert caption_for("3.8-3.10 product fields").startswith("Product fields")


def test_match_summary():
    assert summarize("2.1-2.3 debtor match", "missing", {"rows": []}) == "0 row(s) in the list: no exact match -> create it"


def test_titles_have_no_pdf_numbers():
    from fakturama_i2c.workflow.narration import CAPTIONS, section_for
    assert section_for("2.10.1 terms of payment lookup") == "Payment method"
    assert section_for("2.1-2.3 debtor match") == "Customer"
    assert section_for("3.5 VAT match") == "VAT rate"
    assert section_for("4.6-4.7 follow-up Invoice") == "Linked Invoice"
    assert section_for("1.1-1.2 extract") == "Reading the order image"
    assert section_for("R saved documents") == "Resuming after manual review"
    assert not any("PDF" in c for c in CAPTIONS.values())
