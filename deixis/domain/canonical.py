"""One canonical JSON form and its SHA-256, for every audit hash the product stores (SW14.4).

A hash over raw bytes reports differences that are not differences: another key order, another row order, the same
text written with combining marks. So a value is first normalized — keys sorted, text NFC, sets and tuples turned
into sorted lists and lists — and the digest is taken over that. No other module builds its own digest of a value.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any, Iterable, Mapping


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Mapping):
        return {_normalize(k): _normalize(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        # An unordered collection has no order to record, so it is written in the order its canonical items sort in.
        return sorted((_normalize(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False))
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """The canonical text of a value. `NaN` and infinity have no canonical form and raise `ValueError`."""
    return json.dumps(_normalize(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def canonical_rows(rows: Iterable[Mapping[str, Any]], key: str) -> list[dict[str, Any]]:
    """Rows in the order of their stable identifier, so the digest does not follow the order they arrived in."""
    listed = [dict(row) for row in rows]
    for row in listed:
        if key not in row:
            raise KeyError(key)
    return sorted(listed, key=lambda row: canonical_json(row[key]))


def unordered_pair(a: str, b: str) -> tuple[str, str]:
    """A pair whose two members have no order of their own (two compared records), written one way round."""
    return (a, b) if a <= b else (b, a)
