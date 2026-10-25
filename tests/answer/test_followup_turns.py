"""Follow-up questions (UI parity S22a, F17). SYNTHETIC records and the fake adapter: these tests show the workflow
(the passages actually sent are the allowlist, anchors located, fail-closed citations, no search, atomic publication,
the turn's own budget, pause and resume without a second call, model_mismatch, the not-answered path), not whether a
model answers a follow-up well.
"""

import asyncio
import json
from fastapi.testclient import TestClient
from deixis.domain import contracts
from deixis.workflow.answer import answer as fast_answer, followup
from fakes import FakeAdapter, valid_response
from helpers import make_pdf
from test_api_flow import app_for, create, session, wait_run


PAGES = [
    "SYNTHETIC. The release schedule uses a binary variable per time slot to decide when molecules are emitted.",
    "SYNTHETIC. Interference between symbols is bounded by a linear constraint on the emitted amount.",
    "SYNTHETIC. The bibliography lists unrelated works on acoustic modems and ocean sensing.",
]


QUESTION = "Which binary variable decides the release time slot?"


def upload(client, rid, name, pages):
    response = client.post(f"/api/researches/{rid}/uploads", files={"file": (name, make_pdf(pages), "application/pdf")})
    assert response.status_code == 201, response.text
    return response.json()["uploaded_source_version_id"]


def research(client, files=(("a.pdf", PAGES),)):
    rid = create(client, source_scope="attached")
    svids = [upload(client, rid, name, pages) for name, pages in files]
    return rid, svids


def revision(client, rid):
    return client.get(f"/api/researches/{rid}").json()["scope"]["revision"]


def ask(client, rid, question=QUESTION, key=None, expected=None):
    headers = {"Idempotency-Key": key} if key else {}
    return client.post(f"/api/researches/{rid}/followup-turns", headers=headers,
                       json={"question": question, "expected_scope_revision": expected or revision(client, rid)})


def answered(client, rid, question=QUESTION, statuses=("completed", "failed", "paused", "cancelled")):
    response = ask(client, rid, question)
    assert response.status_code == 202, response.text
    turn = response.json()
    wait_run(client, rid, turn["run"]["id"], statuses)
    return client.get(f"/api/researches/{rid}/followup-turns/{turn['id']}").json()


def step_inputs(app, run_id):
    return [json.loads(r[0]) for r in app.state.store.conn.execute(
        "SELECT payload_json FROM step_inputs WHERE run_id = ? ORDER BY attempt", (run_id,))]


def test_a_follow_up_is_answered_from_the_passages_sent_and_cites_located_anchors(tmp_path):
    adapter = FakeAdapter()
    app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid, (svid,) = research(client)
        turn = answered(client, rid)
        assert turn["status"] == "answered" and turn["run"]["status"] == "completed"
        assert turn["question"] == QUESTION and turn["stale_scope"] is False
        (payload,) = step_inputs(app, turn["run"]["id"])
        # The turn's question replaces the research question in this StepInput only.
        assert payload["task_type"] == "followup_answer" and payload["question"]["text"] == QUESTION
        assert payload["skill_files"] == ["SKILL.md", "followup.md"]
        assert payload["budget"]["max_model_calls"] == followup.CALLS
        sent = [p["passage_id"] for p in payload["passages"]]
        # The allowlist is exactly the passages and sources sent in this call, and it is stored with its StepInput.
        assert payload["allowlist"]["passage_ids"] == sent and payload["allowlist"]["source_ids"] == [svid]
        assert turn["passages_given"] == len(sent) and turn["passages_considered"] >= len(sent)
        # The live steps read the stored step rows: the selection's count is the call's allowlist (UI parity S22b).
        assert turn["progress"] == {"passages_selected": len(sent), "answer_step": "succeeded",
                                    "more_passages": None, "more_step": None,
                                    "more_error": None}
        selection = app.state.store.existing_step(turn["run"]["id"], followup.SELECTION_KEY)["output"]
        assert selection["passage_ids"] == sent and selection["basis"] == "included_works"
        # The page naming the binary variable ranks first: the lexical ranking matched the turn's words.
        assert "binary variable" in payload["passages"][0]["text"]
        (claim,) = turn["answer"]["claims"]
        (citation,) = claim["citations"]
        assert citation["passage_id"] == sent[0] and citation["source_version_id"] == svid
        assert citation["anchor_text"] and citation["anchor_match"] == "exact"
        assert citation["anchor_text"] in app.state.store.passage(sent[0])["text"]
        # The follow-up answer is not the research's answer, and no search ran.
        view = client.get(f"/api/researches/{rid}").json()
        assert view["answers"] == [] and view["search_runs"] == []
        assert [t["id"] for t in client.get(f"/api/researches/{rid}/followup-turns").json()] == [turn["id"]]


