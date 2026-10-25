import pytest

from recon.money import MoneyError, format_minor, parse_minor, validate_currency


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("12.34", 1234),
        ("-12.34", -1234),
        ("(12.34)", -1234),
        ("1,234.56", 123456),
        ("12", 1200),
        ("12.3", 1230),
        ("0.01", 1),
        ("-0.01", -1),
        ("  9.99  ", 999),
    ],
)
def test_parse_minor_is_exact(raw, expected):
    assert parse_minor(raw) == expected


def test_third_decimal_is_rejected():
    with pytest.raises(MoneyError):
        parse_minor("1.005")


def test_garbage_is_rejected():
    for raw in ("", "abc", "1.2.3", "--1"):
        with pytest.raises(MoneyError):
            parse_minor(raw)


def test_format_round_trips():
    assert format_minor(123456, "EUR") == "1,234.56 EUR"
    assert format_minor(-5, "USD") == "-0.05 USD"
    assert format_minor(0) == "0.00"


def test_currency_validation():
    assert validate_currency("eur") == "EUR"
    for bad in ("EU", "EURO", "E1R", ""):
        with pytest.raises(MoneyError):
            validate_currency(bad)
