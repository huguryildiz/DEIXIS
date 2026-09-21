"""Full-text adjudication: two model runs propose, code verifies every quote and decides (SW1, D85).

Pure: no database, no clock, no network, no model. The plan is a function of the works, the inspection order and
the limit. A quote is verified only when `locate_anchor` finds it `exact` or `normalized` on a page the model was
shown. A label writes nothing by itself.

The model is shown a selection of passages, so `criterion_absent` means "absent from the passages shown", and code
may exclude on that. A work is included without the user only when both runs label every part `present` and every
quote verifies.
"""

from __future__ import annotations

from typing import Any

from deixis.domain.contracts import locate_anchor
from deixis.domain.rules import (
    FULLTEXT_CRITERION_PASSAGES,
    FULLTEXT_PASSAGES_PER_CALL,
    FULLTEXT_QUOTE_MIN_CHARS,
    FULLTEXT_READ_LIMIT,
    FULLTEXT_RUNS,
)
from deixis.workflow.criterion import norm
from deixis.workflow.criterion_passages import compile_phrases, criterion_order
from deixis.workflow.fulltext import GROUPS, group_of

# A fresh decision carrying one of these was written by this stage. The work is not read again until the decision
# goes stale. `not_read_yet` is absent on purpose: it is the state this stage replaces.
FRESH_MODEL_CODES = (
    "all_parts_verified",
    "criterion_absent",
    "fulltext_runs_disagree",
    "include_quote_unverified",
    "part_without_evidence",
    "fulltext_runs_agree_unresolved",
    "pdf_identity_unconfirmed",
)
# Codes this stage may replace. A fresh `text_unreadable` or `no_fulltext` belongs to retrieval and is left alone.
OWNED_CODES = ("not_read_yet", *FRESH_MODEL_CODES)

# Re-exported so the protocol body and the flow read the same numbers this module plans with.
PASSAGES_PER_CALL = FULLTEXT_PASSAGES_PER_CALL
CRITERION_PASSAGES = FULLTEXT_CRITERION_PASSAGES
QUOTE_MIN_CHARS = FULLTEXT_QUOTE_MIN_CHARS
RUNS = FULLTEXT_RUNS


def read_budget(effort: str) -> dict[str, int]:
    """The budget a full-text reading run is queued with.

    Read by the API route and by the flow's auto-queue, so a run the user starts and a run a retrieval run leaves
    behind can never be given different room. Two calls per work, and no provider request: the text is already here.
    """
    limit = FULLTEXT_READ_LIMIT[effort]
    return {
        "max_model_calls": FULLTEXT_RUNS * limit,
        "max_provider_requests": 0,
        "max_fulltext_reads": limit,
    }


def should_write(current: dict[str, Any] | None, code: str, stale: bool = False) -> bool:
    """Whether this stage writes `code` over the record's current full-text decision.

    The same fresh code writes nothing. A code this stage does not own — the user's, or retrieval's
    `text_unreadable` / `no_fulltext` — is left alone while it is fresh. A stale decision is always rewritten.
    """
    if current is None or stale:
        return True
    if current["reason_code"] == code:
        return False
    return current["reason_code"] in OWNED_CODES


def _fresh_model(work: dict[str, Any]) -> bool:
    for version in work["versions"]:
        row = version.get("fulltext")
        if row and not row.get("stale") and row["reason_code"] in FRESH_MODEL_CODES:
            return True
    return False


def read_plan(works: list[dict[str, Any]], order: list[str], limit: int) -> dict[str, list[str]]:
    """The works this run reads, and the works its limit did not reach. Nothing is dropped.

    Eligible: a retrieval group (`fulltext.group_of`), PDF text on some version, and no fresh decision of this
    stage. A stale decision re-enters. A work the user excluded, a work the user decided at full text, a work
    with no text, and a work already carrying `text_unreadable` or `no_fulltext` with no text are not here —
    the first two because `group_of` returns None, the last because no version has text.

    Order is the group, then the inspection order, then the head identifier. The first `limit` heads are read;
    the rest are `not_reached`.
    """
    place = {head: position for position, head in enumerate(order)}
    ranked: list[tuple[int, int, str]] = []
    for work in works:
        group = group_of(work)
        if group is None or _fresh_model(work):
            continue
        if not any(version.get("has_text") for version in work["versions"]):
            continue
        ranked.append((GROUPS.index(group), place.get(work["head"], len(place)), work["head"]))
    ranked.sort()
    heads = [head for _, _, head in ranked]
    return {"works": heads[:limit], "not_reached": heads[limit:]}


