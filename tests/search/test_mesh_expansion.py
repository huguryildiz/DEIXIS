"""PubMed's verified MeSH headings: where they come from, what they are written into, and what is recorded instead.

Synthetic throughout — no live app, provider or model; the two NCBI lookups are scripted. What is guarded here is
that a heading is used only when NCBI both mapped the term to it and holds it as a descriptor of that name, that a
heading is written beside its term and never in its place, that the compiled query's own terms are untouched, and
that every run without an expansion says why.
"""

import asyncio
from types import SimpleNamespace

import pytest

from deixis.domain.rules import TEST_EFFORT_BUDGETS
from deixis.providers import pubmed, query_compiler
from deixis.providers.common import ProviderRecord, SearchOutcome
from deixis.runtime.config import Settings
from deixis.storage import db
from deixis.workflow.run import fast_path, views
from deixis.workflow.run import flow as flow_module
from deixis.workflow.run.flow import ResearchFlow
from deixis.workflow.run.store import Store
from deixis.workflow.search import mesh, search as fast_search, small_batch
from test_fast_path_clock import FakeClock

QUESTION = "SYNTHETIC heading question"
# The two blocks the compiler writes, as a vocabulary holds them: the form that enters the query is the root word
# of a phrase or the phrase itself.
TERMS = [{"block": "setting", "root": "heart attack", "phrase": "heart attack", "in_query": "phrase", "dropped": None},
         {"block": "task", "root": "plasticity", "phrase": "neuronal plasticity", "in_query": "root", "dropped": None}]
GROUPS = [["heart attack"], ["plasticity"]]
MAPPING = [{"from": "heart attack", "to": '"myocardial infarction"[MeSH Terms] OR "heart attack"[All Fields]'},
           {"from": "plasticity", "to": '"neuronal plasticity"[MeSH Terms] OR "plasticity"[All Fields]'}]
VERIFIED = {"myocardial infarction": {"descriptor": "Myocardial Infarction", "mesh_ui": "D009203"},
            "neuronal plasticity": {"descriptor": "Neuronal Plasticity", "mesh_ui": "D009473"}}


def _vocabulary(terms=None):
    return {"terms": list(terms if terms is not None else TERMS)}


def _pubmed_query(groups=None):
    """The query the compiler writes for PubMed from these blocks, which is what the run stores."""
    text, _ = query_compiler.fit_block_counts("pubmed", groups or GROUPS)
    return {"provider_id": "pubmed", "query_text": text}


def _queries(groups=None):
    return [{"provider_id": "openalex", "query_text": "SYNTHETIC alpha"}, _pubmed_query(groups)]


# --- what NCBI's own mapping says -----------------------------------------------------------------------------

@pytest.mark.parametrize("translation,heading", [
    ('"myocardial infarction"[MeSH Terms] OR "heart attack"[All Fields]', "myocardial infarction"),
    ('"myocardial infarction"[MeSH Terms]', "myocardial infarction"),
    # The phrase PubMed split into words: the headings belong to the words, not to the phrase.
    ('("heart"[MeSH Terms] AND "attack"[All Fields]) OR "heart attack"[All Fields]', None),
    # Two headings at the top level leave the phrase ambiguous, so neither is read.
    ('"myocardial infarction"[MeSH Terms] OR "myocardial ischemia"[MeSH Terms]', None),
    # A heading joined by AND to anything else: PubMed searched the words together, not the phrase itself.
    ('"myocardial infarction"[MeSH Terms] AND ("heart"[All Fields])', None),
    ('"myocardial infarction"[MeSH Terms] NOT "review"[Publication Type]', None),
    ('"heart attack"[All Fields]', None),
    # Parentheses inside the name are part of the name and open no group of their own.
    ('"Receptors, Antigen (T-Cell)"[MeSH Terms] OR "x"[All Fields]', "Receptors, Antigen (T-Cell)"),
])
def test_only_a_heading_mapped_for_the_whole_phrase_is_read(translation, heading):
    assert pubmed.mapped_heading(translation) == heading


def test_the_lookup_sends_the_plan_s_own_blocks_unquoted():
    """A quoted phrase is searched as it stands and gets no mapping, so the lookup quotes nothing."""
    # Alternatives of a block stay a group; a block holding one term needs none.
    assert mesh.lookup_text([["heart attack", "infarction"], ["plasticity"]]) == \
        "(heart attack OR infarction) AND plasticity"


