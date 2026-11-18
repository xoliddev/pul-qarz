"""Money as integers (pure). 1 so'm = 100 tiyin, 1 dollar = 100 cents. Floats are never used."""

from __future__ import annotations

import re

from .ledger import CURRENCIES

MINOR = 100
MAX_MAJOR = 10**12
_GROUPED = re.compile(r"^(\d{1,3}(?:[ ,]\d{3})+)(?:[.,](\d{1,2}))?$")
_PLAIN = re.compile(r"^(\d+)(?:[.,](\d{1,2}))?$")


class MoneyError(ValueError):
    pass


def parse_amount(text: str) -> int:
    """Turn user text such as ``1 500 000``, ``1,500,000`` or ``150.5`` into minor units.

    A comma or dot followed by one or two digits at the end is the decimal part; groups of three
    digits separated by spaces or commas are thousands.
    """
    if not isinstance(text, str) or len(text) > 32:
        raise MoneyError("bad_amount")
    s = re.sub(r"[\s  _]+", " ", text.strip()).strip()
    s = re.sub(r"(?i)\s*(so'?m|sum|сум|uzs|usd|\$)\s*$", "", s).lstrip("$ ").strip()
    m = _GROUPED.match(s) or _PLAIN.match(s)
    if not m:
        raise MoneyError("bad_amount")
    major = int(re.sub(r"[ ,]", "", m.group(1)))
    frac = (m.group(2) or "").ljust(2, "0")
    value = major * MINOR + int(frac or 0)
    if value <= 0 or major >= MAX_MAJOR:
        raise MoneyError("bad_amount")
    return value


def group(n: int) -> str:
    s = str(n)
    out = []
    while len(s) > 3:
        out.insert(0, s[-3:])
        s = s[:-3]
    out.insert(0, s)
    return " ".join(out)


def format_number(minor: int) -> str:
    """``150000050`` -> ``1 500 000,50``; whole amounts drop the decimals."""
    sign = "-" if minor < 0 else ""
    major, cents = divmod(abs(minor), MINOR)
    text = group(major)
    if cents:
        text += f",{cents:02d}"
    return sign + text


def check_currency(cur: str) -> str:
    if cur not in CURRENCIES:
        raise MoneyError("bad_currency")
    return cur
