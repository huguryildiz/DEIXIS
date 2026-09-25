"""Read models returned by the API. Every value comes from stored records."""

from __future__ import annotations

import json
import re
from typing import Any

from deixis.documents import embeddings, local_embedding, pdf
from deixis.domain.rules import SUGGESTION_CALLS, effective_reviewer, result_applicability
from deixis.workflow import english_question as english_question_rules
from deixis.workflow import approval as approval_rules
from deixis.workflow import flow_counts as flow_rules
from deixis.workflow import overrides as override_rules
from deixis.workflow import probes as probe_rules
from deixis.workflow.chaining import QUERY_PREFIX as CHAIN_PREFIX, policy as chain_policy
from deixis.workflow import suggestions as suggestions_rules
from deixis.workflow import vocabulary as vocabulary_rules
from deixis.workflow.equations import equation_state, equations_to_check
from deixis.workflow.queue import _snapshot as snapshot, context as queue_context, queue_answers, queue_counts
from deixis.workflow.report.store import ReportStore
from deixis.workflow import waiting as waiting_rules
from deixis.providers.registry import search_providers
from deixis.workflow.store import EVIDENCE_STATUS_SQL, NotFound, Store


# What the transcript reports from a search plan; the rest of the stored output stays out of the view.
PLAN_FIELDS = ("question_interpretation", "search_rationale", "scope_boundaries", "concepts")
# What the approval card shows of a vocabulary. The probes stay out: they are large, and the screen shows a term's
# own counts, which are already in the term row.
APPROVAL_VOCABULARY_FIELDS = ("claim_words", "exclusion_words", "outcome_terms", "gate_count", "too_broad")
# What the card reads of one proposed name (slice 08c). `phrase_count` null was not counted, which is not zero.
SUGGESTION_FIELDS = ("phrase", "synonym_of", "block", "phrase_count", "dropped")


