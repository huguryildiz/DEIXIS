"""Pure planning and mocked provider checks; no scientific or live-provider claims."""
import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from deixis.domain import contracts
from deixis.domain.rules import MAX_RATE_LIMIT_MODEL_RETRIES, MAX_TRANSIENT_NETWORK_RETRIES, RevisionConflict, schema_repairs
from deixis.providers.common import MAX_RATE_LIMIT_RETRIES
from deixis.providers.registry import CONNECTORS
from deixis.workflow.candidates import run as planning
from deixis.workflow.store import NotFound
from test_candidate_flow import lib, queue_kill, execute, search
from test_candidate_store import version as edit_version


def row(kind="abstract", text="SYNTHETIC text", n=1):
    return {"id": f"pas_{n:020d}", "source_version_id": "srv_00000000000000000001", "text": text, "kind": kind,
            "physical_page": n if kind == "pdf_page" else None, "printed_label": None, "abstract_origin": "provider" if kind == "abstract" else None}


def test_model_ceilings_follow_the_constants_6_54_60(monkeypatch):
    decomposition = planning.attempts("claim_decomposition")
    search = planning.attempts("kill_search_query") + planning.KILL_KEEP * planning.attempts("claim_assessment")
    assert (decomposition, search, decomposition + search) == (6, 54, 60)
    for task in contracts.CANDIDATE_TASKS:
        assert planning.attempts(task) == (1 + schema_repairs(task)) * (1 + MAX_RATE_LIMIT_MODEL_RETRIES)
    monkeypatch.setattr(planning, "MAX_RATE_LIMIT_MODEL_RETRIES", 0)
    assert planning.attempts("claim_decomposition") == 1 + schema_repairs("claim_decomposition")


def test_every_connector_has_a_bounded_transport_ceiling_and_pubmed_costs_two():
    for pid, connector in CONNECTORS.items():
        assert isinstance(connector.requests_per_search, int) and connector.requests_per_search > 0
        plan = planning.transport_plan([pid])
        assert plan["max_provider_requests"] == connector.requests_per_search * (1 + MAX_RATE_LIMIT_RETRIES) * (1 + MAX_TRANSIENT_NETWORK_RETRIES)
    assert CONNECTORS["pubmed"].requests_per_search == 2


