"""Asking a second source for what a record is missing, and labelling what the record says about itself (SW5, SW9.3).

Three code steps run in an `sw` discovery run, after both search rounds and before screening. None of them calls a
model, none of them changes a selection, and none of them can stop the run:

1. `lookup_plan:<source>` decides who is asked, in which order and in which batch, and stores that plan. The plan is
   read from the stored step output on a resumed run, because "the records still without an abstract" is a different
   list by then and re-deriving the batches would ask about other records.
2. `record_lookup:<source>:<n>` sends one request and writes what came back. What each source answered about each
   record is kept library-wide in `record_lookups`, as links are (D46): a record is asked once per source, by
   whichever research asks first, and only a `failed` answer is asked again.
3. `record_flags` puts the survey labels on the records and writes the abstract-stage decision each record asks for.
   A flag removes nothing and a decision here is always `unresolved`, which is what a `pending` selection already
   says, so `derive_selection` is not called and no selection is written.

A record without an abstract is never out of scope by any route: the lookup leaves it `pending`, and the screening
filter keeps it away from the model rather than letting the model's `exclude` reach its selection (SW5.5).
"""

from __future__ import annotations

from typing import Any, Callable

import httpx

from deixis.config import Settings
from deixis.domain import survey
from deixis.domain.record_identity import record_kind
from deixis.providers import lookup
from deixis.providers.common import MAX_RATE_LIMIT_RETRIES
from deixis.providers.registry import CONNECTORS
from deixis.storage.db import dumps, now, transaction
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.store import Store

MAX_LOOKUP_REQUESTS = 200  # planned requests of one run over both sources; hand-picked, not measured
CROSSREF_CHUNK = 25  # Crossref requests that share one step
THRESHOLDS = {"max_requests": MAX_LOOKUP_REQUESTS, "crossref_chunk": CROSSREF_CHUNK,
              "semantic_scholar_batch": lookup.S2_LOOKUP_BATCH,
              # Retries are requests too; this is the most one run can send before the structural retry bound stops it.
              "max_requests_with_retries": MAX_LOOKUP_REQUESTS * (1 + MAX_RATE_LIMIT_RETRIES)}

ABSTRACT_ORIGINS = {"semantic_scholar": "lookup_semantic_scholar", "crossref": "lookup_crossref_jats"}
SOURCES = ("semantic_scholar", "crossref")
# The abstract-stage codes this step owns. Another step's code (slice 09's) is never replaced by one of these.
OWNED_CODES = ("survey_title_word", "abstract_not_found", "no_abstract", "abstract_not_proposed")


# ---- the words this research reads a title with ---------------------------------------------


def question_forms(vocabulary: dict[str, Any] | None) -> list[str]:
    """Everything the research's own question put into its query or its side lists (claim, exclusion).

    A strong title word that appears here is the subject of the question, not a sign that a record is a survey.
    """
    if not vocabulary:
        return []
    from deixis.workflow.expansion import queried_form, queried_terms  # expansion reads no lookup
    return ([queried_form(term) for term in queried_terms(vocabulary)]
            + list(vocabulary.get("claim_words") or []) + list(vocabulary.get("exclusion_words") or []))


