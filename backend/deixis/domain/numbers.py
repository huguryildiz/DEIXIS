"""Numbers a cell value states that none of its quotes state.

An anchor check finds the quote in the passage; it does not show the value follows from the quote. This narrower check
compares numbers only: a value of 3 dB that quotes a sentence saying 2 dB is named. A count or a unit conversion the
model derived is named too, so the result is a prompt to look, not a rejection.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

# A number, a leading-decimal number (`.5`) or scientific notation (`1e-6`, `.5e-6`); signs are not read, so a range
# `2-5` stays two numbers and the comparison is of sizes.
_NUMBER = re.compile(r"(?:\d+(?:[.,]\d+)*|(?<![\d.,])\.\d+)(?:[eE][-+\u2212]?\d+)?")  # PDF text often writes the exponent's minus as U+2212
_THOUSANDS = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?")


def _as_decimal(token: str) -> Decimal | None:
    mantissa, _, exponent = token.lower().replace("\u2212", "-").partition("e")
    mantissa = mantissa.replace(",", "") if _THOUSANDS.fullmatch(mantissa) else mantissa.replace(",", ".")
    try:
        return Decimal(mantissa + ("e" + exponent if exponent else ""))
    except InvalidOperation:
        return None


def numbers_in(text: str) -> set[Decimal]:
    """Every number written in the text, unsigned and exact; `1,000` is a thousand, `0,5` a half, `802.11` one number."""
    found = set()
    for token in _NUMBER.findall(text):
        number = _as_decimal(token)
        if number is None:
            # `1.2.3` is not one number; its parts are.
            found.update(Decimal(part) for part in re.findall(r"\d+", token))
        else:
            found.add(number)
    return found


def value_numbers(value: Any) -> set[Decimal]:
    """The numbers a cell value states: a number value's number, and numbers written in its text fields."""
    if not isinstance(value, dict):
        return set()
    found = set()
    number = value.get("number")
    if isinstance(number, (int, float)) and not isinstance(number, bool):
        # repr is the shortest text that reads back as the stored float: 0.1 is 0.1, not its binary expansion.
        found.add(Decimal(repr(number)).copy_abs())  # abs() would round to the context's 28 digits
    for key, text in value.items():
        # `as_stated` is shown as the source's own words, so its numbers are checked too.
        if key not in ("number", "option_ids") and isinstance(text, str):
            found |= numbers_in(text)
    return found


def unquoted_numbers(value: Any, quotes: list[str | None]) -> list[Decimal]:
    """Numbers the value states that no quote states, smallest first; empty when the value states none.

    Compared exactly as decimals (`2.0` is `2`, `1e-6` is `0.000001`). A quote a failed validation left without located
    text (`None`) states nothing."""
    stated = value_numbers(value)
    if not stated:
        return []
    quoted = set().union(set(), *(numbers_in(q) for q in quotes if q))
    return sorted(n for n in stated if n not in quoted)
