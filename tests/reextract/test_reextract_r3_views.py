"""S1-S4 synthetic citation identity and read-only provenance contracts."""

import ast
import json
import sys
from pathlib import Path

import pytest

from deixis.documents import pdf
from deixis.workflow.report.export import to_markdown
from deixis.workflow.report.latex import to_latex
from deixis.workflow.views import passage_view, report_view
from tests.helpers import make_pdf
from tests.reextract.reextract_r2a_helpers import api_library, body, head, seed, store_library, url
from tests.reextract.reextract_r2b_helpers import tear, write
from tests.reextract.reextract_r3_helpers import no_external_calls, old_dependency, retry, rich
from tests.review.review_helpers import all_rows, review_lib
from tests.report.test_report_assembly import report_with_sections


def test_s1_old_citation_document_red_on_old(tmp_path, monkeypatch):
    with api_library(tmp_path, "partial", raise_errors=True) as lib:
        rich(lib)
        old = lib.store.passages_for(lib.svid)
        real = pdf.extract_pdf
        def changed(path):
            result = real(path)
            for page in result.pages:
                page.text = "SYNTHETIC relays with replacement wording on this page."
            return result
        monkeypatch.setattr(pdf, "extract_pdf", changed)
        response = lib.client.post(url(lib), json=body(lib))
        text_url = f"/api/researches/{lib.rid}/assets/{lib.aid}/text"
        historic = lib.client.get(text_url, params={"extraction_id": lib.eid}).json()
        assert [(p["id"], p["text"]) for p in historic["passages"]] == [(p["id"], p["text"]) for p in old]
        assert response.status_code == 200 and response.json()["recovery"]["outcome"] == "promoted"
        assert historic["occurrence"]["outcome"] == "superseded"
        current = lib.client.get(text_url).json()
        assert current["occurrence"]["extraction_id"] == head(lib.store, lib.aid)["id"]
        link = lib.conn.execute("SELECT * FROM evidence_links WHERE passage_id = ?", (lib.pid,)).fetchone()
        returned = next(p for p in historic["passages"] if p["id"] == link["passage_id"])
        assert link["anchor_text"] in returned["text"]
        assert all(link["anchor_text"] not in p["text"] for p in current["passages"] if p["physical_page"] == returned["physical_page"])
        # Rejected occurrences and another asset's occurrence never become a document view.
        candidate = changed(lib.path)
        candidate.pages = []
        lib.store.reextract_asset(lib.aid, candidate, "synthetic-rejected", pdf.chunk_page)
        rejected = lib.conn.execute("SELECT id FROM asset_extractions WHERE outcome = 'rejected'").fetchone()[0]
        foreign = seed(lib.store, lib.settings, data=make_pdf(["SYNTHETIC foreign PDF"]))
        for eid in (rejected, foreign.eid, "missing"):
            refused = lib.client.get(text_url, params={"extraction_id": eid})
            assert refused.status_code == 404 and refused.json()["detail"] == "Extraction is not part of this asset"
        replacement = make_pdf(["SYNTHETIC different replacement PDF"])
        replaced = lib.client.put(url(lib).removesuffix("/extractions"), files={"file": ("replace.pdf", replacement, "application/pdf")})
        assert replaced.status_code == 200, replaced.text
        assert lib.client.get(text_url, params={"extraction_id": lib.eid}).json()["passages"] == historic["passages"]
        assert lib.client.get(text_url).status_code == 404


def test_s2_occurrence_input_and_restore_new_contract(tmp_path):
    """Paired with S1; recorded input is not a claim about today's served file."""
    with api_library(tmp_path, "partial", raise_errors=True) as lib:
        rich(lib)
        retry(lib)
        value = passage_view(lib.store, lib.rid, lib.pid)["occurrence"]
        assert value["extraction_id"] == lib.eid and not value["is_current"]
        assert value["current_extraction_id"] == head(lib.store, lib.aid)["id"]
        assert value["input"] is None and value["input_relation"] == "input_not_recorded"
        tear(lib)
        result = write(lib)
        value = passage_view(lib.store, lib.rid, lib.pid)["occurrence"]
        assert value["input"] is None and value["file_restored_after"]
        assert value["latest_file_restore"] == lib.store.file_restore_view(result.operation_id)
        data = make_pdf(["SYNTHETIC verified initial parser input"])
        response = lib.client.post(f"/api/researches/{lib.rid}/uploads", files={"file": ("new.pdf", data, "application/pdf")})
        svid = response.json()["uploaded_source_version_id"]
        pid = lib.store.passages_for(svid)[0]["id"]
        value = passage_view(lib.store, lib.rid, pid)["occurrence"]
        assert value["input"]["integrity"] == "verified" and value["input_relation"] == "input_matched_expected_hash"
        asset = lib.store.asset(lib.store.passage(pid)["asset_id"])
        (lib.settings.papers_dir / asset["storage_path"]).write_bytes(b"SYNTHETIC torn later")
        assert passage_view(lib.store, lib.rid, pid)["occurrence"] == value
        abstract = lib.store._insert_passage(lib.svid, None, "abstract", None, None, "synthetic", None, None, "SYNTHETIC abstract")
        assert passage_view(lib.store, lib.rid, abstract)["occurrence"] is None


