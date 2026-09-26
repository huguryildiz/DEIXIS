"""Migration 0054 and the contract changes of slice 22 (D104, decision 7): the passages rebuild, the two new tables, the
`latex_source` value, `report_section_draft.v2` and the `equation_origin` check. Libraries are SYNTHETIC, built at 0053
through the product's own answer run plus a few SQL rows; no network is used."""

import copy
import json
import re
import shutil
import sqlite3

import pytest
from fastapi.testclient import TestClient

from arxiv_helpers import no_network  # noqa: F401
from deixis.domain import contracts, skill
from deixis.storage import db
from test_api_flow import app_for, create, session, wait_run
from helpers import make_pdf

STEP_INPUTS = json.loads((__import__("pathlib").Path(__file__).parent / "fixtures/research/step-inputs.json").read_text())
OLD_HASH = "sha256:7d4e238c3e9feebd451c77fb997aff717a3617008bd4165be56f9fba46bf6fca"
REBUILD = "0054_arxiv_latex_source.sql"


def at_0053(tmp_path, monkeypatch):
    folder = tmp_path / "migrations-0053"
    folder.mkdir()
    for path in db.MIGRATIONS_DIR.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) < 54:  # a library as it stood before 0054, later migrations included
            shutil.copy(path, folder / path.name)
    real = db.MIGRATIONS_DIR
    monkeypatch.setattr(db, "MIGRATIONS_DIR", folder)
    return real


def populate(tmp_path, monkeypatch):
    """A 0053 library with passages, an answer's evidence links, a cell's evidence link, an embedding, a report citation
    and a model proposal's quote, all pointing at passages."""
    real = at_0053(tmp_path, monkeypatch)
    with TestClient(app_for(tmp_path)) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", make_pdf(["SYNTHETIC channel page one.", "SYNTHETIC channel page two."]), "application/pdf")})
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"]
        _, run = wait_run(client, rid, run_id)
        assert run["status"] == "completed"
    conn = db.connect(tmp_path / "data/library.sqlite")
    assert max(r[0] for r in conn.execute("SELECT version FROM schema_migrations")) == 53
    passage, svid = conn.execute("SELECT id, source_version_id FROM passages WHERE kind = 'pdf_page' ORDER BY rowid LIMIT 1").fetchone()
    step_id, step_input = conn.execute("SELECT step_id, id FROM step_inputs WHERE run_id = ? LIMIT 1", (run_id,)).fetchone()
    ts = "2026-09-25T00:00:00.000+00:00"
    conn.executescript(f"""
        INSERT INTO evidence_tables (id, research_id, title, created_at, updated_at) VALUES ('tbl_S', '{rid}', 'SYNTHETIC', '{ts}', '{ts}');
        INSERT INTO table_columns (id, table_id, position, origin, created_at) VALUES ('col_S', 'tbl_S', 0, 'user', '{ts}');
        INSERT INTO evidence_cells (id, table_id, column_id, source_version_id, created_at, updated_at) VALUES ('cel_S', 'tbl_S', 'col_S', '{svid}', '{ts}', '{ts}');
        INSERT INTO cell_revisions (id, cell_id, kind, author, column_revision, state, value_json, created_at)
          VALUES ('crv_S', 'cel_S', 'human_edit', 'human', 1, 'value', '"x"', '{ts}');
        INSERT INTO cell_evidence_links (cell_revision_id, passage_id, source_version_id) VALUES ('crv_S', '{passage}', '{svid}');
        INSERT INTO passage_embeddings (passage_id, model, dimensions, vector, created_at) VALUES ('{passage}', 'm', 1, x'00', '{ts}');
        INSERT INTO reports (id, research_id, run_id, scope_revision, status, created_at, updated_at) VALUES ('rpt_S', '{rid}', '{run_id}', 1, 'valid', '{ts}', '{ts}');
        INSERT INTO report_sections (id, report_id, section_id, status, ordinal, created_at, updated_at) VALUES ('rsc_S', 'rpt_S', 'IV', 'valid', 4, '{ts}', '{ts}');
        INSERT INTO report_claims (id, report_section_id, claim_key, ordinal, paragraph, text, support_type) VALUES ('rcl_S', 'rsc_S', 'C1', 1, 1, 'x', 'source_stated');
        INSERT INTO report_citation_links (id, claim_id, passage_id, source_version_id, step_input_id) VALUES ('rcit_S', 'rcl_S', '{passage}', '{svid}', '{step_input}');
        INSERT INTO model_proposals (id, research_id, source_version_id, stage, step_id, run_no, label, quote_passage_id, created_at)
          VALUES ('mpr_S', '{rid}', '{svid}', 'fulltext', '{step_id}', 1, 'present', '{passage}', '{ts}');
    """)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", real)
    return conn, passage, svid


def ddl(conn, name):
    return conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (name,)).fetchone()[0]


