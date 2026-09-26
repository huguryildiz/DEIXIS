"""The human queue, read and answered at the store (slice 16, D96).

Records, criteria and page texts are SYNTHETIC and from two fields (diffusion channel scheduling, greenhouse
irrigation). A reading run is written the way `flow._close_adjudication` writes one — two model steps with their
StepInputs and outputs, a proposal per part, a decision on the read version — without a model. Passing shows the queue
derives its rows and writes its answers as the slice says; it says nothing about whether a person finds the rows useful.
"""

import pytest

from deixis.domain.reason_codes import REASON_CODES
from deixis.domain.rules import RevisionConflict
from deixis.providers.common import ProviderRecord
from deixis.storage import db
from deixis.workflow import queue
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.store import NotASource, Store

FIELDS = {
    "channels": {
        "question": "SYNTHETIC which diffusion channel papers state a release model and its timing rule?",
        "topic": "diffusion channel scheduling",
        "parts": [{"name": "release model", "definition": "SYNTHETIC the paper states the release model it uses."},
                  {"name": "timing rule", "definition": "SYNTHETIC the paper states the rule that times a release."}],
        "phrases": [{"phrase": "release model", "part": "release model"},
                    {"phrase": "timing rule", "part": "timing rule"},
                    {"phrase": "molecule budget", "part": None}],
        "page": "SYNTHETIC the release model is a Poisson process with a fixed rate per slot.",
        "cue": "SYNTHETIC each transmitter applies a timing rule before the slot opens.",
    },
    "irrigation": {
        "question": "SYNTHETIC which greenhouse papers state a water balance and a scheduling threshold?",
        "topic": "greenhouse irrigation",
        "parts": [{"name": "water balance", "definition": "SYNTHETIC the paper states the water balance it uses."},
                  {"name": "threshold", "definition": "SYNTHETIC the paper states the threshold that starts a cycle."}],
        "phrases": [{"phrase": "water balance", "part": "water balance"},
                    {"phrase": "moisture threshold", "part": "threshold"},
                    {"phrase": "drip line", "part": None}],
        "page": "SYNTHETIC the water balance is written per bench with a daily drainage term.",
        "cue": "SYNTHETIC a cycle starts when the moisture threshold of the slab is crossed.",
    },
}
BUDGET = {"max_model_calls": 4, "max_provider_requests": 4, "max_candidates": 50, "max_answer_passages": 8}


@pytest.fixture
def store(tmp_path):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    yield Store(connection)
    connection.close()


def body(field, question=None):
    return {"schema": "deixis.protocol.v1", "search_workflow": "sw", "question": question or field["question"],
            "steering": None, "inclusion_criterion": "SYNTHETIC the paper states both parts.",
            "criterion_parts": field["parts"],
            "cue_phrases": [dict(row, runs=[1, 2]) for row in field["phrases"]], "exclusion_title_words": ["survey"],
            "criterion_origin": {"origin": "model", "base_run": 1, "runs_ok": [1, 2],
                                 "dropped_exclusion_title_words": [], "sought_term_in_criterion": True}}


def provider_record(record_id, title, doi, version_label="publishedVersion", merge_by_doi=True, **identifiers):
    return ProviderRecord(
        provider_record_id=record_id, title=title, authors=[], year=2026, venue=None, publication_type="article",
        doi=doi, landing_url=None, oa_pdf_url=None, oa_pdf_version=None, version_label=version_label, abstract=None,
        abstract_origin=None, identifiers=identifiers, raw={}, merge_by_doi=merge_by_doi)


