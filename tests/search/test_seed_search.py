"""D6: the seeds enrich the search, the question filters it. Each seed asks OpenAlex on its own, the question's request
is the unseeded one, the first chain seeds come only from what the question's request accepted, and the seed PDFs
neither push the code's graph seeds out nor add up their nearness. SYNTHETIC."""

import json

import httpx

from deixis.workflow import search as fast_search, ranking, small_batch
from test_fetch_overlap_flow import output
from test_fulltext_flow import work
from test_seed_pdf import QUESTION, SEED_PDF, SEED_TITLE, TITLE_B, SeedTransport, discovery, pdf_of, protocol_body, records, research, seed_work, seeded, select, upload
from test_small_batch_flow import app_for, client_of
from test_seed_pdf import no_upload_lookup  # noqa: F401  (fixtures used by name)

SEED_ONLY_TITLE = "SYNTHETIC a work only a seed's own request found"
PLAN_KEYS = {"version", "semantic", "keywords", "keyword_cap", "page_size", "order", "s2_bulk", "s2_bulk_index",
             "s2_reserved", "dropped", "expansion", "words"}  # words: which plan words a sent query carries (D26)


class Scripted(SeedTransport):
    """The question's semantic request answers `question`, every other semantic request `seeded`; each OpenAlex
    request is logged in order as (kind, text, per_page)."""

    def __init__(self, works, question, seeded=(), by_doi=(), fail_seed=None):
        super().__init__(works, by_doi=by_doi)
        self.question, self.seeded, self.fail_seed, self.log = question, list(seeded), fail_seed, []

    def __call__(self, request):
        params = request.url.params
        if request.url.host == "api.openalex.org" and "search.semantic" in params:
            text = params["search.semantic"]
            self.semantic_queries.append(text)
            self.log.append(("semantic", text, int(params["per_page"])))
            if text.startswith(QUESTION):
                return httpx.Response(200, json={"meta": {"count": len(self.question)}, "results": self.question})
            if self.fail_seed and text.startswith(self.fail_seed):
                return httpx.Response(400, json={"error": "SYNTHETIC refused"})
            return httpx.Response(200, json={"meta": {"count": len(self.seeded)}, "results": self.seeded})
        if (request.url.host == "api.openalex.org" and "search.title_and_abstract" in params
                and params.get("select") != "id"):
            self.log.append(("keyword", params["search.title_and_abstract"], int(params["per_page"])))
        return super().__call__(request)


def titled(number, title):
    return work(number, title=title) | {"display_name": title}


def unseeded(client):
    return client.post("/api/researches", json={"question": QUESTION, "model_connection": "fake",
                                                "requested_model": "fake-model", "effort": "quick"}).json()["research"]["id"]


# ---- 1. An unseeded run is the run before D6 ------------------------------------------------------------------------


# ---- 2. One request per seed, after the question's ------------------------------------------------------------------

def context(svid, status="matched", abstract="An abstract.", page=""):
    return {"source_version_id": svid, "status": status, "title": SEED_TITLE, "abstract": abstract,
            "first_page_text": page}