def test_pubmed_really_sends_two_requests_per_search():
    requests = []
    def transport(request):
        requests.append(request.url.path)
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, json={"esearchresult": {"count": "1", "idlist": ["1"]}})
        return httpx.Response(200, text='<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>1</PMID><Article><ArticleTitle>SYNTHETIC</ArticleTitle></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            return await CONNECTORS["pubmed"].search(client, "SYNTHETIC", 20)
    assert asyncio.run(run()).status == "completed"
    assert len(requests) == CONNECTORS["pubmed"].requests_per_search
    assert requests[0].endswith("esearch.fcgi") and requests[1].endswith("efetch.fcgi")


def test_eligible_providers_keep_scope_order_drop_missing_keys_and_respect_sw(monkeypatch):
    monkeypatch.delenv("IEEE_API_KEY", raising=False)
    scope = {"providers": ["pubmed", "crossref", "ieee_xplore", "openalex", "scopus", "arxiv"], "search_workflow": "sw"}
    assert planning.eligible_providers(scope) == ["pubmed", "openalex", "arxiv"]
    monkeypatch.setitem(CONNECTORS, "pubmed", replace(CONNECTORS["pubmed"], requests_per_search=0))
    assert planning.eligible_providers(scope) == ["openalex", "arxiv"]


@pytest.mark.parametrize("rows,depth,length", [([row()], "abstract", 1),
    ([row(), row("pdf_page", n=2)], "stored_passages", 2),
    ([row(text=" "), row("pdf_page", text="\n", n=2)], "metadata_only", 0),
    ([row("references")], "metadata_only", 0), ([], "metadata_only", 0)])
def test_shown_passages_ignore_blank_and_other_kinds_and_derive_depth(rows, depth, length):
    shown = planning.shown_passages(rows)
    assert shown["reading_depth"] == depth and len(shown["passages"]) == length


def test_shown_text_is_cut_and_no_more_than_six_pages_are_shown_in_page_order():
    rows = [row(text="a" * 3000)] + [row("pdf_page", "p" * 5000, n) for n in range(9, 1, -1)]
    shown = planning.shown_passages(rows)
    assert [len(p["text"]) for p in shown["passages"]] == [2500] + [4000] * 6
    assert [p["physical_page"] for p in shown["passages"][1:]] == list(range(2, 8))
    assert shown["omitted"]["page_limit"] == 2


def test_message_fit_drops_trailing_pages_always_retains_abstract_and_reports_oversize():
    rows = [row()] + [row("pdf_page", n=n) for n in range(2, 8)]
    shown = planning.shown_passages(rows, lambda rows: len(rows) * 100, limit=250)
    assert [p["kind"] for p in shown["passages"]] == ["abstract", "pdf_page"]
    assert shown["omitted"]["message_size"] == 5 and not shown["message_too_large"]
    too_big = planning.shown_passages(rows, lambda rows: len(rows) * 100, limit=50)
    assert too_big["reading_depth"] == "abstract" and too_big["message_too_large"]
    assert too_big["passages"] == rows[:1]


def test_decomposition_basis_uses_frozen_cells_live_current_passages_and_frozen_claims():
    passage = row(text="current" * 400)
    candidate = {"id": "clm_00000000000000000001", "origin": "report_gap", "gap_kind": "corpus_absence", "origin_text": "SYNTHETIC gap",
                 "origin_basis_view_json": json.dumps({"basis_cell_ids": [{"id": "cell", "text": "frozen cell"}, {"id": "missing", "missing": True}],
                    "basis_passage_ids": [{"id": passage["id"], "source_version_id": passage["source_version_id"], "text": "old"},
                                          {"id": "non_current", "source_version_id": passage["source_version_id"], "text": "old"}],
                    "basis_claim_keys": [{"id": "claim", "text": "frozen claim"}, {"id": "blank", "text": " "}]})}
    built = planning.decomposition_input(candidate, {passage["source_version_id"]: [passage]})
    assert [b["kind"] for b in built["target"]["basis"]] == ["cell", "passage", "claim"]
    assert built["target"]["basis"][1]["text"] == passage["text"][:1500]
    assert built["omitted"] == {"missing": 1, "non_current": 1, "blank": 1, "basis_limit": 0, "message_size": 0}
    assert built["passages"][0]["text"] == passage["text"][:1500]
    candidate["origin"] = "owner_text"
    candidate["gap_kind"] = None
    assert planning.decomposition_input(candidate, {})["target"]["basis"] == []


def test_decomposition_basis_caps_at_24_and_counts_message_drops():
    candidate = {"id": "clm_00000000000000000001", "origin": "report_gap", "gap_kind": "corpus_absence", "origin_text": "SYNTHETIC",
                 "origin_basis_view_json": json.dumps({"basis_cell_ids": [{"id": str(i), "text": "SYNTHETIC"} for i in range(30)]})}
    built = planning.decomposition_input(candidate, {})
    assert len(built["target"]["basis"]) == 24 and built["omitted"]["basis_limit"] == 6
    fitted = planning.pack_decomposition(built, lambda target, rows: len(target["basis"]) * 100, limit=250)
    assert len(fitted["target"]["basis"]) == 2 and fitted["omitted"]["message_size"] == 22


def test_plan_fingerprint_is_stable_and_changes_with_version_provider_model_or_skill(lib):
    edit_version(lib, lib.candidate)
    p = lib.planner.preview(lib.rid, lib.candidate["id"])
    assert p == lib.planner.preview(lib.rid, lib.candidate["id"])
    assert p["budget"]["max_model_calls"] == 54
    edit_version(lib, lib.candidate)
    assert lib.planner.preview(lib.rid, lib.candidate["id"])["preview_fingerprint"] != p["preview_fingerprint"]
    for column, value in (("providers_json", '["pubmed"]'), ("requested_model", "fake-other-model")):
        old = lib.planner.preview(lib.rid, lib.candidate["id"])
        lib.conn.execute(f"UPDATE scope_revisions SET {column} = ? WHERE research_id = ?", (value, lib.rid))
        assert lib.planner.preview(lib.rid, lib.candidate["id"])["preview_fingerprint"] != old["preview_fingerprint"]
    old = lib.planner.preview(lib.rid, lib.candidate["id"])
    lib.planner.skill_package_hash = "sha256:different"
    assert lib.planner.preview(lib.rid, lib.candidate["id"])["preview_fingerprint"] != old["preview_fingerprint"]


def test_preview_refusals_no_version_no_provider_and_trashed(lib):
    with pytest.raises(planning.CandidateRunInput, match="candidate_not_decomposed"):
        lib.planner.preview(lib.rid, lib.candidate["id"])
    edit_version(lib, lib.candidate)
    lib.conn.execute("UPDATE scope_revisions SET providers_json = '[]' WHERE research_id = ?", (lib.rid,))
    with pytest.raises(planning.CandidateRunInput, match="no_searchable_provider"):
        lib.planner.preview(lib.rid, lib.candidate["id"])
    lib.candidate_store.trash_candidate(lib.rid, lib.candidate["id"])
    with pytest.raises(RevisionConflict):
        lib.planner.preview(lib.rid, lib.candidate["id"])


def test_request_replay_precedes_edits_and_refuses_mismatched_fingerprint(lib):
    run = queue_kill(lib, "replay")
    edit_version(lib, lib.candidate)
    assert lib.planner.request_run(lib.rid, lib.candidate["id"], run["target"]["preview_fingerprint"], "replay")["id"] == run["id"]
    with pytest.raises(RevisionConflict):
        lib.planner.request_run(lib.rid, lib.candidate["id"], "0" * 64, "replay")
    lib.store.update_run(run["id"], status="completed")
    with pytest.raises(RevisionConflict):
        lib.planner.request_run(lib.rid, lib.candidate["id"], run["target"]["preview_fingerprint"])


def test_evidence_reader_returns_only_stored_input_not_live_passages_or_corpus(lib, monkeypatch):
    run = queue_kill(lib)
    execute(lib, run)
    s = search(lib, run)
    hit = lib.candidate_store.hits(s["id"])[0]
    payload = lib.store.step_input_payload(hit["step_input_id"])
    def forbidden(*args, **kw):
        raise AssertionError("Candidate evidence tried a corpus/live passage view")
    monkeypatch.setattr(lib.store, "passage_view", forbidden, raising=False)
    monkeypatch.setattr(lib.store, "passages_for", forbidden)
    view = planning.candidate_evidence(lib.store, lib.rid, lib.candidate["id"], s["id"], hit["source_version_id"])
    assert view["passages"] == payload["passages"]
    assert view["source"]["title"] == lib.store.source(hit["source_version_id"])["title"]
    with pytest.raises(NotFound):
        planning.candidate_evidence(lib.store, lib.rid, lib.candidate["id"], s["id"], "srv_unknown")


@pytest.mark.parametrize("mode", ["pending", "insufficient_access", "cut"])
def test_evidence_reader_never_exposes_text_for_unassessed_or_cut_hits(lib, mode):
    from test_candidate_store import provider_record
    lib.provider(records=[provider_record(str(i), abstract=None if mode == "insufficient_access" else "SYNTHETIC") for i in range(9)])
    run = queue_kill(lib)
    if mode == "pending":
        lib.store.add_usage(run["id"], "model_calls", 53)
    execute(lib, run)
    s = search(lib, run)
    hits = lib.candidate_store.hits(s["id"])
    hit = next(h for h in hits if not h["kept"]) if mode == "cut" else hits[0]
    if mode == "cut":
        with pytest.raises(NotFound):
            planning.candidate_evidence(lib.store, lib.rid, lib.candidate["id"], s["id"], hit["source_version_id"])
    else:
        view = planning.candidate_evidence(lib.store, lib.rid, lib.candidate["id"], s["id"], hit["source_version_id"])
        assert view["passages"] == [] and view["quotes"] == []


def test_evidence_reader_refuses_another_candidate_or_researchs_search(lib):
    run = queue_kill(lib)
    execute(lib, run)
    s = search(lib, run)
    hit = lib.candidate_store.hits(s["id"])[0]
    other = lib.candidate_store.open_from_owner_text(lib.rid, "SYNTHETIC other candidate")
    with pytest.raises(NotFound):
        planning.candidate_evidence(lib.store, lib.rid, other["id"], s["id"], hit["source_version_id"])
    research = lib.store.create_research("SYNTHETIC other research", "attached", "quick", [], "fake", "fake-model", "en")
    with pytest.raises(NotFound):
        planning.candidate_evidence(lib.store, research, lib.candidate["id"], s["id"], hit["source_version_id"])


def test_historical_search_status_stays_bound_to_that_search_not_the_latest(lib):
    from test_candidate_store import provider_record
    lib.provider(records=[])
    first = queue_kill(lib)
    execute(lib, first)
    lib.provider(records=[provider_record(abstract=None)])
    second = queue_kill(lib)
    execute(lib, second)
    assert lib.candidate_store.search_status(search(lib, first)["id"])["status"] == "open"
    assert lib.candidate_store.search_status(search(lib, second)["id"])["status"] == "undecided"
    version = lib.candidate_store.versions(lib.candidate["id"])[-1]
    card = lib.candidate_store.candidate_status(version["id"])
    assert card["computed"]["status"] == "undecided" and card["previous"]["status"] == "open"