def title_words(vocabulary: dict[str, Any] | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The strong title words this research flags with, and the ones its own question took away."""
    return survey.title_words(question_forms(vocabulary))


# ---- what the library already knows ----------------------------------------------------------


def answered(store: Store, source_version_id: str, provider: str) -> bool:
    """Whether a source has already answered about this record. A `failed` row is not an answer."""
    return store.conn.execute(
        "SELECT 1 FROM record_lookups WHERE source_version_id = ? AND provider = ? AND status IN ('found', 'not_found')",
        (source_version_id, provider),
    ).fetchone() is not None


def in_scope(scope: dict[str, Any], provider: str) -> bool:
    """A source is asked only when the research chose it and it is configured — `_count_probe`'s rule."""
    return provider in scope["providers"] and CONNECTORS[provider].access_mode() != "not_configured"


def _records(store: Store, research_id: str, scope_revision: int) -> list[dict[str, Any]]:
    """Every candidate record of this revision, work heads first, otherwise in `store.candidates` order.

    Work heads come first because a head's own abstract is what screening reads; the other versions follow, because
    a record is asked about for itself and a version's own abstract is what its own decision rests on.
    """
    heads = set(store.work_heads(research_id).values())
    fields = {row[0]: row for row in store.conn.execute(
        "SELECT v.id, v.doi, v.title, v.version_label, v.reference_count, v.work_id,"
        " EXISTS (SELECT 1 FROM passages p WHERE p.source_version_id = v.id AND p.kind = 'abstract') AS has_abstract"
        " FROM candidates c JOIN source_versions v ON v.id = c.source_version_id"
        " WHERE c.research_id = ? AND c.scope_revision = ?", (research_id, scope_revision))}
    rows = [{"source_version_id": row["id"], "doi": row["doi"], "title": row["title"], "work_id": row["work_id"],
             "kind": record_kind(dict(row)), "has_abstract": bool(row["has_abstract"]),
             "reference_count": row["reference_count"], "head": row["id"] in heads}
            for candidate in store.candidates(research_id, scope_revision)
            if (row := fields.get(candidate["source_version_id"])) is not None]
    return sorted(rows, key=lambda row: not row["head"])  # a stable sort keeps the candidate order inside each group


def _has_abstract(store: Store, source_version_id: str) -> bool:
    return store.conn.execute("SELECT 1 FROM passages WHERE source_version_id = ? AND kind = 'abstract'",
                              (source_version_id,)).fetchone() is not None


# ---- planning ---------------------------------------------------------------------------------


def _wanted(row: dict[str, Any], words: tuple[str, ...]) -> str | None:
    """Why this record would be asked about: for its missing abstract, for its links, or not at all.

    A record whose title already carries a strong word will leave the screening list anyway, so its abstract is not
    worth a request; a preprint is asked about for the version it may be linked to, abstract or not.
    """
    if not row["doi"]:
        return None
    if not row["has_abstract"] and not survey.signals(row["title"], None, None, words):
        return "abstract"
    return "link" if row["kind"] == "preprint" else None


def plan_semantic_scholar(store: Store, research_id: str, scope_revision: int, scope: dict[str, Any],
                          words: tuple[str, ...], limit: int = MAX_LOOKUP_REQUESTS) -> dict[str, Any]:
    """Who Semantic Scholar is asked about, split into batches; `outside_limit` counts the records left over."""
    if not in_scope(scope, "semantic_scholar"):
        return {"batches": [], "outside_limit": 0, "skipped": "out_of_scope"}
    wanted = [{"source_version_id": row["source_version_id"], "doi": row["doi"], "reason": reason}
              for row in _records(store, research_id, scope_revision)
              if (reason := _wanted(row, words)) and not answered(store, row["source_version_id"], "semantic_scholar")]
    size = lookup.S2_LOOKUP_BATCH
    batches = [wanted[start:start + size] for start in range(0, len(wanted), size)]
    return {"batches": batches[:limit], "outside_limit": len(wanted) - sum(len(b) for b in batches[:limit]),
            "skipped": None}


def plan_crossref(store: Store, research_id: str, scope_revision: int, scope: dict[str, Any], words: tuple[str, ...],
                  spent: int, limit: int = MAX_LOOKUP_REQUESTS) -> dict[str, Any]:
    """Who Crossref is asked about, one request each, split into chunks that share a step.

    Only records asked about for a missing abstract come here, and only those still missing one: a record Semantic
    Scholar answered with an abstract is done, and one it failed on is asked again here, because one source's
    failure is not the other's.
    """
    if not in_scope(scope, "crossref"):
        return {"chunks": [], "outside_limit": 0, "skipped": "out_of_scope"}
    wanted = [{"source_version_id": row["source_version_id"], "doi": row["doi"]}
              for row in _records(store, research_id, scope_revision)
              if _wanted(row, words) == "abstract" and not row["has_abstract"]
              and not answered(store, row["source_version_id"], "crossref")]
    allowed = max(0, limit - spent)
    asked, outside = wanted[:allowed], wanted[allowed:]
    return {"chunks": [asked[start:start + CROSSREF_CHUNK] for start in range(0, len(asked), CROSSREF_CHUNK)],
            "outside_limit": len(outside), "skipped": None}


# ---- storing one answer -------------------------------------------------------------------------


def store_answer(store: Store, source_version_id: str, provider: str, answer: lookup.LookupAnswer,
                 step_id: str | None, payload_ref: str | None) -> dict[str, int]:
    """Write one source's answer about one record in a single short transaction; returns what it added.

    A `failed` row is written too, so a resumed run can tell "asked and failed" from "not asked yet"; only a failed
    row is ever written over. The abstract is stored just as a search's abstract is — while the record has none.
    """
    added = {"found": 0, "abstracts_filled": 0, "links": 0, "failed": 0}
    with transaction(store.conn):
        current = store.conn.execute(
            "SELECT status FROM record_lookups WHERE source_version_id = ? AND provider = ?",
            (source_version_id, provider)).fetchone()
        if current is not None and current["status"] != "failed":
            return added  # this source already answered about this record; it is not asked or written again
        if answer.status == "found":
            added["found"] = 1
            if answer.abstract and not _has_abstract(store, source_version_id):
                store._insert_passage(source_version_id, None, "abstract", None, None, ABSTRACT_ORIGINS[provider],
                                      payload_ref, None, answer.abstract)
                added["abstracts_filled"] = 1
            store.set_reference_count(source_version_id, answer.reference_count)
            added["links"] = _store_links(store, source_version_id, provider, answer)
        elif answer.status == "failed":
            added["failed"] = 1
        store.conn.execute(
            "INSERT OR REPLACE INTO record_lookups (source_version_id, provider, status, had_abstract, step_id,"
            " asked_at) VALUES (?, ?, ?, ?, ?, ?)",
            (source_version_id, provider, answer.status, int(bool(answer.abstract)), step_id, now()),
        )
    return added


def _store_links(store: Store, source_version_id: str, provider: str, answer: lookup.LookupAnswer) -> int:
    """Store the DOIs this source names as another version of the record, under their own scheme.

    `linked_doi` is a scheme of its own so that the `published_doi` path a `legacy` research reads (D48) cannot see
    it: an external link is an `sw` signal and changes nothing in a legacy research.
    """
    ts, written = now(), 0
    for value in answer.linked_dois:
        written += _mapping(store, source_version_id, value, provider, ts)
    for value in answer.has_preprint:
        # The relation points the other way: the preprint names nothing, so the link is written onto the preprint's
        # own record, with the DOI of the record that named it.
        other = store.find_source_by_identifier("doi", value)
        if other is not None:
            written += _mapping(store, other, store.source(source_version_id)["doi"], provider, ts)
    return written


def _mapping(store: Store, source_version_id: str, value: str | None, provider: str, ts: str) -> int:
    if not value:
        return 0
    return store.conn.execute(
        "INSERT OR IGNORE INTO identifier_mappings (source_version_id, scheme, value, provider, retrieved_at)"
        " VALUES (?, 'linked_doi', ?, ?, ?)", (source_version_id, value, provider, ts)).rowcount


def linked_dois(store: Store, source_version_id: str) -> list[str]:
    """Every DOI this record names as another version of itself: the author's arXiv field and the external links."""
    return [row[0] for row in store.conn.execute(
        "SELECT DISTINCT value FROM identifier_mappings WHERE source_version_id = ?"
        " AND scheme IN ('published_doi', 'linked_doi') ORDER BY value", (source_version_id,))]


# ---- asking -------------------------------------------------------------------------------------


async def ask_second_sources(store: Store, http: httpx.AsyncClient, settings: Settings, run: dict[str, Any],
                             scope: dict[str, Any], words: tuple[str, ...],
                             checkpoint: Callable[[], None], limit: int = MAX_LOOKUP_REQUESTS) -> None:
    """Plan and send this run's DOI lookups. A failed request is recorded and the run goes on (D18).

    No request is sent twice: a step that already succeeded is skipped whole, and inside a chunk a record the
    library already has an answer for is passed over, so a run resumed mid-chunk carries on where it stopped.
    """
    run_id, rid, revision = run["id"], run["research_id"], run["scope_revision"]
    plan = _code_step(store, run_id, "lookup_plan:semantic_scholar", "code:lookup_plan",
                      lambda: plan_semantic_scholar(store, rid, revision, scope, words, limit))
    for number, batch in enumerate(plan["batches"]):
        checkpoint()
        await _semantic_scholar_step(store, http, settings, run, number, batch)
    plan_cr = _code_step(store, run_id, "lookup_plan:crossref", "code:lookup_plan",
                         lambda: plan_crossref(store, rid, revision, scope, words, len(plan["batches"]), limit))
    for number, chunk in enumerate(plan_cr["chunks"]):
        checkpoint()
        await _crossref_step(store, http, settings, run, number, chunk)
    checkpoint()


def _code_step(store: Store, run_id: str, key: str, kind: str, build: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Run a code step once and keep its output; a resumed run reads the stored plan instead of building it again."""
    step = store.step(run_id, key, kind)
    if step["status"] == "succeeded":
        return step["output"]
    store.start_step(step["id"])
    output = build()
    store.finish_step(step["id"], "succeeded", output=output)
    return output


async def _semantic_scholar_step(store: Store, http: httpx.AsyncClient, settings: Settings, run: dict[str, Any],
                                 number: int, batch: list[dict[str, Any]]) -> None:
    """One batch request. The whole batch shares one request, so one failure leaves every record in it `failed`."""
    step = store.step(run["id"], f"record_lookup:semantic_scholar:{number}", "provider_lookup:semantic_scholar")
    if step["status"] == "succeeded":
        return
    store.start_step(step["id"])
    asking = [row for row in batch if not answered(store, row["source_version_id"], "semantic_scholar")]
    if not asking:
        store.finish_step(step["id"], "succeeded", output=_counts([], asked=0))
        return
    connector = CONNECTORS["semantic_scholar"]
    store.add_usage(run["id"], "lookup_requests")
    answers, outcome = await lookup.semantic_scholar_batch(http, [row["doi"] for row in asking], connector.api_key())
    if outcome.retries:
        store.add_usage(run["id"], "lookup_requests", outcome.retries)
    payload_ref = _write_payload(settings, step["id"], outcome.raw_payload)
    added = [store_answer(store, row["source_version_id"], "semantic_scholar", answers[row["doi"]], step["id"],
                          payload_ref) for row in asking]
    # The step succeeded whatever the source answered: a failure is an answer stored on the record, not a broken run.
    store.finish_step(step["id"], "succeeded", output=_counts(added, asked=len(asking), status=outcome.status))


async def _crossref_step(store: Store, http: httpx.AsyncClient, settings: Settings, run: dict[str, Any],
                         number: int, chunk: list[dict[str, Any]]) -> None:
    """One chunk of single-record requests; each answer is written before the next request is sent."""
    step = store.step(run["id"], f"record_lookup:crossref:{number}", "provider_lookup:crossref")
    if step["status"] == "succeeded":
        return
    store.start_step(step["id"])
    added, asked, payloads = [], 0, {}
    for row in chunk:
        if answered(store, row["source_version_id"], "crossref"):
            continue
        asked += 1
        store.add_usage(run["id"], "lookup_requests")
        answer, outcome = await lookup.crossref_work(http, row["doi"], settings.contact_email)
        if outcome.retries:
            store.add_usage(run["id"], "lookup_requests", outcome.retries)
        payload_ref = None
        if outcome.raw_payload is not None:
            # The chunk's answers share one file, rewritten before the passage that points into it, so a stored
            # abstract never names a file a crash left unwritten.
            payloads[row["doi"]] = outcome.raw_payload
            payload_ref = _write_payload(settings, step["id"], payloads)
        added.append(store_answer(store, row["source_version_id"], "crossref", answer, step["id"], payload_ref))
    store.finish_step(step["id"], "succeeded", output=_counts(added, asked=asked))


def _counts(added: list[dict[str, int]], asked: int, status: str | None = None) -> dict[str, Any]:
    output = {"asked": asked, **{key: sum(row[key] for row in added)
                                 for key in ("found", "abstracts_filled", "links", "failed")}}
    return output | ({"status": status} if status else {})


def _payload_name(step_id: str) -> str:
    return f"{step_id}.json"


def _write_payload(settings: Settings, step_id: str, payload: Any) -> str | None:
    """Keep what the source answered, beside the search payloads, so a stored abstract points at its own evidence."""
    if payload is None:
        return None
    settings.payloads_dir.mkdir(parents=True, exist_ok=True)
    (settings.payloads_dir / _payload_name(step_id)).write_text(dumps(payload), encoding="utf-8")
    return _payload_name(step_id)


# ---- the links a second source named ------------------------------------------------------------


def external_links(store: Store, run: dict[str, Any]) -> dict[str, Any]:
    """Read this run's new links and abstracts into `record_links`, in one transaction (SW6.4).

    Two readings, in order: the pairs of a record whose abstract arrived from a second source, because an abstract
    can change what the text rule says about a pair, and then the pairs an external source named itself. A pair that
    is already merged and is now contradicted is counted and left merged: only the user undoes a merge (D72).
    """
    from deixis.workflow import links  # links imports store, which imports this module's callers

    run_id, rid = run["id"], run["research_id"]
    step = store.step(run_id, "external_links", "code:external_links")
    if step["status"] == "succeeded":
        return step["output"]
    store.start_step(step["id"])
    # Only the abstracts a lookup gave: a search stores its payload under its step too, and the abstracts it brought
    # were linked when they were found. Without the origin this would read every record of the run a second time.
    origins = tuple(ABSTRACT_ORIGINS.values())
    filled = [row[0] for row in store.conn.execute(
        "SELECT DISTINCT p.source_version_id FROM passages p JOIN run_steps s ON p.payload_ref = s.id || '.json'"
        f" WHERE s.run_id = ? AND p.kind = 'abstract' AND p.abstract_origin IN ({', '.join('?' * len(origins))})"
        " ORDER BY p.source_version_id", (run_id, *origins))]
    with transaction(store.conn):
        if filled:
            links.link_records(store, rid, filled)
        counts = links.link_external(store, rid)
        contradicted = links.contradicted_merges(store, rid)
    output = {**counts, "abstracts_reread": len(filled), "contradicted_merges": contradicted}
    store.finish_step(step["id"], "succeeded", output=output)
    return output


# ---- flags and decisions ---------------------------------------------------------------------------


def flag_and_decide(store: Store, run: dict[str, Any], scope: dict[str, Any], words: tuple[str, ...]) -> dict[str, Any]:
    """Label every candidate record and write the abstract-stage decision it asks for (SW5.4, SW9.3).

    A flag is stored for each of the three signals, because the seed pool of a later slice reads them; only the
    title signal asks for a decision. Nothing here writes a selection: every outcome is `unresolved`, which is what
    a `pending` selection already says, so `derive_selection` is not called.
    """
    run_id, rid, revision = run["id"], run["research_id"], run["scope_revision"]
    step = store.step(run_id, "record_flags", "code:record_flags")
    if step["status"] == "succeeded":
        return step["output"]
    store.start_step(step["id"])
    decisions = DecisionStore(store)
    protocol = store.current_protocol(rid, revision)
    rows = _records(store, rid, revision)
    flags: dict[str, int] = {}
    written: dict[str, int] = {}
    unknown = 0
    for row in rows:
        abstract = _abstract(store, row["source_version_id"])
        found = survey.signals(row["title"], abstract, row["reference_count"], words)
        unknown += row["reference_count"] is None
        with transaction(store.conn):
            for signal in found:
                flags[signal.flag] = flags.get(signal.flag, 0) + store.conn.execute(
                    "INSERT OR IGNORE INTO record_flags (research_id, scope_revision, source_version_id, flag,"
                    " evidence, step_id, protocol_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (rid, revision, row["source_version_id"], signal.flag, signal.evidence, step["id"],
                     protocol["hash"] if protocol else None, now()),
                ).rowcount
        code, note = _wanted_decision(store, decisions, rid, row, found, abstract, scope)
        if code and _should_write(decisions, rid, row["source_version_id"], code):
            decisions.record(rid, row["source_version_id"], code, step_id=step["id"], note=note)
            written[code] = written.get(code, 0) + 1
    held = held_from_screening(store, rid, revision)
    output = {"flags": dict(sorted(flags.items())), "decisions": dict(sorted(written.items())),
              "reference_count_unknown": unknown, "held_from_screening": len(held)}
    store.finish_step(step["id"], "succeeded", output=output)
    return output


def _abstract(store: Store, source_version_id: str) -> str | None:
    row = store.conn.execute(
        "SELECT text FROM passages WHERE source_version_id = ? AND kind = 'abstract' ORDER BY id LIMIT 1",
        (source_version_id,)).fetchone()
    return row[0] if row else None


def _wanted_decision(store: Store, decisions: DecisionStore, research_id: str, row: dict[str, Any],
                     found: list[survey.SurveySignal], abstract: str | None,
                     scope: dict[str, Any]) -> tuple[str | None, str | None]:
    """The abstract-stage code this record asks for now, and the note that says what was asked.

    A self-describing abstract and a reference count write no decision at all: they are labels, and the record
    stays a candidate (SW9.3).
    """
    if any(signal.flag == "survey_title_word" for signal in found):
        return "survey_title_word", None
    if abstract is None:
        if not row["doi"]:
            return "abstract_not_found", "no_doi"
        asked = [source for source in SOURCES if in_scope(scope, source)]
        if all(answered(store, row["source_version_id"], source) for source in asked):
            # Either every source in scope answered without an abstract, or no source is in scope to ask.
            return "abstract_not_found", ", ".join(asked) or "no_source_in_scope"
        # Left outside this run's request limit, or every answer failed: a later discovery run asks again.
        return "no_abstract", None
    current = decisions.current(research_id, row["source_version_id"], "abstract")
    if current is not None and current["reason_code"] in ("no_abstract", "abstract_not_found", "survey_title_word"):
        # The row no longer holds: the abstract arrived after it was written, or the question was revised and the
        # title word is now its subject. Left standing, a survey row would keep the record away from screening.
        return "abstract_not_proposed", None
    return None, None


def _should_write(decisions: DecisionStore, research_id: str, source_version_id: str, code: str) -> bool:
    """Whether this decision says something the record's current one does not.

    A second discovery run must not close a row and write the same code again merely because its step identifier and
    its protocol digest are new. A code another step owns is left alone.
    """
    current = decisions.current(research_id, source_version_id, "abstract")
    if current is None:
        return True
    if current["reason_code"] not in OWNED_CODES:
        return False
    return current["reason_code"] != code


def held_from_screening(store: Store, research_id: str, scope_revision: int) -> set[str]:
    """The work heads an `sw` run keeps away from the screening model (SW5.5, SW9.3, SW9.4).

    Two kinds leave the list: a head without an abstract of its own, because the model's `exclude` proposal reaches
    the selection directly and would make a record nobody could judge look out of scope; and a work every version of
    which is a title-word survey, because a flag on one version never drops the work. A held record stays `pending`,
    is not hidden and is not deleted: the user may include it.
    """
    # Read once: asking for every head's versions and their decisions took a second on 2,000 candidates, on the
    # thread the API answers from, and almost no head is a survey.
    surveys = {row[0] for row in store.conn.execute(
        "SELECT source_version_id FROM stage_decisions WHERE research_id = ? AND stage = 'abstract'"
        " AND superseded_at IS NULL AND reason_code = 'survey_title_word'", (research_id,))}
    held = set()
    for row in _records(store, research_id, scope_revision):
        svid = row["source_version_id"]
        if not row["head"]:
            continue
        if not row["has_abstract"]:
            held.add(svid)
            continue
        if svid not in surveys:
            continue
        versions = [r[0] for r in store.conn.execute(
            "SELECT m.source_version_id FROM corpus_memberships m JOIN source_versions v ON v.id = m.source_version_id"
            " WHERE m.research_id = ? AND m.removed_at IS NULL AND v.work_id = ?",
            (research_id, row["work_id"]))]
        if versions and all(version in surveys for version in versions):
            held.add(svid)
    return held
