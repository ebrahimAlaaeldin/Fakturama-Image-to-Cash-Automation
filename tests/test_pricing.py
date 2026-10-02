from decimal import Decimal as D

from fakturama_i2c.workflow import pricing


def test_gross_price_pdf_3_9():
    assert pricing.gross_price(D("250.00"), D("19")) == D("297.50")
    assert pricing.gross_price(D("40.00"), D("19")) == D("47.60")
    assert pricing.gross_price(D("9.99"), D("7")) == D("10.69")  # 10.6893 -> half-up


def test_line_net_pdf_3_16():
    assert pricing.line_net(D("2"), D("250.00"), D("10")) == D("450.00")
    assert pricing.line_net(D("3"), D("40.00"), D("0")) == D("120.00")


def test_document_totals_sample():
    assert pricing.document_totals([(D("450.00"), D("19")), (D("120.00"), D("19"))]) == (
        D("570.00"),
        D("108.30"),
        D("678.30"),
    )


def test_pct_label():
    assert pricing.pct_label(D("19.00")) == "19"
    assert pricing.pct_label(D("7.50")) == "7.5"
