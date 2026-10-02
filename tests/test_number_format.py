from fakturama_i2c.ui import act


def test_learns_comma_locale_and_formats():
    assert act.learn_decimal_separator("0,00\xa0€") == ","
    assert act.fmt_number("297.50") == "297,50"
    assert act.fmt_number(19, None) == "19"
    assert act.learn_decimal_separator("$0.00") == "."
    assert act.fmt_number("297.5") == "297.50"