class Lib:
    """One SYNTHETIC `sw` research and the rows a reading run would have left in it."""

    def __init__(self, store, field="channels", workflow="sw"):
        self.store, self.field = store, FIELDS[field]
        self.ds = DecisionStore(store)
        self.rid = store.create_research(self.field["question"], "academic", "standard", ["openalex", "arxiv"],
                                         "fake", "m", "en", search_workflow=workflow)
        self.run = self.new_run("discovery")
        store.freeze_protocol(self.rid, 1, body(self.field))
        self.n = 0
        self.reading: str | None = None

    def new_run(self, kind):
        """A run of this research, closed at once: the rows it holds are written here, not by the worker."""
        run = self.store.create_run(self.rid, kind, BUDGET, None)["id"]
        self.store.update_run(run, status="completed")
        return run

    @property
    def parts(self):
        return [part["name"] for part in self.field["parts"]]

    def search(self, records, provider="openalex", query="q"):
        self.n += 1
        revision = self.store.research(self.rid)["current_scope_revision"]
        step = self.store.step(self.run, f"search:{self.n}", f"provider_search:{provider}")
        self.store.record_search(
            dict(research_id=self.rid, run_id=self.run, step_id=step["id"], scope_revision=revision, provider=provider,
                 query_text=query, request_description="GET test", access_mode="keyless", status="completed",
                 delivery_class=None, result_count=len(records), provider_total=len(records), page_limit=25,
                 error_json=None, raw_payload_path=None),
            provider, records, None, step["id"], "succeeded", step_output={"status": "completed"})

    def work(self, query="q"):
        """One published record heading its own work."""
        self.search([provider_record(f"W{self.n + 1}", f"SYNTHETIC {self.field['topic']} study {self.n + 1}",
                                     f"10.9999/synth.{self.n + 1}")], query=query)
        return self.store.find_source_by_identifier("openalex", f"W{self.n}")

    def preprint(self, doi):
        """An arXiv preprint whose published version carries `doi`; it heads its work until that version is found."""
        self.search([provider_record(f"2601.{self.n + 1:05d}v1", f"SYNTHETIC preprint of {self.field['topic']}",
                                     f"10.48550/arxiv.2601.{self.n + 1:05d}", version_label="submittedVersion",
                                     merge_by_doi=False, published_doi=doi)], provider="arxiv")
        return self.store.find_source_by_identifier("arxiv", f"2601.{self.n:05d}v1")

    def published(self, doi):
        self.search([provider_record(f"W{self.n + 1}", f"SYNTHETIC {self.field['topic']} published", doi)])
        return self.store.find_source_by_identifier("openalex", f"W{self.n}")

    def work_of(self, svid):
        return self.store.source(svid)["work_id"]

    def head(self, svid):
        return self.store.work_heads(self.rid)[self.work_of(svid)]

    def text(self, svid, pages):
        """A PDF in use for this record, one passage per page; returns the file's identifier."""
        asset, version = db.new_id("ast"), "pymupdf-synthetic"
        with db.transaction(self.store.conn):
            # A record has one PDF in use; a new one replaces it (D45).
            self.store.conn.execute("UPDATE source_assets SET removed_at = ?, removal_reason = 'replaced'"
                                    " WHERE source_version_id = ? AND removed_at IS NULL", (db.now(), svid))
            self.store.conn.execute(
                "INSERT INTO source_assets (id, source_version_id, sha256, byte_size, media_type, storage_path,"
                " retrieved_at, origin, extraction_status, extraction_version, page_count, retrieved_from)"
                " VALUES (?, ?, ?, 20, 'application/pdf', 'synthetic.pdf', ?, 'download', 'succeeded', ?, ?, ?)",
                (asset, svid, asset.ljust(64, "0")[:64], db.now(), version, len(pages), "https://example.org/x.pdf"))
            for page, text in enumerate(pages, start=1):
                self.store._insert_passage(svid, asset, "pdf_page", page, None, None, None, version, text)
        return asset

    def rank(self, svids, chain=False):
        run = self.new_run("discovery")
        key = "chain_ranking" if chain else "ranking"
        step = self.store.step(run, key, f"code:{key}")
        self.store.finish_step(step["id"], "succeeded", output={})
        self.ds.save_ranks(step["id"], self.rid, [{"source_version_id": svid, "signal": "inspection", "rank": i + 1,
                                                   "available": 1} for i, svid in enumerate(svids)])

    def reading_run(self):
        revision = self.store.research(self.rid)["current_scope_revision"]
        if self.reading is None or self.store.run(self.reading)["scope_revision"] != revision:
            self.reading = self.new_run("fulltext_adjudication")
        return self.reading

    def read(self, svid, code, labels=None, verified=None, quotes=None, shown=((1,), (1,)), head=None):
        """Write one reading of `svid` the way the reading run does, and the code it settled on.

        `labels` maps a part to its two runs' labels (every part `present` by default), `verified` a part to its two
        runs' quote checks, `quotes` a part to its two quotes, and `shown` the pages each run was shown.
        """
        labels = labels or {name: ("present", "present") for name in self.parts}
        run = self.reading_run()
        head = head or self.head(svid)
        pages = self.store.page_texts(svid)
        steps = []
        for run_no in (1, 2):
            step = self.store.step(run, f"fulltext_adjudication:{head}:{run_no}", "model:fulltext_adjudication")
            passages = [{"passage_id": p["id"], "locator": {"physical_page": p["physical_page"]}}
                        for p in self.store.passages_for(svid)
                        if p["kind"] == "pdf_page" and p["physical_page"] in shown[run_no - 1]]
            sid = db.new_id("sti")
            self.store.insert_step_input(step["id"], self.rid, run, 0,
                                         {"step_input_id": sid, "task_type": "fulltext_adjudication",
                                          "scope_revision": 1, "skill_package_hash": "sha256:synthetic",
                                          "passages": passages}, "b", "d", "m", {})
            parts = []
            for name, pair in labels.items():
                label = pair[run_no - 1]
                quote = ((quotes or {}).get(name) or (pages.get(1, ""), pages.get(1, "")))[run_no - 1]
                ok = (verified or {}).get(name, (True, True))[run_no - 1]
                parts.append({"part": name, "label": label, "quote": quote if label == "present" else "",
                              "passage_id": passages[0]["passage_id"] if label == "present" and passages else None,
                              "rationale": f"SYNTHETIC run {run_no} on {name}."})
                self.ds.add_proposal(self.rid, svid, "fulltext", step["id"], run_no, label, criterion_part=name,
                                     quote=quote if label == "present" else None,
                                     quote_verified=ok if label == "present" else False,
                                     quote_passage_id=passages[0]["passage_id"] if label == "present" and passages else None,
                                     quote_page=shown[run_no - 1][0] if label == "present" and ok else None)
            self.store.finish_step(step["id"], "succeeded", output={"result": {"parts": parts}, "step_input_id": sid})
            steps.append(step["id"])
        decision = self.ds.record(self.rid, svid, code, step_id=steps[-1])
        self.ds.derive_selection(self.rid, self.work_of(svid))
        return decision

    def unconfirmed(self, svid):
        """A PDF held back by the identity check, as the reading run's plan writes it."""
        run = self.reading_run()
        step = self.store.step(run, "adjudication_plan", "code:adjudication_plan")
        self.store.finish_step(step["id"], "succeeded", output={})
        return self.ds.record(self.rid, svid, "pdf_identity_unconfirmed", step_id=step["id"])

    def rows(self):
        return queue.queue_rows(self.store, self.rid)

    def row(self, svid):
        return next(row for row in self.rows()["rows"] if row["source_version_id"] == svid)

    def selection(self, svid):
        row = self.store.conn.execute("SELECT state, origin, version FROM selections WHERE research_id = ?"
                                      " AND source_version_id = ?", (self.rid, svid)).fetchone()
        return (row["state"], row["origin"])

    def selection_version(self, svid):
        return self.store.conn.execute("SELECT version FROM selections WHERE research_id = ? AND source_version_id = ?",
                                       (self.rid, svid)).fetchone()[0]

    def list_edit(self, svid, state):
        return self.store.set_user_selection(self.rid, svid, state, self.selection_version(svid), "SYNTHETIC list edit")

    def revise(self):
        research = self.store.research(self.rid)
        self.store.revise_scope(self.rid, research["version"], self.field["question"] + " (revised)", None)

    def code(self, svid):
        return (self.ds.current(self.rid, svid, "fulltext") or {}).get("reason_code")


def partial(lib):
    """Labels for `part_without_evidence`: the first part present in both runs, the second in neither."""
    first, second = lib.parts
    return {first: ("present", "present"), second: ("absent", "absent")}


