"""Integer money. No floats touch an amount, ever."""

from __future__ import annotations

import re

_CURRENCY = re.compile(r"^[A-Z]{3}$")


class MoneyError(ValueError):
    """Raised when an amount cannot be read exactly."""


def validate_currency(code: str) -> str:
    code = (code or "").strip().upper()
    if not _CURRENCY.match(code):
        raise MoneyError(f"not an ISO 4217 style currency code: {code!r}")
    return code


def parse_minor(text: str | int) -> int:
    """Parse a human amount into minor units.

    Accepts '12.34', '-12.34', '(12.34)' for negatives, '1,234.56', '12'.
    Rejects anything with more than two decimal places, because a third decimal
    in a settlement file is a signal that the file is not what you think it is.
    """
    if isinstance(text, int) and not isinstance(text, bool):
        return text * 100
    raw = str(text or "").strip()
    if not raw:
        raise MoneyError("empty amount")
    negative: bool = False
    if raw.startswith("(") and raw.endswith(")"):
        negative, raw = True, raw[1:-1]
    raw = raw.replace(",", "").replace(" ", "")
    if raw.startswith("-"):
        negative, raw = not negative, raw[1:]
    if raw.count(".") > 1:
        raise MoneyError(f"malformed amount: {text!r}")
    whole, _, frac = raw.partition(".")
    if not whole.isdigit() or (frac and not frac.isdigit()):
        raise MoneyError(f"malformed amount: {text!r}")
    if len(frac) > 2:
        raise MoneyError(f"more than two decimal places: {text!r}")
    minor = int(whole) * 100 + int(frac.ljust(2, "0") or 0)
    return -minor if negative else minor


def format_minor(minor: int, currency: str = "") -> str:
    sign = "-" if minor < 0 else ""
    whole, frac = divmod(abs(minor), 100)
    body = f"{sign}{whole:,}.{frac:02d}"
    return f"{body} {currency}".strip()