@pytest.mark.parametrize("retained", [False, True])
def test_s2_mismatch_retention_new_contract(tmp_path, retained):
    """Paired with S1; only a recorded before observation establishes retained_copy."""
    with store_library(tmp_path, "partial") as lib:
        torn = b"SYNTHETIC input mismatch"
        import hashlib
        sha = hashlib.sha256(torn).hexdigest()
        lib.store.reextract_asset(lib.aid, pdf.extract_pdf(lib.path), "synthetic-input-mismatch", pdf.chunk_page,
            input_observation=dict(kind="extraction_input", operation_id=None, storage_path=lib.path.name,
            expected_sha256=lib.sha, expected_byte_size=len(lib.data), observed_sha256=sha,
            observed_byte_size=len(torn), integrity="mismatch"))
        if retained:
            lib.store.add_file_observation(kind="before_restore", operation_id=None, storage_path=lib.path.name,
                expected_sha256=lib.sha, expected_byte_size=len(lib.data), observed_sha256=sha,
                observed_byte_size=len(torn), integrity="mismatch", retained_filename="retained-" + sha + ".bin")
        value = passage_view(lib.store, lib.rid, lib.store.passages_for(lib.svid)[0]["id"])["occurrence"]
        assert value["input_relation"] == "input_differed_from_expected_hash" and value["retained_copy"] is retained


def exports(lib, language="en"):
    view = report_view(lib.store, lib.rid, lib.report_id) | {"language": language}
    corpus = lib.rich["reports"].snapshot(lib.report_id)["corpus"]
    sources = [lib.store.source(r["source_version_id"]) | {"source_version_id": r["source_version_id"], "arxiv_id": None} for r in view["references"]]
    bundle = to_latex(view, title="SYNTHETIC R3", corpus=corpus, bib_sources=sources)
    return view, to_markdown(view, title="SYNTHETIC R3", corpus=corpus), bundle.tex


def test_s3_report_freshness_red_on_old(tmp_path):
    with store_library(tmp_path, "partial") as lib:
        rich(lib)
        before_changes = json.dumps(lib.rich["reports"].evidence_changes(lib.report_id), sort_keys=True)
        before_rows = all_rows(lib.conn)
        baseline = exports(lib)
        baseline_rows_unchanged = all_rows(lib.conn) == before_rows
        baseline_bytes_unchanged = exports(lib)[1:] == baseline[1:]
        retry(lib)
        before_rows = all_rows(lib.conn)
        view, markdown, latex = exports(lib)
        assert "Passage freshness compared:" in markdown
        assert baseline_rows_unchanged and baseline_bytes_unchanged
        freshness = view["passage_freshness"]
        assert freshness["compared"] == "passage_identity" and freshness["semantic_support"] == "not_checked"
        assert len(freshness["affected"]) == 1 and not freshness["unresolved"]
        item = freshness["affected"][0]
        assert item["passage_id"] == lib.pid and item["evidence_status"] == "text_superseded"
        assert item["passage_extraction_id"] == lib.eid and item["current_extraction_id"] != lib.eid
        assert {u["kind"] for u in item["used_by"]} == {"citation", "restorable_citation", "snapshot_cell", "gap_basis", "section_input", "equation_origin"}
        assert item["used_by"] == sorted(item["used_by"], key=lambda u: (u["kind"], u["ref"]))
        assert json.dumps(lib.rich["reports"].evidence_changes(lib.report_id), sort_keys=True) == before_changes
        assert view["evidence_changes"]["not_checked"] == ["passages"]
        assert "Passage freshness compared:" in latex
        assert "Pasaj güncelliği karşılaştırıldı:" in exports(lib, "tr")[1]
        assert all_rows(lib.conn) == before_rows
        lib.conn.execute("UPDATE report_gaps SET basis_json = ? WHERE id = ?", (json.dumps({"basis_passage_ids": ["missing"]}), lib.gap_id))
        unresolved = report_view(lib.store, lib.rid, lib.report_id)["passage_freshness"]["unresolved"]
        assert unresolved == [{"passage_id": "missing", "reason": "passage_missing", "used_by": [{"kind": "gap_basis", "ref": lib.gap_id}]}]