def test_a_term_is_read_back_by_its_own_text_and_a_term_without_a_heading_says_why():
    found, missing = mesh.heading_candidates(
        [{"from": "heart attack", "to": '"myocardial infarction"[MeSH Terms] OR "x"[All Fields]'},
         {"from": "split", "to": '("a"[MeSH Terms] AND "b"[All Fields])'},
         {"from": "plain", "to": '"plain"[All Fields]'}],
        ["heart attack", "split", "plain", "never mapped"])
    assert found == {"heart attack": "myocardial infarction"}
    assert missing == {"split": "not_the_whole_phrase", "plain": "not_a_heading", "never mapped": "not_mapped"}


# --- what the heading is written into --------------------------------------------------------------------------

def test_a_heading_is_written_beside_its_term_in_the_provider_s_own_syntax():
    expanded = mesh.expanded("pubmed", GROUPS, {"heart attack": "Myocardial Infarction"})
    # A single word stays unquoted, as the compiler writes it; the heading is an alternative of the term, never a
    # replacement, so a record PubMed has not indexed is still reachable.
    assert expanded["query_text"] == ('("heart attack"[Title/Abstract] OR "Myocardial Infarction"[MeSH Terms])'
                                      ' AND plasticity[Title/Abstract]')
    assert expanded["headings"] == [{"term": "heart attack", "heading": "Myocardial Infarction"}]
    assert expanded["dropped"] == [] and expanded["rule"] == mesh.RULE


def test_no_verified_heading_leaves_the_compiled_query_alone():
    assert mesh.expanded("pubmed", GROUPS, {}) is None
    # A heading for a term this query does not carry is not written into it either.
    assert mesh.expanded("pubmed", GROUPS, {"absent term": "Heading"}) is None


def test_the_length_bound_drops_headings_and_never_a_term():
    groups = [["alpha", "beta"], ["gamma"]]
    headings = {"alpha": "Alpha Heading", "beta": "Beta Heading", "gamma": "Gamma Heading"}
    compiled, _ = query_compiler.fit_block_counts("pubmed", groups)
    # A bound that fits the terms and nothing else: every heading goes, so the caller sends the compiled query.
    assert mesh.expanded("pubmed", groups, headings, max_chars=len(compiled)) is None
    # A heading goes from the block holding the most of them, the last one of that block first.
    tight = mesh.expanded("pubmed", groups, headings, max_chars=185)
    assert tight is not None and tight["dropped"] == ["beta"]
    assert [row["term"] for row in tight["headings"]] == ["alpha", "gamma"]
    # Tighter still: with a heading left in each block the last block gives one up, which is the tie the
    # compiler itself breaks the same way when it takes a term.
    tighter = mesh.expanded("pubmed", groups, headings, max_chars=140)
    assert tighter is not None and tighter["dropped"] == ["beta", "gamma"]
    assert [row["term"] for row in tighter["headings"]] == ["alpha"]
    # Whatever went, every term the compiler fitted is still searched.
    for text in (tight["query_text"], tighter["query_text"]):
        for term in ("alpha", "beta", "gamma"):
            assert term in text


def test_the_page_sends_the_expanded_text_and_the_query_keeps_its_compiled_text():
    query = _pubmed_query() | {"mesh": {"query_text": "SYNTHETIC expanded"}}
    assert mesh.sent_query(query)["query_text"] == "SYNTHETIC expanded"
    assert query["query_text"] == _pubmed_query()["query_text"]
    # Nothing to send differently: the compiled query goes as it is.
    assert mesh.sent_query(_pubmed_query()) == _pubmed_query()
    assert mesh.sent_query(_pubmed_query() | {"mesh": {"reason": "lookup_failed"}})["query_text"] == \
        _pubmed_query()["query_text"]


# --- the step the run writes ------------------------------------------------------------------------------------