def test_a_seeded_run_asks_the_unseeded_question_then_each_seed_then_the_keywords(tmp_path, monkeypatch):
    transport = Scripted(records(), records(), seeded=[titled(4000, SEED_ONLY_TITLE)], by_doi=[seed_work()])
    app, _ = app_for(tmp_path, monkeypatch, transport=transport)
    with client_of(app) as client:
        rid = research(client)
        a, b = upload(client, rid, "a.pdf", SEED_PDF), upload(client, rid, "b.pdf", pdf_of(TITLE_B))
        select(client, rid, source_version_ids=[a, b])
        run_id, view = discovery(client, rid)
        store = app.state.store
        plan = protocol_body(store, run_id)["fast_path_search"]
        assert plan["version"] == 2 and set(plan) == PLAN_KEYS | {"seed_semantic"}
        assert plan["semantic"]["query_text"] == QUESTION and set(plan["semantic"]) == {
            "provider_id", "endpoint", "query_text", "limit", "query_origin"}
        assert [(s["source_version_id"], s["limit"]) for s in plan["seed_semantic"]] == [(a, 25), (b, 25)]
        semantic = [entry for entry in transport.log if entry[0] == "semantic"]
        question = semantic.index(("semantic", QUESTION, 50))
        # B had no DOI: its lookup (D3) went before the plan; then the question, then A and B by their own text.
        assert [entry[1] for entry in semantic[question + 1:]] == [s["query_text"] for s in plan["seed_semantic"]]
        assert [entry[2] for entry in semantic[question + 1:]] == [25, 25]
        first_keyword = next(i for i, entry in enumerate(transport.log) if entry[0] == "keyword")
        assert transport.log.index(semantic[-1]) < first_keyword
        for i in (0, 1):
            step = store.existing_step(run_id, f"search:fast:semantic:seed:{i}")
            assert step["status"] == "succeeded" and step["output"]["fast_path_request"]["class"] == 0
            assert "accepted_source_version_ids" not in step["output"]
        # The seeds' finds enter the pool as search candidates, never as the first chain seeds.
        found = store.find_source_by_identifier("openalex", "W4000")
        assert found in {c["source_version_id"] for c in store.candidates(rid)}
        assert found not in {s["source_version_id"] for s in output(store, run_id, "fast_chain:seeds")["seeds"]}
        assert [u["semantic"] for u in (s["use"] for s in view["scope"]["seeds"])] == [True, True]
        assert fast_search.graph_rule(store, store.run(run_id)) == "seed_max_v2"
        listing = output(store, run_id, small_batch.LIST_KEY)
        assert listing["manifest"]["graph_rule"] == "seed_max_v2"
        assert small_batch.replay(listing["manifest"])["fused"] == listing["automatic_order"]


# ---- 3. The first chain seeds come only from what the question's request accepted (v4) ------------------------------


# ---- 4. The ranking: seed PDFs take no code seed's place and count by the nearest -----------------------------------

def row(rid, refs, *, work=None, own=None, pdf=False):
    found = {"id": rid, "work_id": work or f"w-{rid}", "title": f"SYNTHETIC {rid}", "abstract": None,
             "own_ids": frozenset(own or {f"O{rid}"}), "references": frozenset(refs)}
    return found | ({"seed_pdf": True} if pdf else {})


def pool_of(n=24):
    return [row(f"r{i:02d}", {f"R{i}", "RA"}) for i in range(n)]


def test_nearness_to_two_seed_pdfs_is_not_added_up():
    near_two = row("x", {"S1", "S2", "Z"})
    near_one = row("y", {"S1", "Z", "Q"})
    pdfs = [row("p1", {"S1", "K1"}, pdf=True), row("p2", {"S2", "K2"}, pdf=True)]
    summed = ranking.graph_scores([near_two, near_one], pdfs)
    nearest = ranking.graph_scores_v2([near_two, near_one], [], pdfs)
    assert summed["x"] > summed["y"]
    assert nearest["x"] == nearest["y"] == summed["y"]
    # A seed PDF never scores its own work, and the user's and code's seeds still add up.
    own = row("p1copy", {"S1"}, work="w-p1")
    assert ranking.graph_scores_v2([own], [], pdfs[:1]) == {"p1copy": 0.0}
    others = [row("u1", {"Z"}), row("u2", {"Z"})]
    assert ranking.graph_scores_v2([near_one], others, []) == ranking.graph_scores([near_one], others)


def test_a_frozen_list_replays_under_the_rule_it_froze():
    pool = pool_of()
    pdfs = [row(f"p{i}", {"RA", f"R{i}"}, pdf=True) for i in range(3)]

    def stored(r):
        return r | {"own_ids": sorted(r["own_ids"]), "references": sorted(r["references"]), "cited_by_count": None}
    manifest = {"ranking_version": 3, "pool": [stored(r) for r in pool], "verified": [stored(r) for r in pdfs],
                "query_words": ["synthetic"], "blocks": {}, "embedding_model": None, "similarities": {},
                "off_reason": None, "compared_terms": None}
    old = small_batch.replay(manifest)
    new = small_batch.replay(manifest | {"graph_rule": "seed_max_v2"})
    assert old["graph_seeds"][:3] == [r | {"own_ids": set(r["own_ids"]), "references": set(r["references"])}
                                      for r in manifest["verified"]]
    assert [s["id"] for s in new["graph_seeds"][-3:]] == ["p0", "p1", "p2"]
    assert small_batch.replay(manifest)["fused"] == old["fused"]


# ---- 5. A run frozen before D6 finishes under it ---------------------------------------------------------------------


# ---- 6. seed_terms: the terms the seeds brought, a diagnosis only ---------------------------------------------------