@pytest.mark.parametrize("kind", ["snapshot", "basis", "input", "origin"])
@pytest.mark.parametrize("raw", ["{", "[]", "{}", '{"passages": [2], "allowlist": []}'])
def test_s3_unreadable_records_new_contract(tmp_path, kind, raw):
    """Paired with S3; direct freshness is tolerant, existing snapshot readers retain their policy."""
    from deixis.workflow.report.passage_freshness import passage_freshness
    with store_library(tmp_path, "partial") as lib:
        rich(lib, reviews=False)
        if kind == "snapshot":
            lib.conn.execute("UPDATE report_snapshot SET snapshot_json = ? WHERE report_id = ?", (raw, lib.report_id))
        elif kind == "basis":
            if raw.startswith('{"passages"'):
                raw = '{"basis_passage_ids": [2]}'
            lib.conn.execute("UPDATE report_gaps SET basis_json = ? WHERE id = ?", (raw, lib.gap_id))
        elif kind == "input":
            # Append a malformed latest input; immutable historical inputs stay intact.
            old_input = dict(lib.conn.execute("SELECT * FROM step_inputs WHERE id = ?", (lib.rich["report_input_id"],)).fetchone())
            old_input["id"] = "sti_synthetic_unreadable"
            old_input["attempt"] += 1
            old_input["payload_json"] = raw
            columns = list(old_input)
            lib.conn.execute("INSERT INTO step_inputs (" + ",".join(columns) + ") VALUES (" + ",".join("?" for _ in columns) + ")", tuple(old_input.values()))
        else:
            lib.conn.execute("UPDATE report_claims SET equation_origin_json = ? WHERE equation_origin_json IS NOT NULL", (raw,))
        before = all_rows(lib.conn)
        result = passage_freshness(lib.rich["reports"], lib.report_id)
        # Readable legacy records can omit optional passage collections.
        if (kind == "origin" and raw in ("{}", '{"passages": [2], "allowlist": []}')) or (kind in ("basis", "input") and raw == "{}"):
            assert not result["unresolved"]
        else:
            assert any(u["reason"] == "unreadable_record" for u in result["unresolved"])
        if kind == "input":
            assert report_view(lib.store, lib.rid, lib.report_id)["passage_freshness"] == result
        assert all_rows(lib.conn) == before


def check_old_oracle(store, reader):
    ids = [r[0] for r in store.conn.execute("SELECT id FROM passages")] + ["missing"]
    expected = {pid: old_dependency(store.conn, pid) for pid in ids}
    assert {pid: reader.evidence_dependency(pid) for pid in ids} == expected
    assert store.evidence_statuses(ids) == {pid: item["evidence_status"] for pid, item in expected.items() if item is not None}


def test_s4a_review_dependency_guard(review_lib):
    check_old_oracle(review_lib["store"], review_lib["reader"])


def test_s4a_promotion_dependency_guard(tmp_path):
    with store_library(tmp_path, "partial") as lib:
        rich(lib)
        check_old_oracle(lib.store, lib.rich["reader"])
        retry(lib)
        check_old_oracle(lib.store, lib.rich["reader"])


def test_s4b_shared_helper_new_contract(tmp_path):
    """Paired with S4a, including chunk bounds and a query-only connection."""
    from deixis.workflow import evidence_deps
    with store_library(tmp_path, "partial") as lib:
        rich(lib)
        retry(lib)
        ids = [r[0] for r in lib.conn.execute("SELECT id FROM passages")]
        expected = lib.store.evidence_statuses(ids)
        lib.conn.execute("PRAGMA query_only = ON")
        assert {pid: row["evidence_status"] for pid, row in evidence_deps.passage_dependencies(lib.conn, ids).items()} == expected
        queries = []
        lib.conn.set_trace_callback(queries.append)
        assert evidence_deps.passage_dependencies(lib.conn, ["unknown" + str(i) for i in range(1001)]) == dict.fromkeys("unknown" + str(i) for i in range(1001))
        assert len(queries) == 3 and all(q.startswith("SELECT ") for q in queries)
    source = Path(evidence_deps.__file__).read_text()
    imports = [n for n in ast.walk(ast.parse(source)) if isinstance(n, (ast.Import, ast.ImportFrom))]
    modules = [name.name for node in imports if isinstance(node, ast.Import) for name in node.names]
    modules.extend(node.module for node in imports if isinstance(node, ast.ImportFrom))
    assert all(name.split(".")[0] in sys.stdlib_module_names | {"__future__"} for name in modules)
