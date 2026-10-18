"""Reverse citation search R4b (D108): a statement check counts a work as support only when at least one of its parts
is `stated`; a `found_partial` with only `partly`/`not_stated` parts is `support_not_shown`, a class and a counter of
its own. The class is read by `statement.support_class` from stored rows under the rule the revision stored; a revision
stored before R4b reads with rule 1 and looks as before. The stored result, parts and quotes are never rewritten.
Records and model answers are SYNTHETIC; no real model or network is used."""

import csv
import io
import json
import shutil
import sqlite3

import pytest

from deixis.domain import statement
from deixis.models.adapter import ModelStepResult
from deixis.storage import db
from deixis.workflow import statement_check
from fakes import valid_response
from test_statement_check import answer, build, counter_identities, create, cutoff, execute, items, scripted

STATED = {"assessment": "stated"}
PARTLY = {"assessment": "partly"}
NOT_STATED = {"assessment": "not_stated"}


# ------------------------------------------------------------------------------------------------ the classifier

def test_a_stated_part_keeps_a_partial_result_support():
    assert statement.support_class("found_partial", [STATED, PARTLY], 2) == "found_partial"
    assert statement.support_class("found_partial", [STATED, NOT_STATED], 2) == "found_partial"


def test_a_partial_result_with_no_stated_part_is_support_not_shown():
    assert statement.support_class("found_partial", [PARTLY], 2) == "support_not_shown"
    assert statement.support_class("found_partial", [PARTLY, NOT_STATED], 2) == "support_not_shown"
    assert statement.support_class("found_partial", [PARTLY, PARTLY], 2) == "support_not_shown"


def test_found_whole_not_found_and_no_result_are_unchanged():
    assert statement.support_class("found_whole", [STATED, STATED], 2) == "found_whole"
    assert statement.support_class("not_found_in_given", [NOT_STATED], 2) == "not_found_in_given"
    assert statement.support_class(None, None, 2) is None  # could not check, planned, no text: no class
    # `derive_result` never gives a support result without a stated part list; the rule fails closed if one appears.
    assert statement.support_class("found_whole", [], 2) == "support_not_shown"


def test_rule_1_is_the_result_as_before():
    assert statement.support_class("found_partial", [PARTLY, NOT_STATED], 1) == "found_partial"
    assert statement.support_class("found_whole", [STATED], 1) == "found_whole"
    assert statement.support_class("not_found_in_given", [NOT_STATED], 1) == "not_found_in_given"
    with pytest.raises(ValueError):
        statement.support_class("found_partial", [PARTLY], 3)


# ------------------------------------------------------------------------------- a check with both kinds of partial

FIRST, SECOND = "Supervised exercise lowered cancer related fatigue", "after chemotherapy"


def two_partials():
    """A responder: the first work gets a stated part and a partly part (support); every later work a partly part and a
    not-stated part, no stated one (support not shown). Each quote is a span of the work's SYNTHETIC abstract."""
    seen: list[str] = []

    def respond(si, attempt):
        item = si["statement_check_target"]["item_id"]
        if item not in seen:
            seen.append(item)
        passage = si["passages"][0]
        quote = {"passage_id": passage["passage_id"], "quote": "supervised exercise lowered fatigue"}
        other = {"passage_id": passage["passage_id"], "quote": "in one trial"}
        if seen.index(item) == 0:
            return answer(si, [{"text": FIRST, "assessment": "stated", "evidence": [quote]},
                               {"text": SECOND, "assessment": "partly", "evidence": [other]}])
        return answer(si, [{"text": FIRST, "assessment": "partly", "evidence": [quote]},
                           {"text": SECOND, "assessment": "not_stated", "evidence": []}])
    return scripted(respond)


def checked(tmp_path, n=3):
    lib = build(tmp_path, n=n, responder=two_partials())
    cutoff(lib)
    check = create(lib)
    execute(lib, check)
    return lib, check


def test_a_new_revision_stores_rule_2_and_its_view_names_each_class(tmp_path):
    lib, check = checked(tmp_path)
    assert statement_check.check_row(lib.store, check["id"])["support_rule_version"] == statement.SUPPORT_RULE_VERSION == 2
    rows = items(lib, check)
    # The stored results are V3's, unchanged: all three are found_partial.
    assert [(r["status"], r["result"]) for r in rows] == [("done", "found_partial")] * 3
    view = statement_check.view(lib.store, check["id"])
    assert view["support_rule_version"] == 2
    assert [(i["result"], i["support_class"]) for i in view["items"]] == [
        ("found_partial", "found_partial"), ("found_partial", "support_not_shown"), ("found_partial", "support_not_shown")]
    # Parts, the model's assessments and the backend's located quotes stay visible on the support-not-shown items.
    shown = view["items"][1]
    assert [p["assessment"] for p in shown["parts"]] == ["partly", "not_stated"]
    assert shown["parts"][0]["evidence"][0]["located"] is True
    listed = statement_check.list_checks(lib.store, lib.rid)["checks"][0]
    assert listed["support_rule_version"] == 2


