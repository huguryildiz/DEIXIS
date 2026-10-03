"""P9 H2, F02: SIGKILL while a PDF is written to disk or its passages are written to the library.

Four cuts, each on a real process: inside the file write of a download (the file is half written when the process
dies), after the file is complete and before the library row exists, inside the write transaction of the asset and its
passages (asset row and two passage rows inserted, not committed), and the same upload repeated afterwards.
SYNTHETIC files, a scripted model, single runs. SIGKILL is not power loss: SQLite's WAL durability is not shown here.
"""

from __future__ import annotations

import hashlib
import threading

import pytest
from p9_harness import (ASSET_COLUMNS, PASSAGE_COLUMNS, count, create_research, digest, discovery_to_answer_ready,  # noqa: F401
                        foreign_key_check, harness, integrity_check, papers_files, rows, sha256_file, start_run, upload,
                        wait_for, wait_run)
from helpers import make_pdf

pytestmark = pytest.mark.process


def file_problems(data) -> list[str]:
    problems = []
    for path in papers_files(data):
        if path.suffix == ".pdf" and sha256_file(path) != path.stem:
            problems.append(f"papers/{path.name} is {path.stat().st_size} bytes and its content hash is {sha256_file(path)[:12]}, not its name")
    for row in rows(data, "SELECT storage_path, sha256 FROM source_assets"):
        path = data / "papers" / row["storage_path"]
        if not path.exists():
            problems.append(f"source_assets row {row['sha256'][:12]} has no file")
        elif sha256_file(path) != row["sha256"]:
            problems.append(f"source_assets row {row['sha256'][:12]} does not match its file {path.name}")
    return problems


def assert_library_sound(data) -> None:
    assert integrity_check(data) == "ok"
    assert foreign_key_check(data) == []


def backup_attempt(harness, data, tmp_path):
    dest = tmp_path / "backup-out"
    dest.mkdir(exist_ok=True)
    return harness.run_cli(["backup", str(dest)], data)


def backup_works(harness, data, tmp_path) -> str:
    done = backup_attempt(harness, data, tmp_path)
    assert done.returncode == 0, (done.stdout, done.stderr)
    return done.stdout.strip()


def test_f02_download_write_cut_by_sigkill(harness, tmp_path):
    """The 2nd file write of the answer run is cut at half its bytes. On the old code that is the final, hash-named file."""
    data = tmp_path / "data"
    first = harness.start_server(data, "first", P9_HOLD_PAPER_WRITE_NTH="2")
    c = first.client
    rid = create_research(c, "attached_and_academic")
    discovery_to_answer_ready(c, rid)
    answer = start_run(c, rid, "answer")
    held = first.wait_held("paper_write")
    assert 0 < held["written"] < held["total"], held
    done_assets = rows(data, "SELECT id FROM source_assets")
    assert len(done_assets) == 1, "the first download should be a complete asset by now"
    asset_id = done_assets[0]["id"]
    passages_before = digest(data, "passages", PASSAGE_COLUMNS, "asset_id = ?", (asset_id,))
    assets_before = digest(data, "source_assets", ASSET_COLUMNS, "id = ?", (asset_id,))
    first.no_network()
    first.kill9()

    second = harness.start_server(data, "second")
    problems = [f"after restart: {p}" for p in file_problems(data)]
    assert_library_sound(data)
    assert digest(data, "passages", PASSAGE_COLUMNS, "asset_id = ?", (asset_id,)) == passages_before
    assert digest(data, "source_assets", ASSET_COLUMNS, "id = ?", (asset_id,)) == assets_before
    leftovers = sorted(p.name[:14] + "..." + p.suffix for p in papers_files(data) if p.suffix != ".pdf")
    print("F02 download write: non-.pdf files left in papers/:", leftovers)

    assert second.client.post(f"/api/runs/{answer}/resume").status_code in (200, 202)
    row = wait_run(second.client, rid, answer)
    assert row["status"] == "completed", row
    assert count(data, "answers", "research_id = ?", (rid,)) == 1
    problems += [f"after resume: {p}" for p in file_problems(data)]
    assert_library_sound(data)
    assert digest(data, "passages", PASSAGE_COLUMNS, "asset_id = ?", (asset_id,)) == passages_before
    done = backup_attempt(harness, data, tmp_path)
    if done.returncode != 0:
        problems.append(f"backup failed ({done.returncode}): {done.stderr.strip()}")
    else:
        print("F02 download write:", done.stdout.strip())
    second.no_network()
    assert not problems, "\n" + "\n".join(problems)


def test_f02_file_complete_row_missing(harness, tmp_path):
    """Extraction call 1 is the attached upload's; call 2 is the first extraction of the answer run, for a complete
    hash-named file whose library row is not written yet when the process dies."""
    data = tmp_path / "data"
    first = harness.start_server(data, "first", P9_HOLD_EXTRACT_NTH="2")
    c = first.client
    rid = create_research(c, "attached_and_academic")
    assert upload(c, rid, "attached.pdf", make_pdf(["SYNTHETIC attached page one.", "SYNTHETIC attached page two."])).status_code == 201
    discovery_to_answer_ready(c, rid)
    answer = start_run(c, rid, "answer")
    held = first.wait_held("extract")
    # Since R3 (D197) the extraction reads a private hash-verified copy named <sha256>-<token>.pdf; the placed
    # hash-named file is the one that must be complete while its row is missing.
    sha = held["file"][:64]
    path = data / "papers" / (sha + ".pdf")
    assert path.exists() and sha256_file(path) == sha
    size_before, mtime_before = path.stat().st_size, path.stat().st_mtime_ns
    assert count(data, "source_assets", "sha256 = ?", (sha,)) == 0, "the row must not exist yet"
    first.no_network()
    first.kill9()

    second = harness.start_server(data, "second")
    assert path.exists() and sha256_file(path) == sha
    assert count(data, "source_assets", "sha256 = ?", (sha,)) == 0
    assert_library_sound(data)
    assert second.client.post(f"/api/runs/{answer}/resume").status_code in (200, 202)
    row = wait_run(second.client, rid, answer)
    assert row["status"] == "completed", row
    assert count(data, "source_assets", "sha256 = ?", (sha,)) == 1, "the row should appear on resume"
    assert (path.stat().st_size, path.stat().st_mtime_ns) == (size_before, mtime_before), "the complete file must be reused, not rewritten"
    assert count(data, "answers", "research_id = ?", (rid,)) == 1
    assert file_problems(data) == []
    assert_library_sound(data)
    print("F02 file written, row not:", backup_works(harness, data, tmp_path))
    second.no_network()