def queued(lib, code="part_without_evidence"):
    svid = lib.work()
    lib.text(svid, [lib.field["page"], lib.field["cue"]])
    lib.read(svid, code, labels=partial(lib) if code == "part_without_evidence" else None)
    return svid


# ---- which works are rows ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("field", sorted(FIELDS))
def test_each_human_queue_code_is_one_row_per_work_and_no_other_code_is(store, field):
    lib = Lib(store, field)
    routed = [code for code, entry in REASON_CODES.items() if entry.next_step == "human_queue"]
    assert set(routed) == set(queue.QUEUE_CODES) and len(routed) == 6
    by_code = {}
    for code in routed:
        svid = lib.work()
        lib.text(svid, [lib.field["page"]])
        if code == "pdf_identity_unconfirmed":
            lib.unconfirmed(svid)
        else:
            lib.read(svid, code, labels=partial(lib) if code == "part_without_evidence" else None)
        by_code[code] = svid
    for code in ("all_parts_verified", "criterion_absent", "no_fulltext", "text_unreadable", "not_read_yet"):
        svid = lib.work()
        lib.ds.record(lib.rid, svid, code)
    for code in ("runs_agree_candidate", "abstract_not_read", "runs_agree_out_of_scope"):
        lib.ds.record(lib.rid, lib.work(), code)
    decided = queued(lib)
    lib.ds.record(lib.rid, decided, "human_include")
    # Two versions of one work, both routed to the queue, are one row, named on the head.
    published = lib.published("10.9999/synth.two")
    preprint = lib.preprint("10.9999/synth.two")
    for svid in (published, preprint):
        lib.text(svid, [lib.field["page"]])
        lib.read(svid, "fulltext_runs_disagree", labels={name: ("present", "absent") for name in lib.parts},
                 head=published)
    found = lib.rows()
    assert sorted(row["reason_code"] for row in found["rows"]) == sorted(routed + ["fulltext_runs_disagree"])
    assert {row["source_version_id"] for row in found["rows"]} == set(by_code.values()) | {published}
    assert len({row["work_id"] for row in found["rows"]}) == len(found["rows"])
    assert found["counts"]["open"] == 7 and found["counts"]["decided"] == {"human_include": 1}
    assert found["order"] == "fused_rank"


def test_a_work_whose_selection_the_user_set_is_not_in_the_queue(store):
    lib = Lib(store)
    listed, shown = queued(lib), queued(lib)
    lib.list_edit(listed, "excluded")
    found = lib.rows()
    assert [row["source_version_id"] for row in found["rows"]] == [shown]
    assert found["counts"]["user_selected"] == 1 and found["counts"]["open"] == 1


def test_rows_are_ordered_by_fused_rank_with_chained_works_after_keyword_works(store):
    lib = Lib(store, "irrigation")
    first, second, unranked = queued(lib), queued(lib), queued(lib)
    chained = lib.work(query="chain:backward:W1")
    lib.text(chained, [lib.field["page"]])
    lib.read(chained, "fulltext_runs_disagree", labels={name: ("present", "absent") for name in lib.parts})
    lib.rank([second, first])
    lib.rank([chained], chain=True)
    rows = lib.rows()["rows"]
    assert [row["source_version_id"] for row in rows] == [second, first, chained, unranked]
    assert [row["place"] for row in rows] == [1, 2, 3, None]
    assert [row["arm"] for row in rows] == ["keyword", "keyword", "chain", "keyword"]


# ---- what each row asks -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("field", sorted(FIELDS))
def test_the_row_question_names_the_first_part_the_runs_did_not_settle(store, field):
    lib = Lib(store, field)
    first, second = lib.parts
    disagree = lib.work()
    lib.text(disagree, [lib.field["page"]])
    lib.read(disagree, "fulltext_runs_disagree", labels={first: ("present", "present"), second: ("present", "unclear")})
    unverified = lib.work()
    lib.text(unverified, [lib.field["page"]])
    lib.read(unverified, "include_quote_unverified", verified={first: (True, False), second: (False, True)})
    identity = lib.work()
    lib.text(identity, [lib.field["page"]])
    lib.unconfirmed(identity)
    rows = {row["source_version_id"]: row for row in lib.rows()["rows"]}
    assert rows[disagree]["kind"] == "choose_run"
    assert rows[disagree]["question"] == {"part": second, "definition": lib.field["parts"][1]["definition"]}
    assert rows[unverified]["kind"] == "confirm_quote" and rows[unverified]["question"]["part"] == first
    assert rows[identity]["kind"] == "confirm_pdf" and rows[identity]["question"] is None


def test_part_without_evidence_splits_into_confirm_absent_and_find_part(store):
    lib = Lib(store)
    first, second = lib.parts
    absent = queued(lib)
    open_part = lib.work()
    lib.text(open_part, [lib.field["page"]])
    lib.read(open_part, "part_without_evidence", labels={first: ("present", "present"), second: ("absent", "unclear")})
    rows = {row["source_version_id"]: row for row in lib.rows()["rows"]}
    assert rows[absent]["kind"] == "confirm_absent" and rows[absent]["question"]["part"] == second
    assert rows[open_part]["kind"] == "find_part" and rows[open_part]["question"]["part"] == second


def test_the_closest_passage_is_searched_only_on_the_pages_that_run_was_shown(store):
    lib = Lib(store)
    first, second = lib.parts
    svid = lib.work()
    near = "SYNTHETIC the release model is a Poisson proces with a fixed rate per slot."
    lib.text(svid, ["SYNTHETIC an unrelated page about antenna gain and cable loss.", lib.field["page"]])
    lib.read(svid, "include_quote_unverified", quotes={first: (near, near), second: (near, near)},
             verified={first: (False, False), second: (True, True)}, shown=((1,), (2,)))
    detail = queue.row_detail(store, lib.rid, svid)["detail"]
    by_run = {run["run_no"]: {part["part"]: part for part in run["parts"]} for run in detail["runs"]}
    assert detail["runs"][0]["shown_pages"] == [1] and detail["runs"][1]["shown_pages"] == [2]
    assert by_run[1][first]["closest"] is None
    assert by_run[1][first]["closest_note"] == "no close text on the shown pages"
    assert by_run[2][first]["closest"]["page"] == 2 and by_run[2][first]["closest"]["kind"] == "fuzzy"
    assert "closest" not in by_run[2][second]  # a verified quote needs no nearest text
    assert by_run[1][first]["rationale"] == f"SYNTHETIC run 1 on {first}."


