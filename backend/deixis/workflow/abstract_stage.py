"""The abstract stage of an `sw` discovery run: what code decides, what the model is asked, and what two runs mean.

Pure: no database, no clock, no network, no model. Everything here is a function of the records, the concept blocks
and the two runs' proposals, so a resumed run re-derives nothing it did not already store and a replay of the same
input gives the same decisions (SW14.6).

Three rules hold this module together:

- **Code decides, the model proposes** (SW1.1). `code_outcome` closes what a title and an abstract already settle;
  the model is asked only for what it leaves open, and it answers with a label, one quote and one sentence. The
  quote is looked for by `contracts.locate_anchor` in the abstract the model was shown, and `combine` turns the two
  runs into one reason code. Nothing here is included: the abstract stage has no `include` outcome (SW1.2).
- **Nothing is dropped.** A work outside the read limit is `abstract_not_read` and the next discovery run of the
  same question reads on from there; a batch whose output was invalid leaves its records `abstract_not_proposed`.
  Both are `unresolved`, which is what a `pending` selection already says.
- **A record without an abstract is never out of scope** (SW5.5), and the codes slice 05 owns are left where they
  are: `code_outcome` reads them and stands aside.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

from deixis.domain.contracts import locate_anchor
from deixis.domain.record_identity import record_kind
from deixis.workflow.ranking import block_forms, blocks_in
from deixis.workflow.vocabulary import GATE_BLOCKS

# The codes slice 05 wrote and this stage never replaces: a record it already routed elsewhere keeps that routing.
LOOKUP_CODES = ("survey_title_word", "no_abstract", "abstract_not_found")
# The codes this stage owns. A fresh decision carrying any other code is left alone, as slice 05 leaves this one's.
OWNED_CODES = ("blocks_in_title", "both_blocks_missing", "notice_record", "artifact_of_paper", "abstract_not_read",
               "abstract_not_proposed", "runs_agree_candidate", "runs_agree_out_of_scope", "runs_agree_unresolved",
               "runs_disagree_kept_as_candidate", "quote_not_found_kept_as_candidate")
# A work carrying one of these was read by the model under the current question, so it is not read a second time.
MODEL_CODES = ("runs_agree_candidate", "runs_agree_out_of_scope", "runs_agree_unresolved",
               "runs_disagree_kept_as_candidate", "quote_not_found_kept_as_candidate")
# A work carrying one of these was not read yet, whatever else it says: the model is asked about it.
UNREAD_CODES = ("abstract_not_proposed", "abstract_not_read")


# ---- what code alone settles -------------------------------------------------------------------


def code_outcome(record: dict[str, Any], blocks: dict[str, list[str]], links: Iterable[str]) -> str | None:
    """The abstract-stage code this one record asks for without a model, or None when the model may read it.

    `record` carries the record's own fields (`id`, `title`, `abstract`, `doi`, `version_label`) and `decision`,
    the reason code its current abstract decision holds. `blocks` is what `ranking.query_vocabulary` returns and
    `links` the records that carry an open `artifact_of` link. The branches are tried in this order:

    1. A correction, retraction or withdrawal notice is not a paper to read (SW6.2).
    2. An artifact a stored, not-undone link attaches to a paper is that paper's data, not a second paper. An
       artifact **without** such a link goes on as an ordinary record: a Zenodo or figshare DOI can be the only
       copy of a paper, and in slice 03's measurement 85 of 127 pairs were artifacts that got no link.
    3. A decision slice 05 owns stands; this stage neither confirms nor replaces it.
    4. Both gate blocks in the title: a candidate without asking anyone.
    5. The record has an abstract of its own and neither gate block stands in its title or abstract: out of scope.
       One missing block does not close it (SW9.2), and a record with no abstract is never closed here (SW5.5).
    """
    if record_kind(record) == "notice":
        return "notice_record"
    if record_kind(record) == "artifact" and record["id"] in links:
        return "artifact_of_paper"
    if record.get("decision") in LOOKUP_CODES:
        return None
    forms = block_forms({name: blocks.get(name) or [] for name in GATE_BLOCKS})
    if blocks_in(forms, record["title"] or "") == set(GATE_BLOCKS):
        return "blocks_in_title"
    # "Both missing" needs two blocks to be missing from. With one searched block, the record that lacks it is the
    # record SW9.2 leaves to the model ("one missing block does not close"), not one code may put out of scope.
    if (record.get("abstract") and all(forms[name] for name in GATE_BLOCKS)
            and not blocks_in(forms, f"{record['title'] or ''} {record['abstract']}")):
        return "both_blocks_missing"
    return None


def should_write(current: dict[str, Any] | None, code: str, stale: bool = False) -> bool:
    """Whether this stage writes `code` over the record's current decision (slice 05's `_should_write`, same spirit).

    The same code again writes nothing, so a second discovery run does not close a row and reopen it merely because
    its step identifier and protocol digest are new. A code another step owns is left alone while it is fresh.

    A stale decision is always rewritten, the same code included: the record has now been judged under the question
    the research is actually asking, and a row left at the old revision would read as stale for ever and be read
    again by every later run.
    """
    if current is None or stale:
        return True
    if current["reason_code"] == code:
        return False
    return current["reason_code"] in OWNED_CODES


# ---- which works the model reads, in which batches ----------------------------------------------


def reading_version(work: dict[str, Any]) -> str | None:
    """The one version of the work whose title and abstract the model is shown, or None when there is none.

    The work's head when the head qualifies, else the qualifying version with the smallest identifier — so which
    version a provider happened to return first cannot change what is read. A version qualifies when it has an
    abstract of its own and code left it open; that closes slice 05's gap, where a head without its own abstract
    was never read although another version of its work carried one.
    """
    eligible = [version["id"] for version in work["versions"]
                if version.get("has_abstract") and version.get("code") is None
                and version.get("decision") not in LOOKUP_CODES]
    if not eligible:
        return None
    return work["head"] if work["head"] in eligible else min(eligible)


def _wants_model(version: dict[str, Any]) -> bool:
    """Whether the version's own abstract decision leaves it to be read: none yet, unread, or gone stale.

    A fresh decision from the two model runs is not read again; that is what "the next run reads on from where the
    first stopped" means, and it is why the same record is never asked about twice.
    """
    return version.get("decision") is None or version["decision"] in UNREAD_CODES or bool(version.get("stale"))


def read_plan(order: list[str], works: list[dict[str, Any]], limit: int, batch: int) -> dict[str, Any]:
    """The works the model reads, cut into batches, and the works left over; the unit is the work (SW9.4).

    Each work is `{"work_id", "head", "versions": [...]}`, and each version carries `id`, `has_abstract`, `code`
    (this run's `code_outcome`), `decision` (the reason code it currently holds), `decided_by` and `stale`. A work
    is read when no version of it is a code candidate, no version carries the user's own decision, it has a reading
    version, and that version's decision leaves it to be read.

    The order is where the work's head stands in `order`, the inspection order the ranking stored; a work the
    ranking did not place goes last, by identifier, so nothing depends on a dictionary's iteration. The first
    `limit` works are cut into batches of `batch`; the rest are `not_read`. No work is in both and none is lost.
    """
    place = {svid: position for position, svid in enumerate(order)}
    wanted: list[tuple[int, str, str]] = []
    for work in works:
        if any(version.get("code") == "blocks_in_title" for version in work["versions"]):
            continue
        if any(version.get("decided_by") == "human" for version in work["versions"]):
            continue
        svid = reading_version(work)
        if svid is None:
            continue
        version = next(v for v in work["versions"] if v["id"] == svid)
        if not _wants_model(version):
            continue
        wanted.append((place.get(work["head"], len(place)), work["head"], svid))
    wanted.sort()
    reading = [svid for _, _, svid in wanted]
    read, rest = reading[:limit], reading[limit:]
    return {"batches": [read[start:start + batch] for start in range(0, len(read), batch)], "not_read": rest}


def model_calls(limit: int, batch: int, runs: int) -> int:
    """The model calls a full read of `limit` works costs: one per batch per run (K3; the budget in api/app.py)."""
    return runs * math.ceil(limit / batch) if limit else 0


# ---- what one run proposed, and what two runs mean ----------------------------------------------


def verified(quote: str | None, abstract: str, min_chars: int) -> bool:
    """Whether the quote is that abstract's own words, verbatim (SW1.1).

    `exact` or `normalized` only: a fuzzy match is a paraphrase or a splice, and this stage asks for a copy. The
    lower bound keeps a two-word fragment from standing as evidence for a whole abstract. The text searched is the
    abstract **as the model was shown it** — truncated — so a quote from beyond the cut is not verified either.
    """
    if not quote or len(quote) < min_chars:
        return False
    match = locate_anchor(quote, abstract or "")
    return match is not None and match.kind in ("exact", "normalized")


def combine(first: dict[str, Any] | None, second: dict[str, Any] | None) -> str:
    """One reason code from the two runs' proposals, each `{"label", "quote_verified"}` or None (SW11.4).

    Nothing here drops a record: two runs that disagree, and a label whose quote is not in the abstract, both keep
    the record as a candidate for the full text, because the cheap mistake is one more paper read.
    """
    if first is None or second is None:
        return "abstract_not_proposed"
    labels = (first["label"], second["label"])
    if labels == ("unresolved", "unresolved"):
        return "runs_agree_unresolved"
    if labels[0] != labels[1]:
        return "runs_disagree_kept_as_candidate"
    if not (first["quote_verified"] and second["quote_verified"]):
        return "quote_not_found_kept_as_candidate"
    return "runs_agree_candidate" if labels[0] == "candidate" else "runs_agree_out_of_scope"


def proposals_of(candidates: list[dict[str, Any]], records: list[dict[str, Any]],
                 min_chars: int) -> dict[str, dict[str, Any]]:
    """One run's usable proposals, by candidate identifier (slice 09, Task 2).

    A record-level defect is a warning, not an invalid output, and costs that record its proposal for this run
    only: an identifier the step did not send, an identifier sent twice (the first entry goes too, because nothing
    says which of the two the model meant), and an empty quote under a `candidate` or `out_of_scope` label. A
    record the output never named is in the same position, and `combine` reads all of them as "not proposed".
    """
    shown = {candidate["candidate_id"]: candidate.get("abstract") or "" for candidate in candidates}
    found: dict[str, dict[str, Any]] = {}
    dropped: set[str] = set()
    for record in records:
        cid = record["candidate_id"]
        if cid not in shown or cid in found or cid in dropped:
            dropped.add(cid)
            found.pop(cid, None)
            continue
        quote = (record.get("quote") or "").strip()
        if record["label"] in ("candidate", "out_of_scope") and not quote:
            dropped.add(cid)
            continue
        found[cid] = {"label": record["label"], "quote": quote or None,
                      "quote_verified": verified(quote, shown[cid], min_chars),
                      "rationale": record.get("rationale") or ""}
    return found
