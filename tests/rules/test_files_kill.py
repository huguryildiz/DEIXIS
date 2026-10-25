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
from process_harness import ASSET_COLUMNS, PASSAGE_COLUMNS, count, create_research, digest, foreign_key_check, harness, integrity_check, papers_files, rows, upload, wait_for
from helpers import make_pdf

pytestmark = pytest.mark.process


def assert_library_sound(data) -> None:
    assert integrity_check(data) == "ok"
    assert foreign_key_check(data) == []


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