@pytest.mark.parametrize("field", sorted(FIELDS))
def test_cue_sentences_come_with_their_pages_or_the_row_says_none_were_found(store, field):
    lib = Lib(store, field)
    unassigned = lib.field["phrases"][2]["phrase"]
    with_cue = lib.work()
    lib.text(with_cue, [lib.field["page"] + f" A {unassigned} is kept.", "SYNTHETIC methods page.", lib.field["cue"]])
    lib.read(with_cue, "part_without_evidence", labels=partial(lib))
    without = lib.work()
    lib.text(without, [lib.field["page"] + f" A {unassigned} is kept."])
    lib.read(without, "part_without_evidence", labels=partial(lib))
    cues = queue.row_detail(store, lib.rid, with_cue)["detail"]["cues"]
    page_three = next(p["id"] for p in store.passages_for(with_cue) if p["physical_page"] == 3)
    assert cues["sentences"] == [{"page": 3, "sentence": lib.field["cue"], "passage_id": page_three,
                                  "rendition": False}]  # a PDF of its own, not Europe PMC's drawn text (SW21)
    assert cues["total"] == 1
    assert cues["note"] is None
    none = queue.row_detail(store, lib.rid, without)["detail"]["cues"]
    # The unassigned phrase is on the page, but it belongs to no part, so it is no cue for this one.
    assert none["sentences"] == [] and none["total"] == 0 and none["note"] == "no cue found"


def test_reading_the_queue_opens_no_step_and_writes_nothing(store):
    lib = Lib(store)
    svid = queued(lib)
    identity = lib.work()
    lib.text(identity, [lib.field["page"]])
    lib.unconfirmed(identity)
    tables = [row[0] for row in store.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]

    def snapshot():
        return {table: store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}

    before, changes = snapshot(), store.conn.total_changes
    queue.queue_rows(store, lib.rid)
    queue.row_detail(store, lib.rid, svid)
    queue.row_detail(store, lib.rid, identity)
    queue.verified_records(store, lib.rid)
    queue.queue_counts(store, lib.rid)
    assert snapshot() == before and store.conn.total_changes == changes


# ---- answering -----------------------------------------------------------------------------------------------------

def test_not_sure_and_pdf_wrong_leave_the_work_pending_and_do_not_return_to_the_queue(store):
    lib = Lib(store, "irrigation")
    unsure, wrong = queued(lib), queued(lib)
    for svid, answer in ((unsure, "not_sure"), (wrong, "pdf_wrong")):
        result = queue.decide(store, lib.rid, svid, answer, None, lib.row(svid)["row_token"])
        assert result["row"] is None and result["decision"]["decided_by"] == "human"
    assert lib.rows()["rows"] == []
    assert lib.selection(unsure) == ("pending", "code_rule") and lib.selection(wrong) == ("pending", "code_rule")
    assert lib.ds.current(lib.rid, wrong, "fulltext")["next_step"] == "waiting_for_pdf"
    assert lib.ds.current(lib.rid, unsure, "fulltext")["next_step"] == "none"
    assert lib.rows()["counts"]["decided"] == {"human_not_sure": 1, "human_pdf_wrong": 1}
    assert queue.verified_records(store, lib.rid) == []


def test_undo_brings_back_the_code_decision_and_the_row_and_releases_the_selection_only_if_unchanged_since(store):
    lib = Lib(store)
    svid = queued(lib)
    result = queue.decide(store, lib.rid, svid, "include", "SYNTHETIC both parts on page 1", lib.row(svid)["row_token"])
    assert lib.selection(svid) == ("included", "user")
    history = [row["reason"] for row in store.conn.execute(
        "SELECT reason FROM selection_history WHERE source_version_id = ? ORDER BY id", (svid,))]
    assert history[-1] == "human_include"
    events = [row[0] for row in store.conn.execute("SELECT type FROM events WHERE research_id = ?", (lib.rid,))]
    assert "stage_decision_recorded" in events
    undone = queue.undo(store, lib.rid, svid, result["undo_token"])
    assert lib.code(svid) == "part_without_evidence" and undone["row"]["reason_code"] == "part_without_evidence"
    assert lib.selection(svid) == ("pending", "code_rule")
    assert [row["source_version_id"] for row in lib.rows()["rows"]] == [svid]
    with pytest.raises(RevisionConflict):
        queue.undo(store, lib.rid, svid, undone["undo_token"])  # nothing left to undo


def test_undo_leaves_a_selection_the_user_changed_since_even_to_the_same_state(store):
    lib = Lib(store)
    svid = queued(lib)
    queue.decide(store, lib.rid, svid, "include", None, lib.row(svid)["row_token"])
    lib.list_edit(svid, "included")  # the same state, from the source list
    token = queue.row_detail(store, lib.rid, svid)["undo_token"]
    queue.undo(store, lib.rid, svid, token)
    assert lib.selection(svid) == ("included", "user")
    assert lib.code(svid) == "part_without_evidence"
    # The work is back to its code decision, and the user's own list choice keeps it out of the queue.
    assert lib.rows()["rows"] == [] and lib.rows()["counts"]["user_selected"] == 1


def test_a_decision_on_a_non_head_version_sets_the_heads_selection_and_undo_releases_it(store):
    lib = Lib(store, "irrigation")
    published = lib.published("10.9999/synth.head")
    preprint = lib.preprint("10.9999/synth.head")
    assert lib.head(preprint) == published
    lib.text(preprint, [lib.field["page"]])
    lib.read(preprint, "part_without_evidence", labels=partial(lib), head=published)
    row = lib.row(preprint)
    assert row["head"] == published and row["source_version_id"] == preprint
    result = queue.decide(store, lib.rid, preprint, "criterion_not_met", None, row["row_token"])
    assert lib.ds.current(lib.rid, preprint, "fulltext")["reason_code"] == "human_criterion_not_met"
    assert lib.ds.current(lib.rid, published, "fulltext") is None
    assert lib.selection(published) == ("excluded", "user")
    queue.undo(store, lib.rid, preprint, result["undo_token"])
    assert lib.selection(published) == ("pending", "code_rule")