def _approval_side(vocabulary: dict[str, Any] | None, criterion: dict[str, Any] | None,
                   queries: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """One side of the approval — what was proposed, or what was approved — as the screen reads it (slice 08a)."""
    if vocabulary is None:
        return None
    origins = approval_rules.block_origins(vocabulary)
    side = {
        "terms": [{field: term[field] for field in vocabulary_rules.TERM_FIELDS}
                  | {"block_origin": origins.get(term["phrase"], "rule")} for term in vocabulary["terms"]],
        **{field: vocabulary[field] for field in APPROVAL_VOCABULARY_FIELDS},
        "criterion": criterion,
        # Whether a criterion was built at all: without one the screen offers to write it or to go on without it.
        "criterion_available": criterion is not None,
        "sought_term_in_criterion": (criterion or {}).get("sought_term_in_criterion"),
    }
    if queries is not None:
        # The compiled text of every query this run will send, by provider and, beside a model-written query, by
        # which vocabulary wrote it (D92).
        side["queries"] = [{"provider_id": q["provider_id"], "query_text": q["query_text"],
                            **({"origin": q["origin"]} if q.get("origin") else {})} for q in queries]
    if (record := vocabulary.get("search_query")) is not None:
        side["search_query"] = _search_query_side(vocabulary, record)
    return side


def _search_query_side(vocabulary: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    """What the card shows of a model-written query (D92): each term's kind, reason and two counts, the backups that
    replaced a term, the warnings, and the code's query offered beside it. A failed model whose user chose the code's
    query alone says only that."""
    if record["status"] != "ready":
        return {"status": record["status"], "choice": record.get("choice"),
                "attempts": [{"attempt": a["attempt"], "reason": a["reason"]} for a in record.get("attempts") or []]}
    counts = {c["phrase"]: c for c in record["checks"]}  # a phrase counted again after a correction: the last count
    code = vocabulary["code_query"]
    return {
        "status": "ready",
        "terms": [{"phrase": phrase, **meta, "with_other_block": (counts.get(phrase) or {}).get("with_other_block")}
                  for phrase, meta in record["meta"].items()],
        "warnings": record["warnings"],
        "backups_left": record["backups_left"],
        "code_query": {
            "searched": code["searched"],
            # A code query that could not be searched on its own is shown, but the switch cannot turn it on.
            "available": bool(code["queries"]) and not code["vocabulary"]["too_broad"],
            "terms": [{"phrase": t["phrase"], "block": t["block"],
                       "form": t["root"] if t["in_query"] == "root" else t["phrase"]}
                      for t in code["vocabulary"]["terms"] if not t["dropped"]],
            "queries": [{"provider_id": q["provider_id"], "query_text": q["query_text"]} for q in code["queries"]],
        },
    }


def _suggestions_side(store: Store, run_id: str, step: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    """What the model was asked for on this card, and what came of it (slice 08c, SW2.5).

    The list stays on the card after the approval, so which proposals were added and which were not can still be
    read. `available` says whether the route would take a request, and `unavailable_reason` why not; a card that is
    waiting for the worker is `requested` and offers no button.
    """
    steps = store.suggestion_steps(run_id)
    requests = output.get("suggestion_requests") or 0
    carried = output.get("carried_suggestions") or {}
    ready = [row for row in steps if (row["output"] or {}).get("status") == "ready"]
    terms = ready[-1]["output"]["terms"] if ready else carried.get("terms") or []
    # A list with no row in it is an answer too: the model proposed nothing, and it is not asked again.
    answered = bool(ready) or bool(carried)
    closed = {row["operation_key"] for row in steps if row["status"] == "succeeded"}
    working = bool(requests) and f"term_suggestions:{requests}" not in closed
    failure = next((row["output"]["failure"] for row in reversed(steps)
                    if (row["output"] or {}).get("status") == "failed"), None)
    status = ("requested" if working else "ready" if answered else "failed" if failure else "none")
    reason = ("no_anchor_phrases" if not suggestions_rules.anchors(output["proposal"]["vocabulary"])
              else "already_suggested" if answered
              # A started call is charged to the run even when it fails; the run was given SUGGESTION_CALLS for this.
              else "suggestion_call_spent" if store.suggestion_calls(run_id) >= SUGGESTION_CALLS else None)
    return {
        "status": status,
        # The card shows the button only while it is editable, so the run's own status is not read here.
        "available": step["status"] != "succeeded" and reason is None and not working,
        "unavailable_reason": reason,
        "failure": failure if status == "failed" else None,
        "carried": not ready and bool(carried),
        "terms": [{field: row[field] for field in SUGGESTION_FIELDS} for row in terms],
    }


def approval_view(store: Store, run_id: str) -> dict[str, Any] | None:
    """What this run asked the user to approve and what came of it, or None when it asked nothing (SW2.6)."""
    step = store.approval_step(run_id)
    if step is None or not step["output"]:
        return None
    output = step["output"]
    approved = output.get("approved")
    record = output.get("approval") or {}
    return {
        "status": "approved" if step["status"] == "succeeded" else
                  "submitted" if output.get("submitted") is not None else "waiting",
        "approved_by": record.get("approved_by"),
        "edited": record.get("edited"),
        "proposal_hash": output["proposal_hash"],
        # Both sides stay on the screen after the approval: the user can see what was proposed and what changed.
        "proposal": _approval_side(output["proposal"]["vocabulary"], output["proposal"]["criterion"],
                                   # A model-written proposal shows its compiled queries before the approval (D92).
                                   output["proposal"]["queries"]
                                   if output["proposal"]["vocabulary"]["block_assignment"] == "search_query" else None),
        "approved": _approval_side(approved["vocabulary"], approved["criterion"], approved["queries"]) if approved else None,
        "skipped_edits": output.get("skipped_edits") or [],
        "suggestions": _suggestions_side(store, run_id, step, output),
        # Which sources the queries were compiled for and why (D93): the approved routing once a correction routed
        # again, else the proposal's. None for a card shown before routing existed.
        "routing": _card_routing(approved or output["proposal"], output["proposal"]),
        # How this run will chain citations after its abstract stage: the rule and its limits, frozen in the run's
        # budget when it was queued (D95). The real seeds are only known after the search, in the run view.
        "chaining": _card_chaining(store, run_id),
    }


def _card_chaining(store: Store, run_id: str) -> dict[str, Any] | None:
    run = store.run(run_id)
    return chain_policy(run["budget"], store.scope(run["research_id"], run["scope_revision"])["effort"])


def _card_routing(side: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any] | None:
    """The card's routing with `queried`: the chosen sources the first round's queries really go to. The effort's
    query limit can leave a chosen source no query, and the card must not call it searched (review of slice 14)."""
    routing = side.get("routing") or proposal.get("routing")
    if routing is None:
        return None
    queried = {q["provider_id"] for q in side.get("queries") or []}
    return routing | {"queried": [p for p in routing["providers"] if p in queried]}


def source_counts(store: Store, run_id: str, probe: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Per round, what each source brought in this run: how many works, and how many no other source brought (D93).

    Works are counted after the DOI and work merge, through the candidate each record became, and a source's work is
    its own when no other source's search found that work anywhere in this run. The numbers come from
    `candidate_hits`, which keeps every search that found a candidate; a run searched before that table existed has
    none, and it says its counts were not kept (`counted` false) instead of reading as zero. None for a run that
    searched nothing.

    With an `sw` research's probe set (slice 19), a counted run also gets `arms`: for each of these rows the records
    it returned and the included and confirmed works it found, in the same "only" universe, the first round's split
    of a source by query origin, and the arm-kind line. Without one the result is exactly D93's.
    """
    conn = store.conn
    searches = [dict(r) for r in conn.execute(
        "SELECT sr.id, sr.provider, sr.status, sr.result_count, st.operation_key FROM search_runs sr"
        " JOIN run_steps st ON st.id = sr.step_id WHERE sr.run_id = ? ORDER BY sr.rowid", (run_id,))]
    if not searches:
        return None
    works: dict[str, set[str]] = {}
    for row in conn.execute(
            "SELECT h.search_run_id, v.work_id FROM candidate_hits h JOIN search_runs sr ON sr.id = h.search_run_id"
            " JOIN source_versions v ON v.id = h.source_version_id WHERE sr.run_id = ?", (run_id,)):
        works.setdefault(row["search_run_id"], set()).add(row["work_id"])
    if any(s["result_count"] and s["status"] == "completed" and s["id"] not in works for s in searches):
        return {"counted": False, "rounds": []}
    # The first round is the queries the approval closed on; what the second round added is numbered after them.
    card = store.existing_step(run_id, "protocol_approval")
    first = len((((card or {}).get("output") or {}).get("approved") or {}).get("queries") or []) or None
    by_round: dict[int, dict[str, set[str]]] = {}
    everywhere: dict[str, set[str]] = {}
    # Citation chaining is not a round of a source's searches (D95): its works are counted apart, with the works no
    # keyword search of this run found.
    chained: set[str] = set()
    for search in searches:
        if search["operation_key"].startswith(CHAIN_PREFIX):
            chained |= works.get(search["id"], set())
            continue
        index = re.match(r"search:(\d+)", search["operation_key"])
        number = 2 if first is not None and index and int(index.group(1)) >= first else 1
        found = works.get(search["id"], set())
        by_round.setdefault(number, {}).setdefault(search["provider"], set()).update(found)
        everywhere.setdefault(search["provider"], set()).update(found)
    counts: dict[str, Any] = {"counted": True, "rounds": [
        {"round": number, "sources": [
            {"provider_id": provider, "works": len(found),
             "only": len(found - set().union(*(w for p, w in everywhere.items() if p != provider)))}
            for provider, found in providers.items()]}
        for number, providers in sorted(by_round.items())]}
    if any(search["operation_key"].startswith(CHAIN_PREFIX) for search in searches):
        counts["chain"] = {"works": len(chained), "only": len(chained - set().union(*everywhere.values()))}
    if probe is not None:
        # Beside D93's rows, not inside them: their fields and meaning stay exactly as D93 wrote them.
        counts["arms"] = probe_rules.arm_counts(store, run_id, searches, works, first, card, probe)
    return counts


def _json(value: str | None) -> Any:
    return json.loads(value) if value else None


def _model_outputs(store: Store, run_id: str, kind: str) -> list[dict[str, Any]]:
    return [json.loads(r["output_json"]) for r in store.conn.execute(
        "SELECT output_json FROM run_steps WHERE run_id = ? AND kind = ? AND status = 'succeeded' AND output_json IS NOT NULL"
        " ORDER BY rowid", (run_id, kind),
    )]


def ocr_state(store: Store, asset_id: str) -> dict[str, Any]:
    """Pages of the text in use without text (blank pages included), pages read with OCR, and the latest OCR reading (D51)."""
    conn = store.conn
    asset = store.asset(asset_id)
    pages = {r["physical_page"]: r["ocr"] for r in conn.execute(
        "SELECT physical_page, MAX(text_source = 'ocr') AS ocr FROM passages WHERE asset_id = ? AND kind = 'pdf_page'"
        " AND extraction_version IS ? GROUP BY physical_page", (asset_id, asset["extraction_version"]))}
    last = conn.execute(
        "SELECT outcome, rejection_reason, ocr_json, created_at FROM asset_extractions WHERE asset_id = ? AND ocr_json IS NOT NULL"
        " ORDER BY created_at DESC, rowid DESC LIMIT 1", (asset_id,)).fetchone()
    return {"pages_without_text": max(0, (asset["page_count"] or 0) - len(pages)), "ocr_pages": sum(1 for o in pages.values() if o),
            "last_read": {"outcome": last["outcome"], "rejection_reason": last["rejection_reason"], "created_at": last["created_at"]}
            | json.loads(last["ocr_json"]) if last else None}


def report_view(store: Store, research_id: str, report_id: str) -> dict[str, Any]:
    """Return one report only through the research that owns it, with stored claim anchors."""
    store.research(research_id)
    reports = ReportStore(store)
    report = reports.report(report_id)
    if report["research_id"] != research_id:
        raise NotFound(report_id)

    sections = []
    for section in reports.sections(report_id):
        claims = []
        for claim in store.conn.execute(
            "SELECT id, claim_key, text, support_type FROM report_claims"
            " WHERE report_section_id = ? ORDER BY ordinal", (section["id"],),
        ):
            evidence = [
                {"passage_id": link["passage_id"], "cell_id": link["cell_id"],
                 "anchor_text": link["anchor_text"]}
                for link in store.conn.execute(
                    "SELECT passage_id, cell_id, anchor_text FROM report_citation_links"
                    " WHERE claim_id = ? ORDER BY rowid", (claim["id"],),
                )
            ]
            claims.append({"claim_key": claim["claim_key"], "text": claim["text"],
                           "support_type": claim["support_type"], "evidence": evidence})
        sections.append({key: section[key] for key in (
            "section_id", "status", "word_count", "draft", "validation",
        )} | {"claims": claims})
    return report | {"sections": sections}


def research_view(store: Store, research_id: str) -> dict[str, Any]:
    """The research as the screen reads it, from one read snapshot (slice 19, decision 10): an `sw` research derives
    its decision facts once, and the queue counts, the probe set, the arm counts and the signal table share them."""
    with snapshot(store.conn):
        return _research_view(store, research_id)


def _research_view(store: Store, research_id: str) -> dict[str, Any]:
    conn = store.conn
    research = store.research(research_id)
    scope = store.scope(research_id)
    sw = scope.get("search_workflow") == "sw"
    # One queue context: the facts and every work's outcome, read once for all four (slice 19). Legacy has none.
    ctx = queue_context(store, research_id) if sw else None
    probe = probe_rules.probe_set(ctx) if ctx is not None else None
    seed = scope["seed_snapshot"]
    scope_view = {key: value for key, value in scope.items() if key != "seed_snapshot"}
    scope_view["seed"] = ({key: seed[key] for key in ("source_version_id", "asset_id", "asset_sha256",
                                                      "extraction_version", "title", "title_basis", "page_count", "text_pages")}
                          | {"passage_count": len(seed["passages"])} if seed else None)
    scope_view["seed_status"] = store.seed_status(research_id, scope)
    # The providers a query may go to; a verification connector in the scope is not one (D87), nor Scopus in an sw
    # research (D91).
    scope_view["search_providers"] = search_providers(scope["providers"], scope.get("search_workflow"))

    runs = []
    for row in conn.execute("SELECT id FROM runs WHERE research_id = ? ORDER BY created_at DESC LIMIT 10", (research_id,)):
        run = store.run(row["id"])
        run["steps"] = store.run_steps(run["id"])
        # The protocol this run froze; a run that froze none (an answer run) ran under the revision's latest one.
        own = next((s["output"] for s in run["steps"] if s["operation_key"] == "protocol" and s["output"]), None)
        frozen = own or store.current_protocol(research_id, run["scope_revision"])
        run["protocol_hash"] = (frozen.get("protocol_hash") or frozen.get("hash")) if frozen else None
        output = next((o for o in _model_outputs(store, run["id"], "model:search_plan") if o.get("output_type") == "SearchPlan"), None)
        # A v1 plan holds the queries the model wrote; a v2 plan's queries were compiled from its concepts and stored beside it (D44).
        run["plan"] = ({k: output["result"][k] for k in PLAN_FIELDS}
                       | {"queries": output["result"].get("queries", output.get("queries", []))}) if output else None
        # Screening runs in batches; each batch's note is its own line, timed by its step.
        # What this run asked the user to approve before it froze its protocol; None for a legacy run (slice 08a).
        run["approval"] = approval_view(store, run["id"])
        # What each source brought in each round of this run, and how much of it no other source did (D93).
        run["source_counts"] = source_counts(store, run["id"], probe) if run["kind"] == "discovery" else None
        if run["source_counts"] and run["source_counts"]["counted"] and probe is None:
            run["source_counts"]["arms"] = None  # a legacy research has no probe set
        # Where the person's confirmed works stood in this run's keyword ranking, descriptively (slice 19).
        run["signals"] = probe_rules.signal_table(store, run["id"], probe) if probe and run["kind"] == "discovery" else None
        run["screening_notes"] = [
            {"step_id": r["id"], "text": note} for r in store.conn.execute(
                "SELECT id, output_json FROM run_steps WHERE run_id = ? AND kind = 'model:screening' AND status = 'succeeded'"
                " AND output_json IS NOT NULL ORDER BY rowid", (run["id"],))
            if (note := (json.loads(r["output_json"]).get("result") or {}).get("notes", "").strip())
        ]
        runs.append(run)

    search_runs = [
        {**{k: r[k] for k in ("id", "run_id", "scope_revision", "provider", "query_text", "access_mode", "status", "result_count", "provider_total", "page_limit", "retrieved_at",
                              "page_number", "read_limit", "read_total", "stop_reason", "unread_count")},
         "error": _json(r["error_json"])}
        for r in conn.execute("SELECT * FROM search_runs WHERE research_id = ? ORDER BY retrieved_at", (research_id,))
    ]
    # What a paged query left unread is the count on its last stopped page; a page read again replaces the earlier
    # row rather than adding to it, and an unknown provider total is skipped instead of counted as zero (slice 04c).
    last_stopped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in search_runs:
        if row["stop_reason"] is None:
            continue
        key = (row["run_id"], row["provider"], row["query_text"])
        order = (row["page_number"] or 0, row["retrieved_at"], row["id"])
        seen = last_stopped.get(key)
        if seen is None or order >= (seen["page_number"] or 0, seen["retrieved_at"], seen["id"]):
            last_stopped[key] = row

    answers = []
    cited_sources: set[str] = set()
    # A quote of a source removed from this research still opens; the view names the removal (D50).
    removed = {r[0] for r in conn.execute(
        "SELECT source_version_id FROM corpus_memberships WHERE research_id = ? AND removed_at IS NOT NULL", (research_id,))}
    for a in conn.execute("SELECT * FROM answers WHERE research_id = ? ORDER BY created_at DESC, rowid DESC", (research_id,)):
        draft = _json(a["draft_json"])
        claims = []
        for c in conn.execute("SELECT * FROM claims WHERE answer_id = ? ORDER BY ordinal", (a["id"],)):
            evidence = [
                {"passage_id": e["passage_id"], "source_version_id": e["source_version_id"], "source_key": e["source_key"], "kind": e["kind"],
                 "physical_page": e["physical_page"], "printed_label": e["printed_label"],
                 "reading_depth": "abstract" if e["kind"] == "abstract" else "selected_sections", "title": e["title"],
                 "version_label": e["version_label"], "anchor_text": e["anchor_text"], "evidence_status": e["evidence_status"],
                 "text_source": e["text_source"], "removed_from_research": e["source_version_id"] in removed}
                for e in conn.execute(
                    "SELECT l.passage_id, l.source_version_id, l.anchor_text, p.kind, p.physical_page, p.printed_label, p.text_source, s.title, s.version_label,"
                    " (SELECT w.source_key FROM works w WHERE w.id = s.work_id) AS source_key,"
                    f" {EVIDENCE_STATUS_SQL} AS evidence_status FROM evidence_links l"
                    " JOIN passages p ON p.id = l.passage_id JOIN source_versions s ON s.id = l.source_version_id"
                    " LEFT JOIN source_assets a ON a.id = p.asset_id"
                    " WHERE l.claim_id = ? ORDER BY l.rowid", (c["id"],)
                )
            ]
            if not answers:
                cited_sources.update(e["source_version_id"] for e in evidence)
            claims.append({"id": c["id"], "label": c["label"], "section": c["section"], "text": c["text"], "support_type": c["support_type"],
                           "semantic_review": c["semantic_review"], "evidence": evidence})
        session = conn.execute(
            "SELECT connection, requested_model, resolved_model, token_usage_json FROM model_sessions WHERE step_input_id = ?",
            (a["step_input_id"],),
        ).fetchone() if a["step_input_id"] else None
        review = _review_view(store, a["id"])
        verdicts = {r["claim_label"]: {"verdict": r["verdict"], "reason": r["reason"]} for r in (review or {}).get("reviews", [])}
        for claim in claims:
            claim["review"] = verdicts.get(claim["label"])
        given = store.step_input_payload(a["step_input_id"]) if a["step_input_id"] else None
        validation = _json(a["validation_json"]) or {}
        answers.append({
            "id": a["id"], "run_id": a["run_id"], "status": a["status"], "scope_revision": a["scope_revision"],
            # A report keeps the number and title it was saved with; later answers and title changes do not rewrite them.
            "report_version": a["report_version"],
            "report_title": (draft or {}).get("title") if a["status"] == "structurally_valid" else None,
            "applicability": result_applicability(a["scope_revision"], research["current_scope_revision"],
                                                  a["selection_revision"], research["selection_revision"]),
            "answer_language": a["answer_language"], "created_at": a["created_at"], "claims": claims,
            "limitations": (draft or {}).get("limitations", []) if a["status"] == "structurally_valid" else [],
            "unanswered_aspects": (draft or {}).get("unanswered_aspects", []) if a["status"] == "structurally_valid" else [],
            "capability_notice": (draft or {}).get("capability_notice") if a["status"] == "structurally_valid" else None,
            "clarification": draft if a["status"] == "clarification" else None,
            "unverified_draft": draft if a["status"] == "unverified_draft" else None,
            "validation": validation,
            "model": {"connection": session["connection"], "requested_model": session["requested_model"],
                      "resolved_model": session["resolved_model"], "token_usage": _json(session["token_usage_json"])} if session else None,
            # A file or text extraction this answer read is no longer in use; its quotes still open what was read (D45).
            "source_text_changed": bool(given) and any(
                status != "current" for status in store.evidence_statuses([p["passage_id"] for p in given["passages"]]).values()),
            "inputs_given": {"sources": len(given["sources"]), "passages": len(given["passages"]),
                             "source_ids": [s["source_id"] for s in given["sources"]]} if given else None,
            # Where the flow stood when this answer's run started (slice 20); null for an answer whose run kept none,
            # never today's counts in its place. Beside `inputs_given`, not instead of it.
            "start_snapshot": _start_snapshot(store, a) if sw else None,
            "review": review,
        })
    duplicates = store.suspected_duplicates(research_id)
    # Similarity from the chosen semantic search model only; with semantic search off, no source has one (D30).
    provider, model = embeddings.chosen(store.setting("semantic_search"))
    similarity_model = embeddings.Embedder(provider, model).stored_model if provider != "off" and model else None
    answered_in_queue = queue_answers(store, research_id)
    sources = []
    for row in conn.execute(
        "SELECT m.added_by, m.created_at AS added_at, s.*, sel.state, sel.origin AS selection_origin, sel.version AS selection_version, sel.proposal,"
        " (SELECT w.source_key FROM works w WHERE w.id = s.work_id) AS source_key,"
        " sel.proposal_reason, sel.proposal_basis, sel.user_reason, c.id AS candidate_id, c.rank, c.scope_revision AS found_in_revision,"
        " (SELECT ss.similarity FROM source_similarities ss WHERE ss.research_id = m.research_id AND ss.source_version_id = m.source_version_id"
        "  AND ss.scope_revision = c.scope_revision AND ss.model = ?) AS similarity"
        " FROM corpus_memberships m JOIN source_versions s ON s.id = m.source_version_id"
        " JOIN selections sel ON sel.research_id = m.research_id AND sel.source_version_id = m.source_version_id"
        " LEFT JOIN candidates c ON c.research_id = m.research_id AND c.source_version_id = m.source_version_id"
        " WHERE m.research_id = ? AND m.removed_at IS NULL ORDER BY m.created_at, c.rank", (similarity_model, research_id)
    ):
        svid = row["id"]
        # The PDF in use, whether its text comes from the current extractor, and a later extraction that was not taken (D45).
        # A math extraction (D52) builds on the current extractor's text; its own "nothing to read" or failed attempts are
        # reported as the PDF's equation state, not as a rejected re-extraction.
        assets = [dict(r) | {"current_extraction": (r["extraction_version"] or "").split("+")[0] == pdf.EXTRACTION_VERSION,
                             "equations": equation_state(store, r["id"]), "ocr": ocr_state(store, r["id"]), "rejected_extraction": dict(rejected) if (rejected := conn.execute(
            "SELECT extraction_version, rejection_reason, created_at FROM asset_extractions WHERE asset_id = ? AND outcome = 'rejected'"
            " AND extraction_version NOT LIKE '%+marker-%' ORDER BY created_at DESC, rowid DESC LIMIT 1", (r["id"],)).fetchone()) else None} for r in conn.execute(
            "SELECT id, extraction_status, extraction_version, page_count, origin, byte_size, original_filename FROM source_assets"
            " WHERE source_version_id = ? AND removed_at IS NULL", (svid,)
        )]
        replaced_assets = [dict(r) for r in conn.execute(
            "SELECT id, original_filename, removed_at, replaced_by_asset_id FROM source_assets"
            " WHERE source_version_id = ? AND removal_reason = 'replaced' ORDER BY removed_at DESC", (svid,)
        )]
        abstract = conn.execute(
            "SELECT id, abstract_origin FROM passages WHERE source_version_id = ? AND kind = 'abstract' LIMIT 1", (svid,)
        ).fetchone()
        # The link's latest attempt in any research: a refused link is not requested again (see Store.pdf_link_refusal).
        fetch = conn.execute(
            "SELECT status, error_code, json_extract(error_json, '$.http_status') AS http_status FROM run_steps"
            " WHERE operation_key = ? ORDER BY started_at DESC LIMIT 1", (f"fetch:{svid}",)
        ).fetchone()
        other_copy = conn.execute(
            "SELECT s.status, s.error_code FROM run_steps s JOIN runs r ON r.id = s.run_id"
            " WHERE r.research_id = ? AND s.operation_key = ? ORDER BY s.started_at DESC LIMIT 1", (research_id, f"other_copy:{svid}")
        ).fetchone()
        pdf_candidates = [{k: r[k] for k in (
            "id", "provider", "candidate_url", "landing_url", "version_label", "license", "identity_status",
            "version_status", "access_status", "http_status", "error_code", "final_url", "discovered_at", "attempted_at"
        )} for r in conn.execute(
            # Web results under another paper's title, stored before those were dropped at lookup, are not shown.
            "SELECT * FROM pdf_candidates WHERE source_version_id = ? AND identity_status != 'unverified'"
            " ORDER BY discovered_at, rowid", (svid,)
        )]
        sources.append({
            "source_version_id": svid, "work_id": row["work_id"], "source_key": row["source_key"], "title": row["title"],
            "authors": json.loads(row["authors_json"]),
            "year": row["year"], "venue": row["venue"], "volume": row["volume"], "issue": row["issue"],
            "pages": row["pages"], "doi": row["doi"], "landing_url": row["landing_url"],
            "version_label": row["version_label"], "publication_type": row["publication_type"], "origin": row["origin"],
            "cited_by_count": row["cited_by_count"], "cited_by_count_at": row["cited_by_count_at"],
            "added_by": row["added_by"], "added_at": row["added_at"], "rank": row["rank"], "similarity": row["similarity"],
            # Whether an answer can read this version's PDF pages rather than its abstract (D49).
            "has_pdf_text": bool(assets) and store.has_pdf_text(svid),
            # Some of that text was read with OCR from scanned pages and is labelled so (D51).
            "has_ocr_text": bool(assets) and any(p["text_source"] == "ocr" for p in store.passages_for(svid)),
            # "other_version": another version of a found record (e.g. its submitted manuscript), stored separately.
            "version_role": "other_version" if row["added_by"] == "search" and row["candidate_id"] is None else "record",
            # A search result keeps the question revision it was found for; attached files belong to no revision.
            "found_in_revision": row["found_in_revision"],
            "applicability": "current" if row["found_in_revision"] is None
            else result_applicability(row["found_in_revision"], research["current_scope_revision"]),
            "access": {"abstract_passage_id": abstract["id"] if abstract else None,
                       "abstract_origin": abstract["abstract_origin"] if abstract else None,
                       "oa_pdf_url": row["oa_pdf_url"], "oa_pdf_version": row["oa_pdf_version"], "assets": assets, "replaced_assets": replaced_assets,
                       "fetch": dict(fetch) if fetch else None, "other_copy": dict(other_copy) if other_copy else None,
                       "pdf_candidates": pdf_candidates,
                       "pdf_discoveries": store.pdf_discoveries(research_id, svid)},
            "selection": {"state": row["state"], "origin": row["selection_origin"], "version": row["selection_version"],
                          "proposal": row["proposal"], "proposal_reason": row["proposal_reason"],
                          "proposal_basis": row["proposal_basis"], "user_reason": row["user_reason"],
                          # A selection the human queue wrote (slice 17): the answer, read from its stored link.
                          "queue_answer": answered_in_queue.get((svid, row["selection_version"]))
                          if row["selection_origin"] == "user" else None},
            "cited_in_latest_answer": svid in cited_sources,
            # Providers whose records map to this source version (one DOI from several providers is one source).
            "provider_records": [r[0] for r in conn.execute(
                "SELECT DISTINCT provider FROM identifier_mappings WHERE source_version_id = ? AND scheme = provider ORDER BY provider", (svid,)
            )],
            # Possibly the same publication as another source (same title, or a preprint naming its DOI); never merged.
            "suspected_duplicates": duplicates.get(svid, []),
        })

    # A work has one record, its head: a published record, else the first (D46, D48). Another candidate of the same work
    # (a preprint screened before its published record joined the work) is shown as another version of the head.
    heads = store.work_heads(research_id)
    reads_version = store.answer_versions(research_id)
    for s in sources:
        if s["version_role"] == "record" and heads.get(s["work_id"]) != s["source_version_id"]:
            s["version_role"] = "other_version"
        # The version whose text an answer reads when it is not the head itself (D48), and whether the answer reads
        # no version of the work at all: its only PDF text is a person's file not read yet (slice 18b, decision 8).
        s["answer_reads_version_id"] = None
        s["answer_reads_nothing"] = False
        if s["version_role"] == "record":
            reads = reads_version.get(s["source_version_id"], s["source_version_id"])
            if reads is None:
                s["answer_reads_nothing"] = True
            elif reads != s["source_version_id"]:
                s["answer_reads_version_id"] = reads

    # Other versions follow the record of their work and share its question revision.
    others: dict[str, list[dict[str, Any]]] = {}
    for s in sources:
        if s["version_role"] == "other_version":
            others.setdefault(s["work_id"], []).append(s)
    ordered: list[dict[str, Any]] = []
    for record in (s for s in sources if s["version_role"] == "record"):
        ordered.append(record)
        # Grouped once rather than scanned per record: the nested scan was 2.2 s of the view's 7.2 s on the
        # smoke run's 7,769-source research (slice 13d).
        ordered += [s | {"found_in_revision": record["found_in_revision"], "applicability": record["applicability"]}
                    for s in others.get(record["work_id"], ())]
    placed = {s["source_version_id"] for s in ordered}
    sources = ordered + [s for s in sources if s["source_version_id"] not in placed]

    # Versions of one work are not independent: unique, included, given and cited count works.
    work_of = {s["source_version_id"]: s["work_id"] for s in sources}

    def works(ids: Any) -> int:
        return len({work_of.get(i, i) for i in ids})

    latest_given = next((a["inputs_given"] for a in answers if a["inputs_given"]), None)
    counts = {
        "found": sum(s["result_count"] for s in search_runs),
        "unread": sum(s["unread_count"] or 0 for s in last_stopped.values()),
        "unique": works(work_of),
        # A work's selection is its head's; other versions follow it (D48).
        "included": sum(s["selection"]["state"] == "included" for s in sources if s["version_role"] == "record"),
        "excluded": sum(s["selection"]["state"] == "excluded" for s in sources if s["version_role"] == "record"),
        "pending": sum(s["selection"]["state"] == "pending" for s in sources if s["version_role"] == "record"),
        "inspected": works(latest_given["source_ids"]) if latest_given else 0,
        "cited": works(cited_sources),
        # Works the user removed from this research, and those a later search found again; neither is listed (D50).
        **dict(zip(("removed", "removed_found_again"), conn.execute(
            "SELECT COUNT(DISTINCT v.work_id), COUNT(DISTINCT CASE WHEN m.found_again_at IS NOT NULL THEN v.work_id END)"
            " FROM corpus_memberships m JOIN source_versions v ON v.id = m.source_version_id"
            " WHERE m.research_id = ? AND m.removed_at IS NOT NULL", (research_id,)).fetchone())),
    }
    if sw:
        # The human queue's open rows and the decisions to look at again (slice 16); a legacy view is unchanged.
        counts |= queue_counts(store, research_id, ctx)
        # The works waiting for the person's PDF (slice 18a).
        counts["waiting_for_pdf"] = len(waiting_rules.for_context(ctx)[1])
    # Every work of the revision in one bucket, PRISMA 2020-style boxes and the override count (slice 20), from the
    # same context and probe set as the queue counts; null for a legacy research.
    flow = flow_rules.flow_counts(ctx, probe) if ctx is not None and probe is not None else None
    counts["flow"] = flow
    counts["flow_boxes"] = flow_rules.flow_boxes(ctx, flow) if flow is not None else None
    counts["overrides"] = override_rules.overrides_view(ctx, probe) if ctx is not None and probe is not None else None
    last_event = conn.execute("SELECT MAX(id) FROM events WHERE research_id = ?", (research_id,)).fetchone()[0] or 0
    reviewer = effective_reviewer(scope, store.setting("reviewer"))
    report_runs = [dict(row) for row in conn.execute(
        "SELECT id, status, report_version, created_at FROM reports"
        " WHERE research_id = ? ORDER BY created_at DESC, rowid DESC", (research_id,),
    )]
    return {"research": research, "scope": scope_view, "runs": runs, "search_runs": search_runs, "sources": sources,
            "answers": answers, "reportRuns": report_runs, "counts": counts, "last_event_id": last_event,
            # The semantic search arm for this research's current revision (slice 21); no count of what will be sent.
            "semantic": semantic_view(store, research_id, scope),
            # The probe set's columns and the probes no arm found (slice 19); null for a legacy research.
            "probes": probe_rules.probes_view(store, research_id, probe) if probe is not None else None,
            # The reviewer the next answer would get: the research's own setting, else the app-wide default.
            "reviewer": {"mode": scope["review_mode"], "connection": reviewer[0] if reviewer else None, "model": reviewer[1] if reviewer else None,
                         "reasoning_effort": reviewer[2] if reviewer else None}}


def semantic_view(store: Store, research_id: str, scope: dict[str, Any]) -> dict[str, Any]:
    """The provider semantic search uses, and whether its arm runs for this revision (D103, decision 10).

    `arm`: "off" (no provider), "english_question_missing" (the built-in model, a question not in English and no
    sentence saved), "not_installed" (the built-in model is chosen but not ready now), else "on". The provider is
    what Settings say now; a run freezes its own in its step."""
    provider, model = embeddings.chosen(store.setting("semantic_search"))
    stored_model = embeddings.Embedder(provider, model).stored_model if provider != "off" and model else None
    row = store.english_question(research_id, scope["revision"])
    needs = provider == "builtin" and not english_question_rules.is_english(scope["question"], scope.get("language_hint"))
    if stored_model is None:
        arm = "off"
    elif needs and row is None:
        arm = "english_question_missing"
    elif provider == "builtin" and not local_embedding.builtin_available():
        arm = "not_installed"
    else:
        arm = "on"
    return {"provider": provider, "stored_model": stored_model, "arm": arm,
            "english_question": {"text": row["text"], "origin": row["origin"]} if row else None,
            "needs_english_question": needs}


def _start_snapshot(store: Store, answer: Any) -> dict[str, Any] | None:
    """The `code:answer_start_snapshot` step of this answer's run, and whether the included sources' state moved
    while the answer ran (its own selection revision is not the one the snapshot read)."""
    step = store.existing_step(answer["run_id"], "answer_start_snapshot")
    if step is None or step["status"] != "succeeded" or not step["output"]:
        return None
    output = step["output"]
    return output | {"included_state_changed": answer["selection_revision"] is not None
                     and output["selection_revision"] != answer["selection_revision"]}


# Reading depth of one stored source version. A PDF text layer, an abstract and bare metadata are
# different evidence levels (AGENTS.md), so the library names the level instead of a generic badge.
_HAS_PDF_TEXT = ("EXISTS (SELECT 1 FROM passages p JOIN source_assets a ON a.id = p.asset_id"
                 " WHERE p.source_version_id = v.id AND a.removed_at IS NULL)")
_HAS_ABSTRACT = "EXISTS (SELECT 1 FROM passages p WHERE p.source_version_id = v.id AND p.kind = 'abstract')"
_ACCESS_ORDER = ["metadata", "abstract", "pdf_available"]


def _access_level(has_pdf_text: int, has_abstract: int) -> str:
    return "pdf_available" if has_pdf_text else "abstract" if has_abstract else "metadata"


# Rank one version of a work as the representative shown in the library table: richer bibliographic
# records first, so a bare preprint never hides the published version's metadata.
def _library_representative_score(row: dict[str, Any]) -> tuple[int, ...]:
    return (
        1 if row["cited_by_count"] is not None else 0,
        1 if row["authors"] else 0,
        1 if row["year"] is not None else 0,
        1 if row["venue"] else 0,
        1 if row["doi"] else 0,
        1 if row["version_label"] else 0,
        1 if row["publication_type"] else 0,
    )


def library_view(store: Store) -> dict[str, Any]:
    """Every work (publication) in any non-trashed research, with its versions and the researches it belongs to."""
    conn = store.conn
    rows = conn.execute(
        "SELECT v.id AS source_version_id, v.work_id, v.title, v.authors_json, v.year, v.venue, v.volume, v.issue,"
        " v.pages, v.publication_type, v.doi, v.landing_url, v.version_label, v.cited_by_count, v.cited_by_count_at,"
        " v.created_at AS source_created_at, r.id AS research_id, r.title AS research_title, r.updated_at AS research_updated_at,"
        " m.removed_at,"
        f" {_HAS_PDF_TEXT} AS has_pdf_text, {_HAS_ABSTRACT} AS has_abstract"
        " FROM corpus_memberships m JOIN source_versions v ON v.id = m.source_version_id"
        " JOIN researches r ON r.id = m.research_id WHERE r.trashed_at IS NULL"
        " ORDER BY v.created_at DESC, r.updated_at DESC"
    ).fetchall()

    works: dict[str, dict[str, Any]] = {}
    for row in rows:
        work = works.setdefault(row["work_id"], {"versions": {}, "researches": {}})
        svid = row["source_version_id"]
        if svid not in work["versions"]:
            work["versions"][svid] = {
                "source_version_id": svid, "title": row["title"], "version_label": row["version_label"], "year": row["year"],
                "venue": row["venue"], "doi": row["doi"], "authors": json.loads(row["authors_json"]),
                "publication_type": row["publication_type"], "landing_url": row["landing_url"],
                "cited_by_count": row["cited_by_count"], "cited_by_count_at": row["cited_by_count_at"],
                "source_created_at": row["source_created_at"],
                "access_level": _access_level(row["has_pdf_text"], row["has_abstract"]),
            }
        rid = row["research_id"]
        # A source removed from a research stays in the library but not in that research's project group (D50).
        if row["removed_at"] is None and rid not in work["researches"]:
            work["researches"][rid] = {"id": rid, "title": row["research_title"], "updated_at": row["research_updated_at"]}

    entries = []
    for work_id, work in works.items():
        versions = list(work["versions"].values())
        versions.sort(key=lambda v: (v["source_created_at"] is None, v["source_created_at"] or ""), reverse=True)
        representative = max(versions, key=_library_representative_score)
        researches = sorted(work["researches"].values(), key=lambda r: r["updated_at"] or "", reverse=True)
        entries.append({
            "work_id": work_id, "source_key": store.source_key(work_id),
            "title": representative["title"],
            "authors": representative["authors"],
            "year": representative["year"], "venue": representative["venue"],
            "publication_type": representative["publication_type"], "doi": representative["doi"],
            "landing_url": representative["landing_url"],
            "cited_by_count": max((v["cited_by_count"] for v in versions if v["cited_by_count"] is not None), default=None),
            "cited_by_count_at": representative["cited_by_count_at"],
            "versions": [{"source_version_id": v["source_version_id"], "version_label": v["version_label"],
                          "year": v["year"], "venue": v["venue"], "access_level": v["access_level"]} for v in versions],
            # The best reading depth any stored version of this work reaches; the panel lists each version separately.
            "access_level": max((v["access_level"] for v in versions), key=_ACCESS_ORDER.index),
            "researches": researches,
            "first_research_id": researches[0]["id"] if researches else None,
            "newest_source_at": max(v["source_created_at"] or "" for v in versions),
        })

    # Most recently added works first; within a tie, newest active research first.
    entries.sort(key=lambda e: (e["newest_source_at"], e["first_research_id"] or ""), reverse=True)
    # Every active research, including ones with no source yet, so each can be a group and a drop target.
    researches = [dict(r) for r in conn.execute(
        "SELECT id, title, updated_at FROM researches WHERE trashed_at IS NULL ORDER BY updated_at DESC"
    )]
    return {
        "entries": entries,
        "researches": researches,
        "counts": {"works": len(entries), "versions": sum(len(e["versions"]) for e in entries),
                   "researches": len({r["id"] for e in entries for r in e["researches"]})},
    }


def library_version_to_add(work: dict[str, Any]) -> dict[str, Any]:
    """The one version of a work that joins a research when the user adds the work from the Library.

    The deepest stored reading comes first, so a paywalled published record never replaces a preprint whose
    text DEIXIS holds; among equals, the richer bibliographic record. Other versions stay out: they are
    different evidence, not copies.
    """
    return max(work["versions"], key=lambda v: (_ACCESS_ORDER.index(v["access_level"]), _library_representative_score(v)))


def library_work_view(store: Store, work_id: str) -> dict[str, Any] | None:
    """One work in reading depth: every stored version with its access level, abstract and PDF asset.

    Versions stay separate. A preprint and a published version are different evidence, so the panel
    never merges their abstracts or files into one record.
    """
    conn = store.conn
    rows = conn.execute(
        "SELECT v.id AS source_version_id, v.work_id, v.title, v.authors_json, v.year, v.venue, v.doi,"
        " v.landing_url, v.version_label, v.publication_type, v.cited_by_count, v.cited_by_count_at,"
        f" v.created_at AS source_created_at, {_HAS_PDF_TEXT} AS has_pdf_text, {_HAS_ABSTRACT} AS has_abstract"
        " FROM source_versions v WHERE v.work_id = ?"
        " AND EXISTS (SELECT 1 FROM corpus_memberships m JOIN researches r ON r.id = m.research_id"
        "  WHERE m.source_version_id = v.id AND r.trashed_at IS NULL)"
        " ORDER BY v.created_at DESC", (work_id,)
    ).fetchall()
    if not rows:
        return None

    versions, researches = [], {}
    for row in rows:
        svid = row["source_version_id"]
        abstract = conn.execute(
            "SELECT id, text, abstract_origin FROM passages WHERE source_version_id = ? AND kind = 'abstract'"
            " ORDER BY created_at DESC LIMIT 1", (svid,)
        ).fetchone()
        asset = conn.execute(
            "SELECT id, page_count, original_filename, extraction_status FROM source_assets"
            " WHERE source_version_id = ? AND removed_at IS NULL ORDER BY retrieved_at DESC LIMIT 1", (svid,)
        ).fetchone()
        members = conn.execute(
            "SELECT r.id, r.title, r.updated_at FROM corpus_memberships m JOIN researches r ON r.id = m.research_id"
            " WHERE m.source_version_id = ? AND m.removed_at IS NULL AND r.trashed_at IS NULL ORDER BY r.updated_at DESC", (svid,)
        ).fetchall()
        for member in members:
            researches.setdefault(member["id"], {"id": member["id"], "title": member["title"],
                                                 "updated_at": member["updated_at"]})
        versions.append({
            "source_version_id": svid, "version_label": row["version_label"], "year": row["year"],
            "venue": row["venue"], "doi": row["doi"], "landing_url": row["landing_url"],
            "publication_type": row["publication_type"], "authors": json.loads(row["authors_json"]),
            "cited_by_count": row["cited_by_count"], "added_at": row["source_created_at"],
            "access_level": _access_level(row["has_pdf_text"], row["has_abstract"]),
            "abstract": abstract["text"] if abstract else None,
            "abstract_origin": abstract["abstract_origin"] if abstract else None,
            # The PDF opens through a research that holds this version; the asset route is research-scoped.
            "asset": {"id": asset["id"], "page_count": asset["page_count"],
                      "original_filename": asset["original_filename"],
                      "extraction_status": asset["extraction_status"]} if asset else None,
            "abstract_passage_id": abstract["id"] if abstract else None,
            "research_id": members[0]["id"] if members else None,
            # No research holds this version now, but the one it was removed from still opens its stored text (D50).
            "removed_research_id": None if members else (removed["id"] if (removed := conn.execute(
                "SELECT r.id FROM corpus_memberships m JOIN researches r ON r.id = m.research_id"
                " WHERE m.source_version_id = ? AND m.removed_at IS NOT NULL AND r.trashed_at IS NULL"
                " ORDER BY m.removed_at DESC LIMIT 1", (svid,)).fetchone()) else None),
        })

    titles = {row["source_version_id"]: row["title"] for row in rows}
    representative = max(versions, key=_library_representative_score)
    return {
        "work_id": work_id, "source_key": store.source_key(work_id), "title": titles[representative["source_version_id"]],
        "authors": representative["authors"],
        "year": representative["year"], "venue": representative["venue"], "doi": representative["doi"],
        "landing_url": representative["landing_url"], "publication_type": representative["publication_type"],
        "cited_by_count": max((v["cited_by_count"] for v in versions if v["cited_by_count"] is not None), default=None),
        "versions": versions,
        "researches": sorted(researches.values(), key=lambda r: r["updated_at"] or "", reverse=True),
    }


def _review_view(store: Store, answer_id: str) -> dict[str, Any] | None:
    review = store.answer_review(answer_id)
    if review is None:
        return None
    session = store.conn.execute(
        "SELECT connection, requested_model, resolved_model FROM model_sessions WHERE step_id = ? ORDER BY started_at DESC LIMIT 1",
        (review["step_id"],),
    ).fetchone() if review["step_id"] else None
    completed = review["status"] == "completed"
    return {"status": review["status"], "failure_reason": review["failure_reason"], "created_at": review["created_at"],
            "reviews": review["review"]["reviews"] if completed else [], "notes": review["review"]["notes"] if completed else "",
            "issues": (review["review"] or {}).get("issues", []) if not completed else [],
            "model": dict(session) if session else None}


def passage_view(store: Store, research_id: str, passage_id: str) -> dict[str, Any] | None:
    passage = store.passage(passage_id)
    if not store.was_member(research_id, passage["source_version_id"]):
        return None
    source = store.source(passage["source_version_id"])
    return {
        "id": passage["id"], "kind": passage["kind"], "text": passage["text"], "physical_page": passage["physical_page"],
        "printed_label": passage["printed_label"], "abstract_origin": passage["abstract_origin"],
        "extraction_version": passage["extraction_version"], "payload_ref": passage["payload_ref"], "text_source": passage["text_source"],
        "equations_to_check": equations_to_check(store, passage["asset_id"], passage["extraction_version"]).get(passage["physical_page"], 0)
        if passage["text_source"] == "marker" else 0,
        "reading_depth": "abstract" if passage["kind"] == "abstract" else "selected_sections",
        "asset_id": passage["asset_id"],
        "evidence_status": store.evidence_statuses([passage_id])[passage_id],
        "removed_from_research": not store.is_active_member(research_id, passage["source_version_id"]),
        "source": {k: source[k] for k in ("id", "work_id", "title", "authors", "year", "venue", "doi", "landing_url", "version_label", "origin",
                                            "cited_by_count", "cited_by_count_at")}
        | {"source_key": store.source_key(source["work_id"])},
    }
