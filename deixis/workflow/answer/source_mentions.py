"""D131: source names in answer prose come from source records, never from the model.

The model writes `{{source_id}}` where a claim names a source; when the answer is saved, code replaces each mention
with the record's short citation and, at the source's first mention in the answer, its title. The text as the model
wrote it is kept in `mention_texts` so the answer can be shown to a later model step with its handles.
"""

from __future__ import annotations

import json
from typing import Any

from deixis.domain.contracts import SOURCE_MENTION
from deixis.exports.text import in_text_citation


def name(record: dict[str, Any], first: bool) -> str:
    """`Mitrolaris et al. (2026, “Title”)` at a first mention, `Mitrolaris et al. (2026)` after it."""
    who = in_text_citation("mla", {"authors": record["authors"]})
    year = record["year"]
    title = f"“{record['title']}”"
    if who is None:
        return f"{title} ({year})" if year is not None else title
    inside = ", ".join(str(part) for part in ((year, title) if first else (year,)) if part is not None)
    return f"{who} ({inside})" if inside else who


def fill(conn: Any, draft: dict[str, Any]) -> dict[str, Any]:
    """The draft with every mention replaced by its record's name; unchanged when no claim mentions a source."""
    claims = draft.get("claims") or []
    ids = {sid for claim in claims for sid in SOURCE_MENTION.findall(claim.get("text") or "")}
    if not ids:
        return draft
    records = {row["id"]: {"title": row["title"], "year": row["year"], "authors": json.loads(row["authors_json"])}
               for row in conn.execute(f"SELECT id, title, year, authors_json FROM source_versions"
                                       f" WHERE id IN ({','.join('?' * len(ids))})", sorted(ids))}
    seen: set[str] = set()

    def replace(match: Any) -> str:
        sid = match.group(1)
        record = records.get(sid)
        if record is None:  # validation refuses unknown mentions; a vanished record keeps its handle visible
            return match.group(0)
        first = sid not in seen
        seen.add(sid)
        return name(record, first)
    filled = dict(draft, claims=[], mention_texts={})
    for claim in claims:
        filled["mention_texts"][claim["claim_label"]] = claim["text"]
        filled["claims"].append(dict(claim, text=SOURCE_MENTION.sub(replace, claim["text"])))
    return filled