@pytest.mark.parametrize("later_edit", [False, True])
def test_undo_after_a_head_change_releases_the_copied_selection_and_keeps_a_later_list_edit(store, later_edit):
    lib = Lib(store)
    preprint = lib.preprint("10.9999/synth.move")
    lib.text(preprint, [lib.field["page"]])
    lib.read(preprint, "part_without_evidence", labels=partial(lib))
    result = queue.decide(store, lib.rid, preprint, "include", None, lib.row(preprint)["row_token"])
    published = lib.published("10.9999/synth.move")
    assert lib.head(preprint) == published and lib.selection(published) == ("included", "user")
    links = store.conn.execute("SELECT head FROM human_selection_links WHERE decision_id = ? ORDER BY rowid",
                               (result["decision"]["id"],)).fetchall()
    assert [row[0] for row in links] == [preprint, published]
    if later_edit:
        lib.list_edit(published, "excluded")
    token = queue.row_detail(store, lib.rid, preprint)["undo_token"]
    queue.undo(store, lib.rid, preprint, token)
    assert lib.selection(published) == (("excluded", "user") if later_edit else ("pending", "code_rule"))


def test_a_versions_disagree_row_is_decided_on_the_named_version_and_resolves_the_work(store):
    lib = Lib(store, "irrigation")
    published = lib.published("10.9999/synth.pair")
    preprint = lib.preprint("10.9999/synth.pair")
    for svid, code in ((published, "criterion_absent"), (preprint, "all_parts_verified")):
        lib.text(svid, [lib.field["page"]])
        lib.read(svid, code, head=published,
                 labels=None if code == "all_parts_verified" else {n: ("absent", "absent") for n in lib.parts})
    row = lib.rows()["rows"][0]
    assert (row["reason_code"], row["kind"], row["source_version_id"]) == ("versions_disagree", "choose_version", preprint)
    queue.decide(store, lib.rid, preprint, "include", None, row["row_token"])
    assert lib.ds.work_outcome(lib.rid, lib.work_of(preprint))["reason_code"] == "human_include"
    assert lib.code(published) == "criterion_absent"  # the other version's decision is not touched
    assert lib.selection(published) == ("included", "user") and lib.rows()["rows"] == []


# ---- staleness and the row token -----------------------------------------------------------------------------------

def test_after_a_scope_revision_code_rows_leave_and_a_human_decision_is_listed_as_look_again_and_still_counts(store):
    lib = Lib(store)
    code_row, decided = queued(lib), queued(lib)
    queue.decide(store, lib.rid, decided, "include", None, lib.row(decided)["row_token"])
    lib.revise()
    found = lib.rows()
    assert [(row["source_version_id"], row["kind"], row["stale"]) for row in found["rows"]] == [(decided, "look_again", True)]
    assert found["counts"]["open"] == 0 and found["counts"]["look_again"] == 1
    assert code_row not in {row["source_version_id"] for row in found["rows"]}
    assert lib.selection(decided) == ("included", "user")
    assert [(r["source_version_id"], r["stale"]) for r in queue.verified_records(store, lib.rid)] == [(decided, True)]


def test_a_stale_human_include_is_listed_as_look_again_although_its_selection_is_the_users(store):
    lib = Lib(store, "irrigation")
    svid = queued(lib)
    queue.decide(store, lib.rid, svid, "include", None, lib.row(svid)["row_token"])
    lib.list_edit(svid, "included")  # the selection is now the user's own, not the queue's
    lib.revise()
    assert [(row["source_version_id"], row["kind"]) for row in lib.rows()["rows"]] == [(svid, "look_again")]


def test_answering_a_look_again_row_again_writes_a_fresh_decision(store):
    lib = Lib(store)
    svid = queued(lib)
    first = queue.decide(store, lib.rid, svid, "include", None, lib.row(svid)["row_token"])
    lib.revise()
    again = queue.decide(store, lib.rid, svid, "include", None, lib.row(svid)["row_token"])
    assert again["decision"]["id"] != first["decision"]["id"] and again["decision"]["stale"] is False
    assert again["row"] is None and lib.rows()["rows"] == []
    history = [d["reason_code"] for d in lib.ds.history(lib.rid, svid)]
    assert history == ["part_without_evidence", "human_include", "human_include"]
    assert lib.ds.current(lib.rid, svid, "fulltext")["scope_revision"] == 2


def test_a_row_token_is_rejected_after_a_scope_revision_a_new_code_decision_a_selection_change_or_a_new_pdf(store):
    lib = Lib(store)
    # A new PDF for the version.
    svid = queued(lib)
    token = lib.row(svid)["row_token"]
    lib.text(svid, [lib.field["page"]])
    with pytest.raises(RevisionConflict):
        queue.decide(store, lib.rid, svid, "include", None, token)
    # A new code decision written by a later reading run.
    token = lib.row(svid)["row_token"]
    lib.read(svid, "fulltext_runs_disagree", labels={n: ("present", "absent") for n in lib.parts})
    with pytest.raises(RevisionConflict):
        queue.decide(store, lib.rid, svid, "include", None, token)
    # A selection change on a row the queue still lists: a stale decision stays listed whoever set the selection.
    queue.decide(store, lib.rid, svid, "include", None, lib.row(svid)["row_token"])
    lib.revise()
    token = lib.row(svid)["row_token"]
    lib.list_edit(svid, "excluded")
    with pytest.raises(RevisionConflict):
        queue.decide(store, lib.rid, svid, "include", None, token)
    # A scope revision between showing and answering.
    token = lib.row(svid)["row_token"]
    lib.revise()
    with pytest.raises(RevisionConflict):
        queue.decide(store, lib.rid, svid, "criterion_not_met", None, token)
    # The row as it stands now is answered.
    queue.decide(store, lib.rid, svid, "criterion_not_met", None, lib.row(svid)["row_token"])
    assert lib.code(svid) == "human_criterion_not_met"