def test_an_invented_locator_or_unlocatable_anchor_fails_closed(tmp_path):
    def invents(si):
        draft = json.loads(valid_response(si))
        if si["task_type"] == "followup_answer":
            draft["claims"][0]["text"] = "Equation 4 on page 12 proves the slot schedule is optimal."
            draft["citation_anchors"][0]["quote"] = "a sentence that is in no passage at all"
        return json.dumps(draft)

    adapter = FakeAdapter(invents)
    app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        turn = answered(client, rid)
        assert len(adapter.calls) == 2  # the call and its one repair, then it stops; no second round follows
        assert turn["status"] == "unverified_draft" and turn["answer"] is None
        assert {i["code"] for i in turn["issues"]} == {"locator_in_claim_text", "anchor_not_in_passage"}
        assert app.state.store.conn.execute("SELECT COUNT(*) FROM followup_turn_links").fetchone()[0] == 0


def test_a_repair_publishes_once_the_anchor_locates(tmp_path):
    calls = []

    def first_misquotes(si):
        calls.append(si["task_type"])
        draft = json.loads(valid_response(si))
        if len(calls) == 1:
            draft["citation_anchors"][0]["quote"] = "a sentence that is in no passage at all"
        return json.dumps(draft)

    app = app_for(tmp_path, FakeAdapter(first_misquotes))
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        turn = answered(client, rid)
        assert calls == ["followup_answer", "followup_answer"] and turn["status"] == "answered"
        assert turn["answer"]["claims"][0]["citations"][0]["anchor_text"]


def test_pause_during_the_call_publishes_on_resume_without_a_second_call(tmp_path):
    holder = {}

    def responder(si):
        if si["task_type"] == "followup_answer" and not holder.get("paused"):
            holder["paused"] = True
            holder["app"].state.store.update_run(si["run_id"], event="run_pause_requested", status="pause_requested",
                                                 pause_reason="user_requested")
        return valid_response(si)

    adapter = FakeAdapter(responder)
    holder["app"] = app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        response = ask(client, rid)
        turn = response.json()
        _, run = wait_run(client, rid, turn["run"]["id"])
        assert (run["status"], run["pause_reason"]) == ("paused", "user_requested")
        paused = client.get(f"/api/researches/{rid}/followup-turns/{turn['id']}").json()
        assert paused["status"] == "pending" and paused["passages_given"] is None
        # While unpublished the turn's steps still say what is stored: the selection and the finished call.
        sent = step_inputs(app, run["id"])[0]["passages"]
        assert paused["progress"] == {"passages_selected": len(sent), "answer_step": "succeeded",
                                    "more_passages": None, "more_step": None,
                                    "more_error": None}
        assert client.post(f"/api/runs/{run['id']}/resume").status_code == 200
        wait_run(client, rid, run["id"])
        turn = client.get(f"/api/researches/{rid}/followup-turns/{turn['id']}").json()
        assert turn["status"] == "answered" and len(adapter.calls) == 1


