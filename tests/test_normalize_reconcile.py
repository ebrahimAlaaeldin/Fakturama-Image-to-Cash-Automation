from datetime import date
from decimal import Decimal as D

import pytest

from fakturama_i2c.errors import ExtractionError
from fakturama_i2c.extraction.normalize import parse_date, parse_decimal, split_name, to_order
from fakturama_i2c.extraction.reconcile import ensure_reconciled, reconcile
from fakturama_i2c.models import PaidStatus


@pytest.mark.parametrize(
    "text,expected",
    [
        ("EUR 570.00", D("570.00")),
        ("1.234,56", D("1234.56")),
        ("1,234.56", D("1234.56")),
        ("10%", D("10")),
        ("19,00 %", D("19.00")),
        ("1,000", D("1000")),
        ("-10.00 %", D("-10.00")),
    ],
)
def test_parse_decimal(text, expected):
    assert parse_decimal(text) == expected


def test_parse_date():
    assert parse_date("2026-07-14") == date(2026, 7, 14)
    assert parse_date("14.07.2026") == date(2026, 7, 14)


def test_split_name():
    assert split_name("Marta Klein") == ("Marta", "Klein")
    assert split_name("Anna Maria  von Berg") == ("Anna Maria von", "Berg")


def test_sample_normalizes(order):
    assert order.external_reference == "WEB-2026-0714-A17"
    assert order.order_date == date(2026, 7, 14)
    assert order.customer.first_name == "Marta" and order.customer.last_name == "Klein"
    assert order.payment.status is PaidStatus.PAID and order.payment.date == date(2026, 7, 18)
    assert [i.sku for i in order.items] == ["CHR-ERG-01", "MAT-DESK-02"]
    assert order.items[0].discount_pct == D("10")
    assert order.totals.gross == D("678.30")
    assert not order.billing_equals_delivery


def test_sample_reconciles(order):
    assert reconcile(order) == []


def test_misread_digit_is_caught(raw_order):
    raw_order.items[0].unit_net = "260.00"  # OCR misread 5 -> 6
    with pytest.raises(ExtractionError) as exc:
        ensure_reconciled(to_order(raw_order))
    assert any("CHR-ERG-01" in i for i in exc.value.issues)


def test_paid_without_date_rejected(raw_order):
    raw_order.payment_date = ""
    with pytest.raises(ExtractionError):
        to_order(raw_order)


def test_zip_left_in_city_is_split(raw_order):
    raw_order.billing_address.zip = ""
    raw_order.billing_address.city = "10117 Berlin"
    order = to_order(raw_order)
    assert (order.billing_address.zip, order.billing_address.city) == ("10117", "Berlin")


def test_missing_alias_is_rejected(raw_order):
    raw_order.customer_alias = ""
    with pytest.raises(ExtractionError):
        to_order(raw_order)


def test_missing_fields_listed(raw_order):
    from fakturama_i2c.extraction.llm_structurer import missing_fields

    assert missing_fields(raw_order) == []
    raw_order.billing_address.zip = ""
    raw_order.customer_alias = ""
    assert missing_fields(raw_order) == ["customer_alias", "billing_address.zip"]


def test_payment_method_snaps_to_known_names():
    from fakturama_i2c.extraction.normalize import canonical_payment_method as canon
    assert canon("BankTransfer") == "Bank Transfer"
    assert canon("credit card") == "Credit Card"
    assert canon("SEPA DirectDebit") == "SEPA Direct Debit"
    assert canon("PayPal") == "PayPal"  # unknown methods are kept as printed