def test_a_row_token_is_rejected_after_a_head_change_or_the_records_removal(store):
    lib = Lib(store, "irrigation")
    preprint = lib.preprint("10.9999/synth.token")
    lib.text(preprint, [lib.field["page"]])
    lib.read(preprint, "part_without_evidence", labels=partial(lib))
    token = lib.row(preprint)["row_token"]
    published = lib.published("10.9999/synth.token")
    row = lib.row(preprint)  # the same version still asks, under a new head
    assert row["head"] == published and row["row_token"] != token
    with pytest.raises(RevisionConflict):
        queue.decide(store, lib.rid, preprint, "include", None, token)
    removed = queued(lib)
    token = lib.row(removed)["row_token"]
    store.remove_sources(lib.rid, [removed], "SYNTHETIC removed from the list")
    with pytest.raises(RevisionConflict):  # it was a source: the stale row is refused, not an unknown record
        queue.decide(store, lib.rid, removed, "include", None, token)
    assert lib.code(removed) == "part_without_evidence"


def test_a_record_that_was_never_a_source_or_a_legacy_research_is_refused(store):
    lib = Lib(store)
    other = Lib(store, "irrigation")
    stranger = queued(other)
    with pytest.raises(NotASource):
        queue.decide(store, lib.rid, stranger, "include", None, "x")
    legacy = Lib(store, workflow="legacy")
    with pytest.raises(queue.QueueUnavailable):
        queue.queue_rows(store, legacy.rid)


# ---- the fifth answer ----------------------------------------------------------------------------------------------

def test_pdf_confirmation_undo_is_refused_once_a_reading_step_for_the_work_has_opened(store):
    lib = Lib(store)
    svid = lib.work()
    asset = lib.text(svid, [lib.field["page"]])
    lib.unconfirmed(svid)
    result = queue.decide(store, lib.rid, svid, "pdf_confirmed", None, lib.row(svid)["row_token"])
    current = lib.ds.current(lib.rid, svid, "fulltext")
    assert (current["reason_code"], current["note"], current["step_id"]) == ("not_read_yet", f"pdf_confirmed:{asset}", None)
    assert store.asset(asset)["identity_confirmed_at"] and result["decision"]["undoable"] is True
    # A later reading run froze its plan after the confirmation and opened this work's step.
    run = lib.new_run("fulltext_adjudication")
    plan = store.step(run, "adjudication_plan", "code:adjudication_plan")
    store.finish_step(plan["id"], "succeeded", output={})
    store.step(run, f"fulltext_adjudication:{svid}:1", "model:fulltext_adjudication")
    with pytest.raises(RevisionConflict):
        queue.undo(store, lib.rid, svid, result["undo_token"])
    assert store.asset(asset)["identity_confirmed_at"] and lib.code(svid) == "not_read_yet"
    other = queued(lib)
    with pytest.raises(queue.QueueUnavailable):  # only a PDF identity row is confirmed
        queue.decide(store, lib.rid, other, "pdf_confirmed", None, lib.row(other)["row_token"])


def test_verified_records_lists_only_human_include_and_criterion_not_met(store):
    lib = Lib(store, "irrigation")
    answers = {}
    for answer in ("include", "criterion_not_met", "not_sure", "pdf_wrong"):
        svid = queued(lib)
        queue.decide(store, lib.rid, svid, answer, None, lib.row(svid)["row_token"])
        answers[answer] = svid
    lib.ds.record(lib.rid, lib.work(), "all_parts_verified")  # agreement of two runs is not a person's check
    found = queue.verified_records(store, lib.rid)
    assert {(row["source_version_id"], row["reason_code"], row["outcome"]) for row in found} == {
        (answers["include"], "human_include", "include"),
        (answers["criterion_not_met"], "human_criterion_not_met", "criterion_not_met")}
    assert all(row["stale"] is False and row["criterion_hash"] for row in found)


# ---- what the screen reads (slice 17, D97) --------------------------------------------------------------------------

def page_passage(store, svid, page):
    return next(p["id"] for p in store.passages_for(svid) if p["kind"] == "pdf_page" and p["physical_page"] == page)


@pytest.mark.parametrize("field", sorted(FIELDS))
def test_detail_parts_cues_and_closest_carry_the_passage_of_their_page(store, field):
    lib = Lib(store, field)
    first, second = lib.parts
    svid = lib.work()
    page = lib.field["page"]
    near = page.replace("SYNTHETIC the ", "SYNTHETIC teh ", 1)  # a few letters off: fuzzy, never verified
    lib.text(svid, ["SYNTHETIC an unrelated page about antenna gain and cable loss.", page])
    lib.read(svid, "include_quote_unverified", quotes={first: (near, near), second: (page, page)},
             verified={first: (False, False), second: (True, True)}, shown=((2,), (2,)))
    detail = queue.row_detail(store, lib.rid, svid)["detail"]
    two = page_passage(store, svid, 2)
    for run in detail["runs"]:
        by_part = {part["part"]: part for part in run["parts"]}
        assert by_part[first]["passage_id"] == two  # the passage the model named
        assert by_part[first]["closest"]["page"] == 2 and by_part[first]["closest"]["passage_id"] == two
        assert by_part[second]["passage_id"] == two and by_part[second]["page"] == 2
    # The question part's own phrase is on page 2, so its cue sentence opens that page.
    assert [(s["page"], s["passage_id"]) for s in detail["cues"]["sentences"]] == [(2, two)]


def test_every_row_detail_names_the_current_file_of_its_version(store):
    lib = Lib(store, "irrigation")
    first, second = lib.parts
    kinds = {}
    for code in ("part_without_evidence", "fulltext_runs_disagree", "include_quote_unverified"):
        svid = lib.work()
        asset = lib.text(svid, [lib.field["page"]])
        labels = partial(lib) if code == "part_without_evidence" else (
            {first: ("present", "absent"), second: ("present", "absent")} if code == "fulltext_runs_disagree" else None)
        lib.read(svid, code, labels=labels, verified={first: (False, False)} if code == "include_quote_unverified" else None)
        kinds[svid] = asset
    identity = lib.work()
    kinds[identity] = lib.text(identity, [lib.field["page"]])
    lib.unconfirmed(identity)
    for svid, asset in kinds.items():
        assert queue.row_detail(store, lib.rid, svid)["detail"]["asset_id"] == asset
    replaced = next(iter(kinds))
    newer = lib.text(replaced, [lib.field["page"]])  # a new PDF in use for the version
    assert queue.row_detail(store, lib.rid, replaced)["detail"]["asset_id"] == newer != kinds[replaced]


