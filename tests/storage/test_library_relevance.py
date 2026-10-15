"""The Library marks which researches a work is relevant to, so the page can hide unread search results by default.

Records are SYNTHETIC. Passing shows which stored screening decisions make a work relevant; it says nothing about how
good those decisions are.
"""

from deixis.storage import db
from deixis.workflow.views import library_view
from test_lineage_store import make_library


def decide(lib, rid, svid, stage, outcome, superseded=False):
    lib.conn.execute(
        "INSERT INTO stage_decisions (id, research_id, source_version_id, stage, outcome, reason_code, decided_by, next_step,"
        " scope_revision, superseded_at, created_at) VALUES (?, ?, ?, ?, ?, 'SYNTHETIC', 'code', 'none', 1, ?, 'now')",
        (db.new_id("sdc"), rid, svid, stage, outcome, "then" if superseded else None))


def test_library_marks_relevance_per_research_from_screening_and_how_the_source_came(tmp_path):
    lib = make_library(tmp_path / "library.sqlite")
    try:
        found = lib.store.create_research("SYNTHETIC search?", "academic", "quick", [], "fake", "fake-model", "en")
        for letter in ("a", "b", "c", "d", "z"):
            lib.store.add_to_corpus(found, lib.ids[letter], "search")
        decide(lib, found, lib.ids["a"], "fulltext", "include")
        decide(lib, found, lib.ids["b"], "abstract", "candidate")
        decide(lib, found, lib.ids["c"], "abstract", "candidate")
        decide(lib, found, lib.ids["c"], "fulltext", "criterion_not_met")  # read in full and set aside
        decide(lib, found, lib.ids["d"], "abstract", "out_of_scope")
        decide(lib, found, lib.ids["z"], "fulltext", "include", superseded=True)  # an old decision no longer counts

        relevant = {e["work_id"]: set(e["relevant_research_ids"]) for e in library_view(lib.store)["entries"]}
        # Every source of the first research was uploaded by the user, so each is relevant there.
        assert relevant == {"wrk_a": {lib.rid, found}, "wrk_b": {lib.rid, found}, "wrk_c": {lib.rid},
                            "wrk_d": {lib.rid}, "wrk_z": {lib.rid}}

        lib.store.remove_sources(found, [lib.ids["a"]], "SYNTHETIC removal")
        entry = next(e for e in library_view(lib.store)["entries"] if e["work_id"] == "wrk_a")
        assert entry["relevant_research_ids"] == [lib.rid]  # a removed source is relevant to no research it left
    finally:
        lib.conn.close()