def test_f02_passage_write_cut_by_sigkill(harness, tmp_path):
    data, other = tmp_path / "data", tmp_path / "data-other"
    gate = tmp_path / "gate"
    gate.mkdir()
    first = harness.start_server(data, "first", P9_GATE_DIR=str(gate))
    c = first.client
    rid = create_research(c, "attached")
    pdf_a = make_pdf(["SYNTHETIC A page one: alpha release schedule.", "SYNTHETIC A page two: beta bisection bound."])
    pdf_b = make_pdf(["SYNTHETIC B page one: gamma relay budget.", "SYNTHETIC B page two: delta hop allocation rule."])
    assert upload(c, rid, "a.pdf", pdf_a).status_code == 201
    asset_a = rows(data, "SELECT id FROM source_assets")
    assert len(asset_a) == 1
    a_id = asset_a[0]["id"]
    passages_a = digest(data, "passages", PASSAGE_COLUMNS, "asset_id = ?", (a_id,))
    assets_a = digest(data, "source_assets", ASSET_COLUMNS)
    works_before, versions_before = count(data, "works"), count(data, "source_versions")
    view_before = sorted(s["source_version_id"] for s in c.get(f"/api/researches/{rid}").json()["sources"])
    (gate / "armed").write_text("1")
    outcome: dict = {}

    def send_b() -> None:
        try:
            outcome["response"] = upload(c, rid, "b.pdf", pdf_b, timeout=30)
        except Exception as exc:  # the connection dies with the process
            outcome["error"] = type(exc).__name__

    thread = threading.Thread(target=send_b, daemon=True)
    thread.start()
    wait_for(lambda: (gate / "reached").exists(), 60, "the write transaction reaching its gate")
    first.no_network()
    first.kill9()
    thread.join(10)
    assert "error" in outcome, outcome  # no 201 was ever sent

    second = harness.start_server(data, "second")
    c = second.client
    b_sha = hashlib.sha256(pdf_b).hexdigest()
    assert count(data, "source_assets", "sha256 = ?", (b_sha,)) == 0
    assert count(data, "source_assets") == 1
    assert count(data, "passages", "asset_id IS NOT NULL AND asset_id != ?", (a_id,)) == 0
    assert digest(data, "passages", PASSAGE_COLUMNS, "asset_id = ?", (a_id,)) == passages_a
    assert digest(data, "source_assets", ASSET_COLUMNS) == assets_a
    assert_library_sound(data)
    works_after, versions_after = count(data, "works"), count(data, "source_versions")
    view_after = sorted(s["source_version_id"] for s in c.get(f"/api/researches/{rid}").json()["sources"])
    library = c.get("/api/library").json()
    orphans = rows(data, "SELECT v.id FROM source_versions v WHERE NOT EXISTS (SELECT 1 FROM source_assets a WHERE a.source_version_id = v.id)"
                         " AND NOT EXISTS (SELECT 1 FROM corpus_memberships m WHERE m.source_version_id = v.id)")
    assert view_after == view_before, "the research's view must not show the cut upload"
    assert all(v["source_version_id"] not in {o["id"] for o in orphans}
               for entry in library["entries"] for v in entry["versions"]), "the library must not list the cut upload"
    partials = [p.name for p in papers_files(data) if p.suffix == ".partial"]
    unreferenced = [p.name for p in papers_files(data) if p.suffix == ".pdf" and count(data, "source_assets", "storage_path = ?", (p.name,)) == 0]
    print("F02 passage write: works", works_before, "->", works_after, "source_versions", versions_before, "->", versions_after,
          "orphan source rows:", len(orphans), "| .partial left:", partials, "| unreferenced .pdf left:", [n[:12] for n in unreferenced])
    assert versions_after - versions_before == len(orphans) <= 1 and works_after - works_before == len(orphans)
    assert unreferenced == [b_sha + ".pdf"] and partials == []

    # The same file again, no gate: it is stored as a fresh upload and reads like one made in a clean library.
    again = upload(c, rid, "b.pdf", pdf_b)
    assert again.status_code == 201, again.text
    got = count(data, "passages", "asset_id IN (SELECT id FROM source_assets WHERE sha256 = ?)", (b_sha,))
    assert count(data, "source_assets", "sha256 = ?", (b_sha,)) == 1
    clean = harness.start_server(other, "clean")
    rid2 = create_research(clean.client, "attached")
    assert upload(clean.client, rid2, "b.pdf", pdf_b).status_code == 201
    expected = count(other, "passages", "asset_id IN (SELECT id FROM source_assets WHERE sha256 = ?)", (b_sha,))
    assert got == expected > 0, (got, expected)
    assert_library_sound(data)
    second.no_network()
    clean.no_network()