def test_output_from_another_model_is_recorded_but_not_published(tmp_path):
    adapter = FakeAdapter(resolved_model="some-other-model")
    app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        turn = answered(client, rid)
        assert (turn["run"]["status"], turn["run"]["pause_reason"]) == ("paused", "model_mismatch")
        assert turn["status"] == "pending" and turn["answer"] is None and len(adapter.calls) == 1


def test_basis_answer_input_uses_the_frozen_answer_evidence_and_drops_a_later_exclusion(tmp_path):
    from test_fast_path_answer import answer_run, cutoff, setup, user
    lib = setup(tmp_path, n=3)
    cutoff(lib)
    run = answer_run(lib)
    asyncio.run(fast_answer.answer(lib.flow, run, lib.store.scope(lib.rid)))
    plan = lib.store.existing_step(run["id"], fast_answer.INPUT)["output"]
    assert plan["passage_ids"]
    frozen = followup.pool(lib.store, lib.rid, 1)
    assert frozen["basis"] == "answer_input" and frozen["answer_run_id"] == run["id"]
    assert set(frozen["sources"]) == {i["source_version_id"] for i in plan["items"]}
    user(lib, lib.sources[0], "excluded")
    assert lib.sources[0] not in followup.pool(lib.store, lib.rid, 1)["sources"]


def exclude(store, rid, svid, state="excluded"):
    version = store.conn.execute("SELECT version FROM selections WHERE research_id = ? AND source_version_id = ?",
                                 (rid, svid)).fetchone()[0]
    store.set_user_selection(rid, svid, state, version, "SYNTHETIC person choice")


def asset_of(store, svid):
    return store.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ? AND removed_at IS NULL",
                              (svid,)).fetchone()[0]


def during_call(change):
    """A responder that lets `change(store, si)` happen while the follow-up call is out, then answers validly."""
    holder = {}

    def respond(si):
        if si["task_type"] == "followup_answer" and not holder.get("done"):
            holder["done"] = True
            change(holder["app"].state.store, si)
        return valid_response(si)
    return holder, respond


def test_a_selection_change_during_the_call_stops_publication(tmp_path):
    def change(store, si):
        svid = store.conn.execute("SELECT source_version_id FROM corpus_memberships WHERE research_id = ?",
                                  (si["research_id"],)).fetchone()[0]
        exclude(store, si["research_id"], svid)

    holder, respond = during_call(change)
    holder["app"] = app = app_for(tmp_path, FakeAdapter(respond))
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        turn = answered(client, rid)
        assert (turn["run"]["status"], turn["run"]["pause_reason"]) == ("failed", followup.SELECTION_CHANGED)
        assert turn["status"] == "pending" and turn["answer"] is None
        store = app.state.store
        assert store.conn.execute("SELECT COUNT(*) FROM followup_turn_links").fetchone()[0] == 0
        assert not store.conn.execute("SELECT 1 FROM events WHERE type = 'followup_answered'").fetchone()


def test_a_source_the_person_set_pending_leaves_the_pool(tmp_path):
    from test_fast_path_answer import answer_run, cutoff, setup, user
    lib = setup(tmp_path, n=3)
    cutoff(lib)
    run = answer_run(lib)
    asyncio.run(fast_answer.answer(lib.flow, run, lib.store.scope(lib.rid)))
    frozen = followup.pool(lib.store, lib.rid, 1)
    assert lib.sources[1] in frozen["sources"]
    user(lib, lib.sources[1], "pending")  # a user selection in state `pending`, after the answer froze its input
    later = followup.pool(lib.store, lib.rid, 1)
    assert lib.sources[1] not in later["sources"] and set(later["sources"]) < set(frozen["sources"])
    assert followup.changed(lib.store, lib.rid, frozen) == followup.SELECTION_CHANGED