def test_decided_lists_current_human_decisions_and_pdf_confirmations_with_an_undo_token_and_writes_nothing(store):
    lib = Lib(store)
    included, unsure, left = queued(lib), queued(lib), queued(lib)
    queue.decide(store, lib.rid, included, "include", "SYNTHETIC both parts on page 1", lib.row(included)["row_token"])
    queue.decide(store, lib.rid, unsure, "not_sure", None, lib.row(unsure)["row_token"])
    identity = lib.work()
    lib.text(identity, [lib.field["page"]])
    lib.unconfirmed(identity)
    queue.decide(store, lib.rid, identity, "pdf_confirmed", None, lib.row(identity)["row_token"])
    tables = [row[0] for row in store.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    before = {table: store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}
    changes = store.conn.total_changes
    found = lib.rows()
    after = {table: store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}
    assert after == before and store.conn.total_changes == changes
    decided = found["decided"]
    # Newest first: the confirmation, the unsure answer, the inclusion. The row still open is not listed.
    assert [entry["source_version_id"] for entry in decided] == [identity, unsure, included]
    assert left not in {entry["source_version_id"] for entry in decided}
    first = decided[-1]
    assert (first["work_id"], first["head"], first["reason_code"], first["note"]) == (
        lib.work_of(included), included, "human_include", "SYNTHETIC both parts on page 1")
    assert first["title"] == store.source(included)["title"] and first["created_at"]
    # The listed token is the one the undo checks.
    queue.undo(store, lib.rid, included, first["undo_token"])
    assert lib.code(included) == "part_without_evidence"
    queue.undo(store, lib.rid, identity, lib.rows()["decided"][0]["undo_token"])
    assert lib.code(identity) == "pdf_identity_unconfirmed"


def test_a_decided_entry_leaves_the_list_once_undone_or_superseded(store):
    lib = Lib(store, "irrigation")
    svid = queued(lib)
    result = queue.decide(store, lib.rid, svid, "include", None, lib.row(svid)["row_token"])
    assert [entry["source_version_id"] for entry in lib.rows()["decided"]] == [svid]
    queue.undo(store, lib.rid, svid, result["undo_token"])
    assert lib.rows()["decided"] == []
    # A confirmation stands until a reading run decides the work; then the work's outcome is the reading's.
    identity = lib.work()
    lib.text(identity, [lib.field["page"]])
    lib.unconfirmed(identity)
    queue.decide(store, lib.rid, identity, "pdf_confirmed", None, lib.row(identity)["row_token"])
    assert [entry["answer"] for entry in lib.rows()["decided"]] == ["pdf_confirmed"]
    lib.read(identity, "all_parts_verified")
    assert lib.rows()["decided"] == []


def test_a_verified_quote_carries_the_source_text_it_was_found_as_and_an_unverified_one_none(store):
    lib = Lib(store)
    first, second = lib.parts
    svid = lib.work()
    page = "SYNTHETIC The Release  Model is a Poisson process, with a fixed rate per slot."
    lib.text(svid, [page])
    spaced = "synthetic the release model is a poisson process with a fixed rate per slot"
    lib.read(svid, "include_quote_unverified", quotes={first: (spaced, spaced), second: ("SYNTHETIC not on the page", page)},
             verified={first: (True, True), second: (False, True)})
    runs = {run["run_no"]: {part["part"]: part for part in run["parts"]}
            for run in queue.row_detail(store, lib.rid, svid)["detail"]["runs"]}
    # The page's own words, as the page has them: the quote's case and spacing are not the anchor.
    assert runs[1][first]["anchor_text"] == "SYNTHETIC The Release  Model is a Poisson process, with a fixed rate per slot"
    assert runs[2][second]["anchor_text"] == page.removesuffix(".")  # the match ends on the quote's last letter
    assert runs[1][second]["anchor_text"] is None and runs[1][second]["quote_verified"] is False
    for run in runs.values():
        assert all(part["anchor_text"] is None for part in run.values() if part["label"] != "present")


def test_a_stored_verified_flag_whose_quote_only_matches_fuzzily_gets_no_anchor(store):
    lib = Lib(store, "irrigation")
    first, second = lib.parts
    svid = lib.work()
    lib.text(svid, [lib.field["page"]])
    near = lib.field["page"].replace("water", "watr", 1)
    lib.read(svid, "include_quote_unverified", quotes={first: (near, near)},
             verified={first: (True, True), second: (False, False)})
    part = queue.row_detail(store, lib.rid, svid)["detail"]["runs"][0]["parts"][0]
    assert part["part"] == first and part["quote_verified"] is True and part["anchor_text"] is None


def test_a_choose_version_detail_carries_both_versions_and_their_decisions(store):
    lib = Lib(store, "irrigation")
    published = lib.published("10.9999/synth.both")
    preprint = lib.preprint("10.9999/synth.both")
    assets = {}
    for svid, code in ((published, "criterion_absent"), (preprint, "all_parts_verified")):
        assets[svid] = lib.text(svid, [lib.field["page"]])
        lib.read(svid, code, head=published,
                 labels=None if code == "all_parts_verified" else {n: ("absent", "absent") for n in lib.parts})
    row = lib.rows()["rows"][0]
    assert row["kind"] == "choose_version" and row["source_version_id"] == preprint
    versions = queue.row_detail(store, lib.rid, preprint)["detail"]["versions"]
    assert [v["source_version_id"] for v in versions] == [preprint, published]  # the named version first
    assert [(v["decision"]["reason_code"], v["decision"]["outcome"]) for v in versions] == [
        ("all_parts_verified", "include"), ("criterion_absent", "criterion_not_met")]
    assert [v["version_label"] for v in versions] == ["submittedVersion", "publishedVersion"]
    assert [v["asset_id"] for v in versions] == [assets[preprint], assets[published]]
    labels = [{part["label"] for run in v["runs"] for part in run["parts"]} for v in versions]
    assert labels == [{"present"}, {"absent"}] and all(len(v["runs"]) == 2 for v in versions)


def test_a_stale_human_decision_is_in_look_again_and_not_in_decided(store):
    lib = Lib(store)
    svid = queued(lib)
    queue.decide(store, lib.rid, svid, "criterion_not_met", None, lib.row(svid)["row_token"])
    assert [entry["source_version_id"] for entry in lib.rows()["decided"]] == [svid]
    lib.revise()
    found = lib.rows()
    assert [(row["source_version_id"], row["kind"]) for row in found["rows"]] == [(svid, "look_again")]
    assert found["decided"] == []


def test_a_confirmation_of_a_file_that_was_replaced_since_is_not_listed_as_decided(store):
    lib = Lib(store, "irrigation")
    identity = lib.work()
    lib.text(identity, [lib.field["page"]])
    lib.unconfirmed(identity)
    queue.decide(store, lib.rid, identity, "pdf_confirmed", None, lib.row(identity)["row_token"])
    assert [entry["answer"] for entry in lib.rows()["decided"]] == ["pdf_confirmed"]
    # The confirmed file is no longer the one in use, so its confirmation could not be undone: it is not offered.
    lib.text(identity, [lib.field["page"]])
    assert lib.rows()["decided"] == []


def test_the_identity_check_shows_the_text_of_physical_page_one_or_none(store):
    lib = Lib(store)
    with_first, without_first = lib.work(), lib.work()
    lib.text(with_first, ["SYNTHETIC first page", "SYNTHETIC second page"])
    asset = lib.text(without_first, [])
    with db.transaction(store.conn):
        store._insert_passage(without_first, asset, "pdf_page", 2, None, None, None, "pymupdf-synthetic",
                              "SYNTHETIC second page only")
    for svid in (with_first, without_first):
        lib.unconfirmed(svid)
    first = queue.row_detail(store, lib.rid, with_first)["detail"]["identity"]["first_page"]
    missing = queue.row_detail(store, lib.rid, without_first)["detail"]["identity"]["first_page"]
    assert (first, missing) == ("SYNTHETIC first page", None)


def test_a_confirmation_whose_reading_has_begun_is_listed_without_an_undo_and_says_why(store):
    lib = Lib(store)
    svid = lib.work()
    lib.text(svid, [lib.field["page"]])
    lib.unconfirmed(svid)
    queue.decide(store, lib.rid, svid, "pdf_confirmed", None, lib.row(svid)["row_token"])
    entry = lib.rows()["decided"][0]
    assert entry["undo_token"] and entry["undo_blocked"] is None
    run = lib.new_run("fulltext_adjudication")
    plan = store.step(run, "adjudication_plan", "code:adjudication_plan")
    store.finish_step(plan["id"], "succeeded", output={})
    store.step(run, f"fulltext_adjudication:{svid}:1", "model:fulltext_adjudication")
    # The list and `undo` apply the same rule: what the undo would refuse is not offered.
    entry = lib.rows()["decided"][0]
    assert (entry["source_version_id"], entry["undo_token"], entry["undo_blocked"]) == (svid, None, "reading_started")


def test_the_row_token_moves_when_the_text_of_the_same_file_changes(store):
    lib = Lib(store)
    svid = queued(lib)
    before = lib.row(svid)["row_token"]
    asset = store.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ? AND removed_at IS NULL",
                               (svid,)).fetchone()[0]
    # OCR or a new extraction adds passages to the file in use without replacing it.
    with db.transaction(store.conn):
        store._insert_passage(svid, asset, "pdf_page", 2, None, None, None, "pymupdf-synthetic", "SYNTHETIC added page")
    after = lib.row(svid)["row_token"]
    assert after != before
    with pytest.raises(RevisionConflict):
        queue.decide(store, lib.rid, svid, "include", None, before)