def _part_patterns(criterion: dict[str, Any] | None) -> tuple[list[Any], dict[Any, list[tuple[str, Any]]]]:
    """Cue phrases grouped by the part they belong to, in the criterion's part order.

    A phrase whose part is missing or names no part of this criterion joins the unassigned group, which is read
    after the named parts. `compile_phrases` drops a short or repeated phrase; the part map uses the same
    normalisation, so a dropped phrase never becomes a group.
    """
    phrases = (criterion or {}).get("cue_phrases") or []
    names = [part["name"] for part in (criterion or {}).get("parts") or []]
    known = set(names)
    part_of: dict[str, Any] = {}
    for row in phrases:
        part = row.get("part")
        part_of[norm(row["phrase"])] = part if part in known else None
    compiled = compile_phrases(phrases)
    groups: dict[Any, list[tuple[str, Any]]] = {}
    for phrase, pattern in compiled["patterns"]:
        groups.setdefault(part_of.get(phrase), []).append((phrase, pattern))
    order: list[Any] = [name for name in names if name in groups]
    if None in groups:
        order.append(None)
    return order, groups


def reading_list(passages: list[dict[str, Any]], criterion: dict[str, Any] | None,
                 topic_ranked: list[str], per_call: int, criterion_share: int) -> dict[str, Any]:
    """The passages one call is shown, and whether that was the whole text.

    Abstracts are not given. Fewer pdf passages than `per_call` means the whole text: every one of them, in page
    order. Exactly `per_call` is the selection path, not the whole text. The selection takes criterion passages
    in rounds — round *r* takes each part's *r*-th passage, and a passage already taken yields that part's next
    unchosen one — up to `criterion_share`, then the topic order, then page order. The list never exceeds
    `per_call` and is returned in page order. No phrases means topic order then page order.
    """
    pages = [p for p in passages if p.get("kind", "pdf_page") == "pdf_page"]
    ordered = sorted(pages, key=lambda p: (_page(p), p["id"]))
    if len(ordered) < per_call:
        return {"passages": ordered, "whole_text": True}
    chosen = _select(ordered, criterion, topic_ranked, per_call, criterion_share)
    chosen.sort(key=lambda p: (_page(p), p["id"]))
    return {"passages": chosen, "whole_text": False}


def _page(passage: dict[str, Any]) -> int:
    page = passage.get("physical_page")
    return page if isinstance(page, int) else 10**9


def _select(pages: list[dict[str, Any]], criterion: dict[str, Any] | None, topic_ranked: list[str],
            per_call: int, criterion_share: int) -> list[dict[str, Any]]:
    by_id = {passage["id"]: passage for passage in pages}
    chosen: list[dict[str, Any]] = []
    chosen_ids: set[str] = set()
    order, groups = _part_patterns(criterion)
    if order and criterion_share:
        buckets = {key: criterion_order(pages, groups[key]) for key in order}
        pointers = {key: 0 for key in order}
        while len(chosen) < criterion_share:
            added = False
            for key in order:
                if len(chosen) >= criterion_share:
                    break
                bucket, index = buckets[key], pointers[key]
                while index < len(bucket) and bucket[index]["id"] in chosen_ids:
                    index += 1
                pointers[key] = index
                if index < len(bucket):
                    chosen.append(bucket[index])
                    chosen_ids.add(bucket[index]["id"])
                    pointers[key] = index + 1
                    added = True
            if not added:
                break
    for passage_id in topic_ranked:
        if len(chosen) >= per_call:
            break
        passage = by_id.get(passage_id)
        if passage is not None and passage_id not in chosen_ids:
            chosen.append(passage)
            chosen_ids.add(passage_id)
    for passage in pages:
        if len(chosen) >= per_call:
            break
        if passage["id"] not in chosen_ids:
            chosen.append(passage)
            chosen_ids.add(passage["id"])
    return chosen[:per_call]