def test_the_conversation_carries_the_latest_answers_claims_as_text_only(tmp_path):
    from test_fast_path_answer import answer_run, cutoff, setup
    lib = setup(tmp_path, n=3)
    cutoff(lib)
    run = answer_run(lib)
    asyncio.run(fast_answer.answer(lib.flow, run, lib.store.scope(lib.rid)))
    texts = [r[0] for r in lib.store.conn.execute(
        "SELECT c.text FROM claims c JOIN answers a ON a.id = c.answer_id WHERE a.research_id = ?"
        " AND a.status = 'structurally_valid' ORDER BY c.ordinal", (lib.rid,))]
    assert texts
    context = followup.conversation(lib.store, lib.rid, "SYNTHETIC research question", {"id": "none", "created_at": "9999"})
    assert context == {"research_question": "SYNTHETIC research question", "latest_answer": texts, "earlier_turns": [],
                       "evidence_table": []}


def test_a_step_input_for_another_task_may_not_carry_a_conversation():
    from test_followup_contract import STEP_INPUTS
    si = STEP_INPUTS["K_followup_answer"]
    assert not contracts.check_step_input(si)
    without = {k: v for k, v in si.items() if k != "conversation"}
    assert any(i.code == "conversation_mismatch" for i in contracts.check_step_input(without))


def table_rows(spec):
    """SYNTHETIC `_table_values` rows: (cell id, column name, passage id) per cited passage."""
    return [{"cell_id": cell, "column_name": column, "passage_id": pid} for cell, column, pid in spec]


def work_rows(spec):
    """SYNTHETIC `_table_values` rows: (cell id, work id, passage id) per cited passage."""
    return [{"cell_id": c, "work_id": w, "source_version_id": f"sv_{c}", "passage_id": pid} for c, w, pid in spec]


def test_the_selection_puts_one_passage_per_work_first_and_ranks_the_rest(tmp_path, monkeypatch):
    """D64 through `_selection`: the answer's passage first; its work adds no table passage; a reserve work, then one
    version of a work held in two versions, then the next work, up to half the limit; the question's own ranking fills
    the other half. SYNTHETIC records; the table rows are given directly."""
    from types import SimpleNamespace
    from deixis.storage import db
    from deixis.storage.db import new_id, now, transaction
    from deixis.workflow.run.store import Store
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("SYNTHETIC routing question", "attached", "quick", [], "fake", "fake-model", None)
    works, text = {}, {}
    for n in range(6):
        sv = store.create_upload_source(f"SYNTHETIC work {n}")
        works[n] = [sv]
    second = new_id("srv")
    with transaction(conn):
        conn.execute("INSERT INTO source_versions (id, work_id, title, origin, version_label, created_at)"
                     " VALUES (?, ?, 'SYNTHETIC work 0', 'provider', 'submittedVersion', ?)",
                     (second, store.source(works[0][0])["work_id"], now()))
        works[0].append(second)
        for n, svs in works.items():
            for sv in svs:
                body = (f"SYNTHETIC work {n} routing summary.", f"SYNTHETIC work {n} second page.")[:2 if n == 1 else 1] if n != 5 else (
                    "SYNTHETIC holding time is computed from depth.", "SYNTHETIC holding time shrinks with depth.")
                text[sv] = [store._insert_passage(sv, None, "abstract", None, None, "provider", None, None, t) for t in body]
    for svs in works.values():
        for sv in svs:
            store.add_to_corpus(rid, sv, "user_upload", selection_state="included", selection_origin="user")
    work = {n: store.source(svs[0])["work_id"] for n, svs in works.items()}
    p = {n: text[works[n][0]][0] for n in works}
    value = {"title": "SYNTHETIC work", "year": 2020, "options_json": None, "value_json": json.dumps({"text": "depth-based"}),
             "column_name": "Routing family"}
    cites = p | {1: text[works[1][0]][1]}  # the answer cites work 1's first passage, its table value the second
    rows = [value | {"cell_id": f"c{n}", "work_id": work[n], "source_version_id": works[n][0], "passage_id": cites[n]}
            for n in (4, 0, 1, 2, 3)]
    rows.insert(2, value | {"cell_id": "c0b", "work_id": work[0], "source_version_id": second,
                            "passage_id": text[second][0]})
    monkeypatch.setattr(followup, "_table_values", lambda store, rid: rows)
    sources = {sv: text[sv] for n, svs in works.items() if n != 4 for sv in svs}
    frozen = {"sources": sources, "reserve": {works[4][0]: text[works[4][0]]}, "priority": [p[1]],
              "basis": "included_works", "answer_run_id": None}
    run = store.create_run(rid, "followup_answer", {"max_followup_passages": 8}, None)

    async def no_semantic(*args, **kwargs):
        return None
    flow = SimpleNamespace(store=store, _semantic_ranking=no_semantic)
    selected = asyncio.run(followup._selection(flow, store.run(run["id"]), store.scope(rid), "holding time", frozen))
    chosen = selected["passage_ids"]
    assert chosen[:4] == [p[1], p[4], p[0], p[2]] and selected["from_priority"] == 4
    assert text[second][0] not in chosen[:4] and cites[1] not in chosen[:4] and set(text[works[5][0]]) <= set(chosen) and len(chosen) == 8