def test_after_a_head_change_both_heads_keep_the_queue_answer_their_links_name(store):
    lib = Lib(store)
    preprint = lib.preprint("10.9999/synth.both")
    lib.text(preprint, [lib.field["page"]])
    lib.read(preprint, "part_without_evidence", labels=partial(lib))
    queue.decide(store, lib.rid, preprint, "include", None, lib.row(preprint)["row_token"])
    published = lib.published("10.9999/synth.both")
    answers = queue.queue_answers(store, lib.rid)
    assert answers[(published, lib.selection_version(published))] == "include"
    assert answers[(preprint, lib.selection_version(preprint))] == "include"
    lib.list_edit(preprint, "excluded")  # the old head's selection is the person's own again
    assert (preprint, lib.selection_version(preprint)) not in queue.queue_answers(store, lib.rid)


def test_a_rejected_extraction_of_the_same_file_does_not_move_the_row_token(store):
    lib = Lib(store)
    svid = queued(lib)
    before = lib.row(svid)["row_token"]
    asset = store.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ? AND removed_at IS NULL",
                               (svid,)).fetchone()[0]
    # A later extraction that was not taken keeps its passages, but the detail shows only the current extraction's.
    with db.transaction(store.conn):
        store._insert_passage(svid, asset, "pdf_page", 1, None, None, None, "pymupdf-rejected", "SYNTHETIC rejected text")
    assert lib.row(svid)["row_token"] == before


def test_the_detail_says_a_confirmation_is_no_longer_undoable_once_its_reading_has_begun(store):
    lib = Lib(store)
    svid = lib.work()
    lib.text(svid, [lib.field["page"]])
    lib.unconfirmed(svid)
    queue.decide(store, lib.rid, svid, "pdf_confirmed", None, lib.row(svid)["row_token"])
    assert queue.row_detail(store, lib.rid, svid)["decision"]["undoable"] is True
    run = lib.new_run("fulltext_adjudication")
    plan = store.step(run, "adjudication_plan", "code:adjudication_plan")
    store.finish_step(plan["id"], "succeeded", output={})
    store.step(run, f"fulltext_adjudication:{svid}:1", "model:fulltext_adjudication")
    assert queue.row_detail(store, lib.rid, svid)["decision"]["undoable"] is False