def _library(tmp_path, name="library.sqlite", effort="standard", providers=None, evidence_minimum=True):
    conn = db.connect(tmp_path / name)
    db.migrate(conn)
    clock = FakeClock()
    store = Store(conn, clock)
    clock.store = store
    rid = store.create_research(QUESTION, "academic", effort,
                               providers or ["openalex", "semantic_scholar", "pubmed", "arxiv"],
                               "fake", "fake-model", "en")
    budget = small_batch.freeze_budget(TEST_EFFORT_BUDGETS[effort].__dict__, effort, "off")
    budget["fast_path"] = fast_path.freeze_budget(budget, effort, uniform_search=False)
    if not evidence_minimum:
        # A run frozen before the evidence minimum, under which the handover still ends the plan stage.
        policy = {k: v for k, v in budget["fast_path"].items() if k not in ("evidence_minimum", "policy_hash")}
        from deixis.domain import canonical
        budget["fast_path"] = policy | {"policy_hash": canonical.sha256_hex(policy)}
    run = store.create_run(rid, "discovery", budget, None)
    store.update_run(run["id"], status="running")
    return SimpleNamespace(store=store, conn=conn, clock=clock, rid=rid, run=store.run(run["id"]))


def _routing(lib, chosen, status="read", queries=None):
    step = lib.store.step(lib.run["id"], "source_routing", "code:source_routing")
    lib.store.start_step(step["id"])
    record = {"status": status, "query": "SYNTHETIC gate", "total": 100, "fields": [], "route_share": 0.25,
              "table_version": "deixis.source_routes.v1",
              "chosen": [{"provider_id": "openalex", "reason": "always"}] + chosen, "left_out": [],
              "providers": ["openalex"] + [row["provider_id"] for row in chosen]}
    lib.store.finish_step(step["id"], "succeeded", output={"routing": record, "reads": {}, "vocabulary": {},
                                                           "queries": queries or _queries(), "query_compiler": "v1"})
    return record


def _flow(lib, tmp_path, mapping=None, verified=None, lookup=None, descriptors=None):
    flow = ResearchFlow(SimpleNamespace(store=lib.store, clock=lib.clock,
                                        settings=Settings(data_dir=tmp_path / "data"), local_embedder=None,
                                        http=None))
    asked = []

    async def mesh_mapping(client, text, **kwargs):
        asked.append(text)
        return lookup or {"status": "completed", "request": "SYNTHETIC lookup", "requests": 1, "retries": 0,
                          "translations": MAPPING if mapping is None else mapping}

    async def mesh_descriptors(client, names, **kwargs):
        asked.append(tuple(names))
        return descriptors or {"status": "completed", "request": "SYNTHETIC verification", "requests": 2,
                               "retries": 0, "verified": VERIFIED if verified is None else verified, "missing": []}

    flow_module.pubmed.mesh_mapping = mesh_mapping
    flow_module.pubmed.mesh_descriptors = mesh_descriptors
    return flow, asked


@pytest.fixture(autouse=True)
def _restore_adapter():
    mapping, descriptors = pubmed.mesh_mapping, pubmed.mesh_descriptors
    yield
    pubmed.mesh_mapping, pubmed.mesh_descriptors = mapping, descriptors


def _expand(lib, tmp_path, **kwargs):
    flow, asked = _flow(lib, tmp_path, **kwargs)
    queries = asyncio.run(flow._mesh_expansion(lib.run, lib.store.scope(lib.rid), _vocabulary(), _queries()))
    return queries, lib.store.existing_step(lib.run["id"], "mesh_expansion")["output"], asked


def test_the_field_source_s_query_carries_the_headings_ncbi_confirmed(tmp_path):
    lib = _library(tmp_path)
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    queries, output, asked = _expand(lib, tmp_path)
    expanded = next(query for query in queries if query["provider_id"] == "pubmed")
    assert expanded["mesh"]["query_text"] == (
        '("heart attack"[Title/Abstract] OR "Myocardial Infarction"[MeSH Terms]) AND'
        ' (plasticity[Title/Abstract] OR "Neuronal Plasticity"[MeSH Terms])')
    # The identifier of each heading is kept, so a reader can look the heading up itself.
    assert expanded["mesh"]["headings"] == [
        {"term": "heart attack", "heading": "Myocardial Infarction", "mesh_ui": "D009203"},
        {"term": "plasticity", "heading": "Neuronal Plasticity", "mesh_ui": "D009473"}]
    # The compiled text is untouched: it is what the plan's own word record is read back against.
    assert expanded["query_text"] == _pubmed_query()["query_text"]
    # The lookup asked for the plan's own blocks unquoted, then verified the names it was given.
    assert asked == ["heart attack AND plasticity", ("myocardial infarction", "neuronal plasticity")]
    assert output["rule"] == mesh.RULE and output["lookup"]["status"] == "completed"
    assert output["mapped"] == {"heart attack": "myocardial infarction", "plasticity": "neuronal plasticity"}
    lib.conn.close()