def test_counters_keep_support_not_shown_out_of_the_support_counters(tmp_path):
    lib, check = checked(tmp_path)
    counters = statement_check.counters(lib.store, statement_check.check_row(lib.store, check["id"]))
    counter_identities(counters)
    assert counters["results"] == {"found_whole": 0, "found_partial": 3, "not_found_in_given": 0}
    assert counters["classes"] == {"found_whole": 0, "found_partial": 1, "support_not_shown": 2, "not_found_in_given": 0}
    assert counters["classes_by_depth"]["support_not_shown"] == {"selected_passages": 0, "abstract": 2, "full_text": 0}
    assert sum(counters["classes"].values()) == counters["completed"]
    assert counters["support_rule_version"] == 2


def test_both_exports_carry_the_class_beside_the_stored_result(tmp_path):
    lib, check = checked(tmp_path)
    rows = list(csv.DictReader(io.StringIO(statement_check.export(lib.store, check["id"], "csv"))))
    assert [(r["result"], r["support_class"], r["support_rule_version"]) for r in rows] == [
        ("found_partial", "found_partial", "2"), ("found_partial", "support_not_shown", "2"),
        ("found_partial", "support_not_shown", "2")]
    markdown = statement_check.export(lib.store, check["id"], "md")
    assert "| support_class |" in markdown and markdown.count("| found_partial | support_not_shown |") == 2
    # A support-not-shown row words nothing as support: the stored result is its code, the class names the rule.
    for row in rows:
        if row["support_class"] == "support_not_shown":
            assert "support" not in " ".join(v for k, v in row.items() if k != "support_class").casefold()


def test_a_revision_stored_before_r4b_reads_with_rule_1_as_before(tmp_path):
    lib, check = checked(tmp_path)
    lib.store.conn.execute("UPDATE statement_checks SET support_rule_version = 1 WHERE id = ?", (check["id"],))
    view = statement_check.view(lib.store, check["id"])
    assert view["support_rule_version"] == 1
    assert [i["support_class"] for i in view["items"]] == ["found_partial"] * 3
    assert view["counters"]["classes"] == {"found_whole": 0, "found_partial": 3, "support_not_shown": 0,
                                           "not_found_in_given": 0}
    rows = list(csv.DictReader(io.StringIO(statement_check.export(lib.store, check["id"], "csv"))))
    assert {r["support_class"] for r in rows} == {"found_partial"}


def test_items_without_a_result_have_no_class(tmp_path):
    lib = build(tmp_path, n=1, responder=scripted(lambda si, attempt: "SYNTHETIC: not a check"))
    cutoff(lib)
    check = create(lib)
    execute(lib, check)
    (item,) = statement_check.view(lib.store, check["id"])["items"]
    assert (item["status"], item["result"], item["support_class"]) == ("could_not_check", None, None)


# ------------------------------------------------------------------------------------------------- the migration

def test_a_library_made_up_to_0010_takes_0011_and_its_revisions_read_with_rule_1(tmp_path, monkeypatch):
    before = tmp_path / "migrations"
    before.mkdir()
    for path in sorted(db.MIGRATIONS_DIR.glob("*.sql")):
        if int(path.name.split("_", 1)[0]) < 11:
            shutil.copy(path, before)
    path = tmp_path / "library.sqlite"
    with monkeypatch.context() as patch:
        patch.setattr(db, "MIGRATIONS_DIR", before)
        conn = db.connect(path)
        assert db.migrate(conn)[-1] == 10
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at, intent) VALUES ('r', 't', 'n', 'n', 'statement')")
    conn.execute("INSERT INTO statement_checks (id, research_id, revision, request_id, sentence, sentence_sha256,"
                 " scope_revision, attachment_snapshot_json, user_signature, effort, work_cap, model_json,"
                 " skill_package_hash, created_at) VALUES ('c', 'r', 1, 'req', 'S.', 'h', 1, '{}', 'u', 'quick', 12,"
                 " '{}', 'p', 'n')")
    conn.close()
    conn = db.connect(path)
    assert db.migrate(conn) == [11]
    assert conn.execute("SELECT support_rule_version FROM statement_checks WHERE id = 'c'").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE statement_checks SET support_rule_version = 3 WHERE id = 'c'")
    fresh = db.connect(tmp_path / "fresh.sqlite")
    db.migrate(fresh)
    schema = lambda c: sorted(tuple(r) for r in c.execute("SELECT type, name, tbl_name, sql FROM sqlite_master"))
    assert schema(conn) == schema(fresh)