def first_answer(client, rid):
    run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
    wait_run(client, rid, run["id"], ("completed",))
    return [a for a in client.get(f"/api/researches/{rid}").json()["answers"] if a["status"] == "structurally_valid"]


def classify_all(si):
    """SYNTHETIC: a follow-up output that classifies every source sent by its first passage (D66). A source whose
    first passage names "depth" is depth-based, "vector" vector-based, both both (as an interpretation); another is
    ambiguous."""
    draft = json.loads(valid_response(si))
    draft["claims"], draft["citation_anchors"] = [], []
    first: dict[str, dict] = {}
    for p in si["passages"]:
        first.setdefault(p["source_id"], p)
    records = []
    for p in first.values():
        quote = " ".join(p["text"].split())[:120]
        groups = [g for g, word in (("Depth-based", "depth"), ("Vector-based", "vector")) if word in p["text"]]
        records.append({"passage_id": p["passage_id"], "status": "classified" if groups else "ambiguous",
                        "memberships": [{"group": g, "passage_id": p["passage_id"], "quote": quote,
                                         "support_type": "analyst_inference" if len(groups) > 1 else "source_stated"}
                                        for g in groups],
                        "note": None if groups else "SYNTHETIC: the passage names neither."})
    draft["work_classifications"] = records
    return json.dumps(draft)


def test_a_counting_follow_up_is_counted_by_the_application_with_a_citation_per_work(tmp_path):
    """D66 end to end: the model classifies works; the application counts the distinct works per group, a hybrid in
    both, shows each work with its citation and the ambiguous one by its note, and a later turn reads the counts as
    context. SYNTHETIC records and the fake adapter."""
    files = (("a.pdf", ["SYNTHETIC. The protocol forwards by depth toward the surface sinks."]),
             ("b.pdf", ["SYNTHETIC. The protocol forwards inside a vector pipe from source to sink."]),
             ("c.pdf", ["SYNTHETIC. A hybrid uses depth and a vector pipe together for forwarding."]),
             ("d.pdf", ["SYNTHETIC. The bibliography lists unrelated works on acoustic modems."]))
    adapter = FakeAdapter(lambda si: classify_all(si) if "How many" in si["question"]["text"] else valid_response(si))
    app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client, files)
        turn = answered(client, rid, "How many works are depth-based and how many vector-based?")
        assert turn["status"] == "answered", turn.get("validation")
        groups = {g["label"]: g for g in turn["answer"]["work_groups"]["groups"]}
        assert {label: g["count"] for label, g in groups.items()} == {"Depth-based": 2, "Vector-based": 2}
        assert all(w["citations"] and w["citations"][0]["anchor_text"] for g in groups.values() for w in g["works"])
        # The hybrid's memberships are interpretations: marked on the work and on its citation, the others not.
        marked = {w["title"]: (w["inference"], w["citations"][0]["support_type"]) for w in groups["Depth-based"]["works"]}
        assert sorted(marked.values()) == [(False, "source_stated"), (True, "analyst_inference")]
        summary = turn["answer"]["work_groups"]
        assert [w["note"] for w in summary["ambiguous"]] == ["SYNTHETIC: the passage names neither."]
        assert summary["classified_works"] == 3 and summary["sent_works"] == 4 and summary["included_works"] == 4
        assert summary["unclassified"] == [] and summary["table_not_sent"] == []
        later = answered(client, rid)
        (payload, *_) = step_inputs(app, later["run"]["id"])
        lines = payload["conversation"]["earlier_turns"][-1]["answer"]
        assert lines[0].startswith("Depth-based: 2 works (") and lines[1].startswith("Vector-based: 2 works (")
        assert lines[0].count(" [interpretation]") == 1 and lines[1].count(" [interpretation]") == 1
        assert lines[2].startswith("Not settled by their passages: ") and \
            lines[2].endswith(" - SYNTHETIC: the passage names neither.")
        assert lines[3] == ("Counted by the application from the passages sent: 3 of 4 works sent are in a group, of 4"
                            " included; 1 not settled by their passages; a work can be in more than one group.")