def verify(quote: str | None, pages: dict[int, str], named_page: int | None, min_chars: int) -> dict[str, Any]:
    """Whether `quote` is verbatim on a page the model was shown.

    The named page is searched first, then the other shown pages. A page that was not shown is not in `pages` and
    is not searched. `exact` and `normalized` count; a fuzzy match is a paraphrase or a splice and does not. A
    quote shorter than `min_chars` does not.
    """
    text = (quote or "").strip()
    if len(text) < min_chars:
        return {"verified": False, "page": None, "kind": None}
    order = [named_page] if named_page in pages else []
    order += [page for page in sorted(pages) if page != named_page]
    for page in order:
        match = locate_anchor(text, pages[page] or "")
        if match is not None and match.kind in ("exact", "normalized"):
            return {"verified": True, "page": page, "kind": match.kind}
    return {"verified": False, "page": None, "kind": None}


def verdict(labels: list[str]) -> str:
    """One run's reading of the parts: `include`, `not_met`, `partial` or `unclear`."""
    if not labels:
        return "unclear"
    if all(label == "present" for label in labels):
        return "include"
    if "present" in labels:
        return "partial"
    if "absent" in labels:
        return "not_met"
    return "unclear"


def run_view(proposals: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """`{"verdict", "quotes_verified"}` for one run's usable proposals.

    `quotes_verified` is true when every `present` quote was found. A run with no `present` part has nothing to
    fail that check.
    """
    labels = [row["label"] for row in proposals.values()]
    present = [row for row in proposals.values() if row["label"] == "present"]
    return {"verdict": verdict(labels), "quotes_verified": all(row["quote_verified"] for row in present)}


def combine(first: dict[str, Any] | None, second: dict[str, Any] | None) -> str | None:
    """One reason code from the two runs, or None when a run did not answer.

    Identity is not this function's job. The two verdicts are compared only after both runs returned.
    """
    if first is None or second is None:
        return None
    if first["verdict"] != second["verdict"]:
        return "fulltext_runs_disagree"
    view = first["verdict"]
    if view == "include":
        if first["quotes_verified"] and second["quotes_verified"]:
            return "all_parts_verified"
        return "include_quote_unverified"
    if view == "not_met":
        return "criterion_absent"
    if view == "partial":
        return "part_without_evidence"
    return "fulltext_runs_agree_unresolved"


def proposals_of(parts: list[dict[str, Any]], records: list[dict[str, Any]], shown: dict[str, dict[str, Any]],
                 pages: dict[int, str], min_chars: int) -> dict[str, dict[str, Any]]:
    """One run's proposal per criterion part.

    A record-level defect drops that part's proposal for this run and the part is read as `unclear`: an unknown
    part, a part named twice (both copies, because nothing says which the model meant), a missing part, a
    `present` with no quote, and a `passage_id` that was not shown. An unverified quote does not flip the label:
    the part stays `present` and `quote_verified` is false, which is what makes two agreeing include-runs
    `include_quote_unverified` rather than included.
    """
    expected = [part["name"] for part in parts]
    known = set(expected)
    found: dict[str, dict[str, Any]] = {}
    dropped: set[str] = set()
    for record in records:
        name = record.get("part")
        if name not in known or name in found or name in dropped:
            if isinstance(name, str):
                dropped.add(name)
            found.pop(name, None)
            continue
        label = record.get("label")
        quote = (record.get("quote") or "").strip()
        passage_id = record.get("passage_id")
        if label == "present" and (not quote or passage_id not in shown):
            dropped.add(name)
            continue
        if label == "present":
            named = shown[passage_id].get("physical_page")
            checked = verify(quote, pages, named if isinstance(named, int) else None, min_chars)
            found[name] = {"label": "present", "quote": quote, "quote_verified": checked["verified"],
                           "passage_id": passage_id, "page": checked["page"]}
        elif label in ("absent", "unclear"):
            found[name] = {"label": label, "quote": "", "quote_verified": False, "passage_id": None, "page": None}
        else:
            dropped.add(name)
    unclear = {"label": "unclear", "quote": "", "quote_verified": False, "passage_id": None, "page": None}
    return {name: found[name] if name in found and name not in dropped else dict(unclear) for name in expected}