# ------------------------------------------------------------------------------------- the rule over a lifecycle

def test_a_paused_rule_1_revision_resumes_on_rule_1_and_a_new_request_takes_rule_2(tmp_path):
    """A revision stored before R4b (rule 1) and paused by a provider failure is resumed: it stays rule 1 and the result
    stored before the pause is not rewritten. A new request then opens rule 2. One work's first answer marks its part
    `stated` without a quote (invalid) and its repair marks it `partly`: the accepted, repaired parts decide the class."""
    roles: dict[str, str] = {}  # item id -> "a" (a direct partly answer) or "b" (invalid, then a partly repair)
    attempts: dict[str, int] = {}
    failing = {"on": True}

    def respond(si):
        if si["task_type"] != "statement_check":
            return valid_response(si)
        item = si["statement_check_target"]["item_id"]
        attempts[item] = attempts.get(item, 0) + 1
        passage = si["passages"][0]
        quote = {"passage_id": passage["passage_id"], "quote": "supervised exercise lowered fatigue"}
        if roles[item] == "b" and attempts[item] == 1:
            return answer(si, [{"text": FIRST, "assessment": "stated", "evidence": []},
                               {"text": SECOND, "assessment": "not_stated", "evidence": []}])
        return answer(si, [{"text": FIRST, "assessment": "partly", "evidence": [quote]},
                           {"text": SECOND, "assessment": "not_stated", "evidence": []}])

    def fail(si):
        if failing["on"] and si["task_type"] == "statement_check" and roles[si["statement_check_target"]["item_id"]] == "b":
            return ModelStepResult("failed", error="SYNTHETIC provider error")
        return None

    lib = build(tmp_path, n=2, responder=respond, fail=fail)
    cutoff(lib)

    def open_revision(request_id):
        check = create(lib, request_id)
        first, second = items(lib, check)
        roles.update({first["id"]: "a", second["id"]: "b"})
        return check

    old = open_revision("req-old")
    # Stored before migration 0011: the column's default, rule 1.
    lib.store.conn.execute("UPDATE statement_checks SET support_rule_version = 1 WHERE id = ?", (old["id"],))
    run = execute(lib, old)
    assert (run["status"], run["pause_reason"]) == ("paused", "model_call_failed")
    first_row = items(lib, old)[0]
    assert (first_row["status"], first_row["result"]) == ("done", "found_partial")

    failing["on"] = False
    lib.store.resume_run(run["id"])
    assert execute(lib, old)["status"] == "completed"
    rows = items(lib, old)
    assert statement_check.check_row(lib.store, old["id"])["support_rule_version"] == 1
    assert (rows[0]["output_json"], rows[0]["result"], rows[0]["checked_at"]) == (
        first_row["output_json"], first_row["result"], first_row["checked_at"])
    assert attempts[rows[1]["id"]] == 2 and rows[1]["result"] == "found_partial"  # the first answer and its repair
    assert [p["assessment"] for p in json.loads(rows[1]["output_json"])["parts"]] == ["partly", "not_stated"]
    assert [i["support_class"] for i in statement_check.view(lib.store, old["id"])["items"]] == ["found_partial"] * 2

    new = open_revision("req-new")
    assert statement_check.check_row(lib.store, new["id"])["support_rule_version"] == 2
    assert execute(lib, new)["status"] == "completed"
    view = statement_check.view(lib.store, new["id"])
    assert [(i["result"], i["support_class"]) for i in view["items"]] == [("found_partial", "support_not_shown")] * 2
    assert view["counters"]["classes"]["support_not_shown"] == 2
    assert view["counters"]["classes"]["found_partial"] == 0
    # The repaired item's rejected first answer said `stated`; only the accepted parts count.
    repaired = next(i for i in items(lib, new) if roles[i["id"]] == "b")
    assert attempts[repaired["id"]] == 2
    assert [p["assessment"] for p in json.loads(repaired["output_json"])["parts"]] == ["partly", "not_stated"]
    # The rule-1 revision reads as before after the new one exists.
    assert [i["support_class"] for i in statement_check.view(lib.store, old["id"])["items"]] == ["found_partial"] * 2