def test_the_passages_rebuild_keeps_every_row_link_trigger_and_fts_entry(tmp_path, monkeypatch):
    conn, passage, svid = populate(tmp_path, monkeypatch)
    before_ddl, before_trigger = ddl(conn, "passages"), ddl(conn, "cell_evidence_same_source")
    rows = conn.execute("SELECT rowid, id, text_sha256, text_source FROM passages ORDER BY rowid").fetchall()
    fts = conn.execute("SELECT rowid FROM passages_fts WHERE passages_fts MATCH 'channel' ORDER BY rowid").fetchall()
    assert db.migrate(conn)[:1] == [54]  # the rebuild first; migrations added after it follow
    after_ddl = ddl(conn, "passages")
    normalize = lambda s: re.sub(r'CREATE TABLE "?passages(_new)?"?', "CREATE TABLE passages", s)  # noqa: E731
    assert normalize(after_ddl) == normalize(before_ddl).replace("'marker'))", "'marker', 'latex_source'))")
    assert ddl(conn, "cell_evidence_same_source") == before_trigger
    assert conn.execute("SELECT rowid, id, text_sha256, text_source FROM passages ORDER BY rowid").fetchall() == rows
    assert conn.execute("SELECT rowid FROM passages_fts WHERE passages_fts MATCH 'channel' ORDER BY rowid").fetchall() == fts
    conn.execute("INSERT INTO passages_fts(passages_fts, rank) VALUES ('integrity-check', 1)")
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    for table, column in (("evidence_links", "passage_id"), ("cell_evidence_links", "passage_id"), ("report_citation_links", "passage_id"),
                          ("passage_embeddings", "passage_id"), ("model_proposals", "quote_passage_id")):
        assert conn.execute(f"SELECT COUNT(*) FROM {table} t JOIN passages p ON p.id = t.{column}").fetchone()[0] >= 1, table
    assert conn.execute("SELECT COUNT(*) FROM arxiv_sources").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM asset_arxiv_versions").fetchone()[0] == 0
    with pytest.raises(sqlite3.IntegrityError, match="cell evidence must come from the cell source version"):
        other = conn.execute("SELECT id FROM source_versions WHERE id <> ? LIMIT 1", (svid,)).fetchone()
        conn.execute("INSERT INTO cell_evidence_links (cell_revision_id, passage_id, source_version_id) VALUES ('crv_S', ?, ?)",
                     (passage, other[0] if other else "srv_none"))
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("UPDATE passages SET text = 'changed' WHERE id = ?", (passage,))
    ts = "2026-09-25T00:00:00.000+00:00"
    conn.execute("INSERT INTO passages (id, source_version_id, kind, abstract_origin, text, text_sha256, retrieved_at, created_at, text_source)"
                 " VALUES ('psg_L', ?, 'abstract', 'x', 'SYNTHETIC latexsourceword', 'h', ?, ?, 'latex_source')", (svid, ts, ts))
    assert conn.execute("SELECT COUNT(*) FROM passages_fts WHERE passages_fts MATCH 'latexsourceword'").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO passages (id, source_version_id, kind, abstract_origin, text, text_sha256, retrieved_at, created_at, text_source)"
                     " VALUES ('psg_U', ?, 'abstract', 'x', 'y', 'h', ?, ?, 'unknown')", (svid, ts, ts))
    assert max(r[0] for r in conn.execute("SELECT version FROM schema_migrations")) == 55  # 0055 (SW21) follows the rebuild


# ---- contracts ------------------------------------------------------------------------------------------------------------
def section_case():
    step_input = copy.deepcopy(STEP_INPUTS["C_report_section_IV"])
    cases = json.loads((__import__("pathlib").Path(__file__).parent / "fixtures/research/fake-outputs.json").read_text())["cases"]
    case = next(c for c in cases if c["step_input"] == "C_report_section_IV" and c["expect_ok"])
    return step_input, copy.deepcopy(case["output"])


def validate(step_input, output):
    return contracts.validate_model_output(step_input, json.dumps(output))


def test_a_step_input_passage_may_carry_latex_source():
    step_input = copy.deepcopy(STEP_INPUTS["A_answer"])
    passage = next(p for p in step_input["passages"] if p["text_source"] == "text_layer")
    passage["text_source"] = "latex_source"
    assert contracts.check_step_input(step_input) == []
    passage["text_source"] = "compiled_source"
    assert [i.code for i in contracts.check_step_input(step_input)] == ["step_input_schema_invalid"]


def test_the_report_section_draft_is_v2_and_its_equation_origin_is_checked():
    assert contracts.SCHEMA_VERSIONS["ReportSectionDraft"] == "deixis.report_section_draft.v2"
    step_input, output = section_case()
    assert output["schema_version"] == "deixis.report_section_draft.v2"
    claim = output["claims"][0]
    passages = {p["passage_id"]: p for p in step_input["passages"]}
    cited = claim["passage_ids"][0]
    for source in ("latex_source", "marker", "ocr", "text_layer"):
        passages[cited]["text_source"] = source
        claim["equation_origin"] = {"passage_id": cited, "text_source": source}
        assert not [i for i in validate(step_input, output).issues if i.code.startswith("equation_origin")], source
        claim["equation_origin"] = {"passage_id": cited, "text_source": "ocr" if source != "ocr" else "marker"}
        assert "equation_origin_mismatch" in {i.code for i in validate(step_input, output).issues}
    uncited = next(pid for pid in passages if pid not in claim["passage_ids"])
    claim["equation_origin"] = {"passage_id": uncited, "text_source": passages[uncited]["text_source"] or "text_layer"}
    assert "equation_origin_not_cited" in {i.code for i in validate(step_input, output).issues}
    claim["equation_origin"] = {"passage_id": "psg_NOTGIVEN00001", "text_source": "latex_source"}
    assert "unknown_passage_id" in {i.code for i in validate(step_input, output).issues}


def test_the_method_package_names_latex_source_and_its_hash_moved():
    assert skill.package_hash() != OLD_HASH and skill.integrity_issues() == []
    for name in ("source-grounded-answer.md", "evidence-table.md"):
        text = (skill.SKILL_DIR / "references" / name).read_text()
        assert "`latex_source` is the PDF's own text of a passage" in text
        assert "did not check that the source compiles to" in text and "verified" not in text.split("`latex_source`")[1][:600]