def test_work_groups_count_a_work_once_across_its_versions_and_name_table_works_not_sent(tmp_path, monkeypatch):
    """D66: two versions of one work in a group are one work; a work the table names but whose passages were not
    sent, and a sent work with no record, are listed apart. SYNTHETIC records."""
    from test_evidence_tables import make_lib
    lib = make_lib(tmp_path)  # one work in two versions: published and preprint
    other = lib.store.create_upload_source("SYNTHETIC other work")
    unsent = lib.store.create_upload_source("SYNTHETIC unsent work")
    with followup.transaction(lib.conn):
        extra = lib.store._insert_passage(other, None, "abstract", None, None, "provider", None, None, "SYNTHETIC other.")
    work = {sv: lib.store.source(sv)["work_id"] for sv in (lib.published, other, unsent)}
    monkeypatch.setattr(followup, "_table_works", lambda store, rid: [work[unsent], work[other]])
    payload = {"passages": [{"passage_id": lib.abstracts[lib.published], "source_id": lib.published},
                            {"passage_id": lib.abstracts[lib.preprint], "source_id": lib.preprint},
                            {"passage_id": extra, "source_id": other}]}

    def record(pid):
        return {"passage_id": pid, "status": "classified", "note": None,
                "memberships": [{"group": "Packets", "passage_id": pid, "quote": "x" * 12, "support_type": "source_stated"}]}
    frozen = followup.work_groups(lib.store, lib.rid, payload, {"work_classifications": [
        record(lib.abstracts[lib.published]), record(lib.abstracts[lib.preprint])]})
    (group,) = frozen["groups"]
    assert group["count"] == 1 and group["works"][0]["labels"] == ["w1.1", "w2.1"]
    assert frozen["unclassified"] == [work[other]] and frozen["table_not_sent"] == [work[unsent]]
    assert frozen["sent_works"] == 2 and frozen["classified_works"] == 1
    assert followup.work_groups(lib.store, lib.rid, payload, {"work_classifications": []}) is None
    # One version grouped, the other left open: the work is in the group and not listed as left open.
    open_version = {"passage_id": lib.abstracts[lib.preprint], "status": "ambiguous", "memberships": [], "note": "SYNTHETIC."}
    mixed = followup.work_groups(lib.store, lib.rid, payload, {"work_classifications": [
        record(lib.abstracts[lib.published]), open_version]})
    assert mixed["groups"][0]["count"] == 1 and mixed["ambiguous"] == []
    assert mixed["groups"][0]["works"][0]["note"] == "SYNTHETIC."  # the open version's note stays with the work