def test_a_query_no_other_provider_gets_the_expansion(tmp_path):
    lib = _library(tmp_path, "others.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    queries, _, _ = _expand(lib, tmp_path)
    assert [query.get("mesh") for query in queries if query["provider_id"] != "pubmed"] == [None]
    lib.conn.close()


@pytest.mark.parametrize("effort,chosen,providers,reason", [
    # The depth pays for no field source, so there is nothing to expand.
    ("quick", [{"provider_id": "pubmed", "reason": "share", "share": 0.9}], None, "depth_searches_no_field_source"),
    # Another source's fields hold more of the question: PubMed is not the source this depth sends.
    ("standard", [{"provider_id": "pubmed", "reason": "share", "share": 0.3},
                  {"provider_id": "arxiv", "reason": "share", "share": 0.7}], None, "not_the_field_source"),
    # The share could not be read, so no source is the one that fits best.
    ("standard", [], None, "not_the_field_source"),
    # The person's own sources decide, whatever the record chose while PubMed was in.
    ("standard", [{"provider_id": "pubmed", "reason": "share", "share": 0.9}],
     ["openalex", "semantic_scholar", "arxiv"], "not_in_scope"),
])
def test_a_run_that_will_not_search_pubmed_expands_nothing_and_says_why(tmp_path, effort, chosen, providers, reason):
    lib = _library(tmp_path, f"{reason}-{effort}.sqlite", effort=effort, providers=providers)
    _routing(lib, chosen)
    queries, output, asked = _expand(lib, tmp_path)
    assert output["reason"] == reason and asked == []
    assert all("mesh" not in query for query in queries)
    lib.conn.close()


def test_a_query_the_compiler_does_not_write_again_is_not_expanded(tmp_path):
    """A stored text its own vocabulary does not reproduce says nothing about the terms it holds, so no heading is
    put beside a term this query may not carry."""
    lib = _library(tmp_path, "unread.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    flow, asked = _flow(lib, tmp_path)
    queries = [{"provider_id": "pubmed", "query_text": "SYNTHETIC hand-written"}]
    result = asyncio.run(flow._mesh_expansion(lib.run, lib.store.scope(lib.rid), _vocabulary(), queries))
    output = lib.store.existing_step(lib.run["id"], "mesh_expansion")["output"]
    assert output["reason"] == "query_not_read_back" and asked == [] and result == queries
    lib.conn.close()


def test_no_query_compiled_for_pubmed_is_recorded(tmp_path):
    lib = _library(tmp_path, "nocompile.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    flow, asked = _flow(lib, tmp_path)
    queries = [{"provider_id": "openalex", "query_text": "SYNTHETIC alpha"}]
    asyncio.run(flow._mesh_expansion(lib.run, lib.store.scope(lib.rid), _vocabulary(), queries))
    assert lib.store.existing_step(lib.run["id"], "mesh_expansion")["output"]["reason"] == "query_not_compiled"
    assert asked == []
    lib.conn.close()


@pytest.mark.parametrize("kwargs,reason", [
    ({"lookup": {"status": "failed", "request": "SYNTHETIC", "requests": 1, "retries": 1, "translations": [],
                 "error": "SYNTHETIC refusal"}}, "lookup_failed"),
    ({"mapping": []}, "no_heading_mapped"),
    ({"descriptors": {"status": "rate_limited", "request": "SYNTHETIC", "requests": 1, "retries": 2,
                      "verified": {}, "missing": ["myocardial infarction"]}}, "verification_failed"),
    ({"verified": {}}, "no_heading_verified"),
])
def test_a_lookup_that_confirms_nothing_leaves_the_compiled_query_exactly_as_it_was(tmp_path, kwargs, reason):
    lib = _library(tmp_path, f"{reason}.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    queries, output, _ = _expand(lib, tmp_path, **kwargs)
    assert output["reason"] == reason
    assert all("mesh" not in query for query in queries)
    assert next(q for q in queries if q["provider_id"] == "pubmed")["query_text"] == _pubmed_query()["query_text"]
    # What was asked and what came back is kept, so a reader can tell a refusal from an empty answer.
    if reason != "lookup_failed":
        assert output["lookup"]["status"] == "completed"
    lib.conn.close()


def test_a_heading_the_mesh_database_does_not_hold_is_dropped_and_the_others_stay(tmp_path):
    lib = _library(tmp_path, "partial.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    verified = {"myocardial infarction": VERIFIED["myocardial infarction"]}
    queries, output, _ = _expand(lib, tmp_path, verified=verified)
    expanded = next(query for query in queries if query["provider_id"] == "pubmed")
    assert [row["heading"] for row in expanded["mesh"]["headings"]] == ["Myocardial Infarction"]
    assert "Neuronal Plasticity" not in expanded["mesh"]["query_text"]
    assert output["verification"]["verified"] == verified
    lib.conn.close()


def test_a_resumed_run_reads_the_step_and_asks_ncbi_nothing_again(tmp_path):
    lib = _library(tmp_path, "resume.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    _expand(lib, tmp_path)

    async def refuse(*args, **kwargs):
        raise AssertionError("a resumed run asked NCBI again")

    flow = ResearchFlow(SimpleNamespace(store=lib.store, clock=lib.clock, http=None,
                                        settings=Settings(data_dir=tmp_path / "data"), local_embedder=None))
    flow_module.pubmed.mesh_mapping = refuse
    flow_module.pubmed.mesh_descriptors = refuse
    queries = asyncio.run(flow._mesh_expansion(lib.run, lib.store.scope(lib.rid), _vocabulary(), _queries()))
    assert next(query for query in queries if query["provider_id"] == "pubmed")["mesh"]["headings"]
    lib.conn.close()


# --- what the person is shown and what is really sent -----------------------------------------------------------

def _searched(lib, provider, records, status="completed"):
    step = lib.store.step(lib.run["id"], f"search:field:{provider}", "provider_search")
    lib.store.start_step(step["id"])
    lib.store.add_search_run(research_id=lib.rid, run_id=lib.run["id"], step_id=step["id"], scope_revision=1,
                             provider=provider, query_text="SYNTHETIC sent", request_description="SYNTHETIC",
                             access_mode="open", status=status, result_count=records, page_limit=250,
                             request_class=fast_search.FIELD_CLASS, request_index=0, returned_count=records)


def test_the_field_source_row_names_the_headings_the_sent_query_carries(tmp_path):
    lib = _library(tmp_path, "view.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    queries, _, _ = _expand(lib, tmp_path)
    plan = fast_search.build_plan(lib.store, lib.run, lib.store.scope(lib.rid), queries)
    _searched(lib, "pubmed", 12)
    view = views.field_search_view(lib.store, lib.run, {"fast_path_search": plan, "source_routing": {}})
    (row,) = [row for row in view["rows"] if row["provider_id"] == "pubmed"]
    assert row["headings"] == ["Myocardial Infarction", "Neuronal Plasticity"]
    # A source with no expansion of its own names none, rather than an empty list.
    plain = views.field_search_view(lib.store, lib.run,
                                    {"fast_path_search": fast_search.build_plan(lib.store, lib.run,
                                                                                lib.store.scope(lib.rid), _queries()),
                                     "source_routing": {}})
    assert [row["headings"] for row in plain["rows"] if row["provider_id"] == "pubmed"] == [None]
    lib.conn.close()


@pytest.mark.parametrize("answered,state", [(None, "planned"), ("failed", "request_failed")])
def test_a_request_that_never_answered_names_no_heading(tmp_path, answered, state):
    """A heading says what a search looked under; a request that did not answer looked under nothing."""
    lib = _library(tmp_path, f"view-{state}.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    queries, _, _ = _expand(lib, tmp_path)
    plan = fast_search.build_plan(lib.store, lib.run, lib.store.scope(lib.rid), queries)
    if answered:
        _searched(lib, "pubmed", 0, status=answered)
    view = views.field_search_view(lib.store, lib.run, {"fast_path_search": plan, "source_routing": {}})
    (row,) = [row for row in view["rows"] if row["provider_id"] == "pubmed"]
    assert (row["state"], row["headings"]) == (state, None)
    lib.conn.close()


def test_the_planned_request_the_trace_reads_back_is_the_text_that_was_sent(tmp_path):
    """The PRISMA-S trace and the Methods box match a recorded search by its text, so the planned request names
    the expanded text; the plan's own word record keeps reading the compiled one."""
    lib = _library(tmp_path, "trace.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    queries, _, _ = _expand(lib, tmp_path)
    plan = fast_search.build_plan(lib.store, lib.run, lib.store.scope(lib.rid), queries)
    body = {"fast_path_search": plan, "compiled_queries": queries}
    (field,) = [row for row in fast_search.sent_plan(body) if row["arm"] == "field"]
    assert field["query_text"] == plan["field"][0]["query"]["mesh"]["query_text"]
    assert plan["field"][0]["query"]["query_text"] == _pubmed_query()["query_text"]
    # Every word of the plan is still read back as searched: the compiled text is what says what it carries.
    words = fast_search.plan_words(_vocabulary(), plan)
    assert [word["searched"] for word in words] == [True, True]
    lib.conn.close()


def test_each_lookup_is_counted_as_a_request_this_run_sent(tmp_path):
    lib = _library(tmp_path, "usage.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    before = (lib.store.run(lib.run["id"]).get("usage") or {}).get("provider_requests", 0)
    _expand(lib, tmp_path)
    after = (lib.store.run(lib.run["id"]).get("usage") or {}).get("provider_requests", 0)
    # The mapping request, and the verification's own search and summary.
    assert after - before == 3
    lib.conn.close()


def test_a_name_the_verification_request_did_not_carry_is_not_called_missing(tmp_path):
    """A name left out of the request was not checked, which is not the same as the database not holding it."""
    names = [f"heading {index}" for index in range(pubmed.MAX_MESH_NAMES + 3)]
    sent = {}

    async def fake_send(client, url, params, headers, description, *args, **kwargs):
        sent["term"] = params["term"]
        sent["retmax"] = params["retmax"]
        return None, SearchOutcome("failed", "rejected_not_executed", "SYNTHETIC", "keyless", error="SYNTHETIC")

    import deixis.providers.pubmed as module
    original = module.send
    module.send = fake_send
    try:
        result = asyncio.run(pubmed.mesh_descriptors(None, names))
    finally:
        module.send = original
    assert result["unchecked"] == names[pubmed.MAX_MESH_NAMES:]
    assert all(name not in sent["term"] for name in result["unchecked"])
    # One name can answer with its descriptor and its entry-term records, so the page holds more than the names.
    assert sent["retmax"] == pubmed.MAX_MESH_NAMES * pubmed.MESH_RECORDS_PER_NAME
    assert result["status"] == "failed"


def test_the_field_page_really_sends_the_expanded_query(tmp_path):
    lib = _library(tmp_path, "sent.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    queries, _, _ = _expand(lib, tmp_path)
    plan = fast_search.build_plan(lib.store, lib.run, lib.store.scope(lib.rid), queries)
    flow = ResearchFlow(SimpleNamespace(store=lib.store, clock=lib.clock, http=None,
                                        settings=Settings(data_dir=tmp_path / "data"), local_embedder=None))
    fast_path.enter_stage(lib.store, lib.run, "search")
    sent = []

    async def send(run_id, connector, query, limit, page=None, **kwargs):
        sent.append((query["provider_id"], query["query_text"]))
        return SearchOutcome("completed", "rejected_not_executed", "SYNTHETIC", "keyless",
                             records=[ProviderRecord(provider_record_id="W1", title="SYNTHETIC", authors=[],
                                                     year=2026, venue=None, publication_type="article", doi=None,
                                                     landing_url=None, oa_pdf_url=None, oa_pdf_version=None,
                                                     version_label="publishedVersion", abstract="SYNTHETIC",
                                                     abstract_origin="provider_pubmed", identifiers={}, raw={})],
                             provider_total=1, next_cursor=None)

    flow._send_search = send
    asyncio.run(asyncio.wait_for(fast_search.execute(flow, lib.run, lib.store.scope(lib.rid), plan, False), 5))
    assert ("pubmed", plan["field"][0]["query"]["mesh"]["query_text"]) in sent
    lib.conn.close()


# --- the round-2 guards -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("translation", [
    '"A"[MeSH Terms] OR ("B"[MeSH Terms]',   # a group never closed
    '"A"[MeSH Terms]) OR x',                 # a group never opened
    '"A"[MeSH Terms] OR "b"[All Fields',     # an operand cut off
    '"A[MeSH Terms] OR "b"[All Fields]',     # a name never closed
])
def test_a_translation_that_is_not_whole_is_not_read_at_all(translation):
    """Half of a mapping is not a mapping: a text that does not parse says nothing about the phrase."""
    assert pubmed.mapped_heading(translation) is None


def test_a_lookup_waits_seconds_not_the_half_minute_a_search_page_may(tmp_path):
    """The lookups run inside the plan stage, whose whole share is seconds."""
    seen = {}

    async def fake_send(client, url, params, headers, description, *args, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        return None, SearchOutcome("timeout", "rejected_not_executed", "SYNTHETIC", "keyless", error="SYNTHETIC")

    import deixis.providers.pubmed as module
    original = module.send
    module.send = fake_send
    try:
        asyncio.run(pubmed.mesh_mapping(None, "SYNTHETIC"))
        assert seen["timeout"] == pubmed.MESH_TIMEOUT_SECONDS
        asyncio.run(pubmed.mesh_descriptors(None, ["a heading"]))
        assert seen["timeout"] == pubmed.MESH_TIMEOUT_SECONDS
    finally:
        module.send = original


def test_a_run_whose_plan_time_ran_out_searches_the_compiled_query(tmp_path):
    lib = _library(tmp_path, "deadline.sqlite", evidence_minimum=False)
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    flow, asked = _flow(lib, tmp_path)
    fast_path.enter_stage(lib.store, lib.run, "plan")
    lib.clock.advance(400)  # the stage's own soft deadline is seconds; this run is long past it
    queries = asyncio.run(flow._mesh_expansion(lib.run, lib.store.scope(lib.rid), _vocabulary(), _queries()))
    output = lib.store.existing_step(lib.run["id"], "mesh_expansion")["output"]
    assert output["reason"] == "plan_deadline" and asked == []
    assert next(query for query in queries if query["provider_id"] == "pubmed")["query_text"] == \
        _pubmed_query()["query_text"]
    lib.conn.close()


def test_a_name_whose_record_this_page_could_not_reach_is_unchecked_not_missing(tmp_path):
    """MeSH not holding a name and this page not reaching its record are different answers."""
    pages = iter([{"esearchresult": {"count": "900", "idlist": ["68000001"]}},
                  {"result": {"uids": ["68000001"],
                              "68000001": {"ds_recordtype": "descriptor", "ds_meshterms": ["Found Heading"],
                                           "ds_meshui": "D000001"}}}])

    class Reply:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    async def fake_send(client, url, params, headers, description, *args, **kwargs):
        return Reply(next(pages)), SearchOutcome("completed", "rejected_not_executed", "SYNTHETIC", "keyless")

    import deixis.providers.pubmed as module
    original = module.send
    module.send = fake_send
    try:
        result = asyncio.run(pubmed.mesh_descriptors(None, ["Found Heading", "Other Heading"]))
    finally:
        module.send = original
    assert result["verified"] == {"Found Heading": {"descriptor": "Found Heading", "mesh_ui": "D000001"}}
    assert result["missing"] == [] and result["unchecked"] == ["Other Heading"]


def test_the_trace_reads_the_sent_text_back_from_the_protocol_s_own_body(tmp_path):
    """The protocol keeps a stripped copy of each compiled query, which carries no expansion; the plan's own copy
    of the field query carries it, and that is where the sent text is read from."""
    lib = _library(tmp_path, "body.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    queries, _, _ = _expand(lib, tmp_path)
    plan = fast_search.build_plan(lib.store, lib.run, lib.store.scope(lib.rid), queries)
    # The body as `protocol.build_protocol` writes it: the compiled list holds no `mesh` key.
    stripped = [{"provider_id": query["provider_id"], "query_text": query["query_text"]} for query in queries]
    (field,) = [row for row in fast_search.sent_plan({"fast_path_search": plan, "compiled_queries": stripped})
                if row["arm"] == "field"]
    assert field["query_text"] == plan["field"][0]["query"]["mesh"]["query_text"]


def test_a_lookup_does_not_wait_out_a_rate_limit():
    """Its waits would be the person's, and the query it adds to is already compiled without it."""
    seen = {}

    async def fake_send(client, url, params, headers, description, *args, **kwargs):
        seen["retries"] = kwargs.get("max_rate_limit_retries")
        return None, SearchOutcome("rate_limited", "rejected_not_executed", "SYNTHETIC", "keyless",
                                   error="SYNTHETIC")

    import deixis.providers.pubmed as module
    original = module.send
    module.send = fake_send
    try:
        asyncio.run(pubmed.mesh_mapping(None, "SYNTHETIC"))
        assert seen["retries"] == 0
        asyncio.run(pubmed.mesh_descriptors(None, ["a heading"]))
        assert seen["retries"] == 0
    finally:
        module.send = original
