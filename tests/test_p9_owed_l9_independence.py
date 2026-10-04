"""Synthetic migrated libraries only; no server, provider, or model calls."""

import json
from pathlib import Path
import shutil
import sqlite3
import subprocess

import pytest

from deixis.storage import db
from deixis.workflow.store import Store
from scripts.p9_owed import funnel_counts as copies
from scripts.p9_owed import l9_independence as kit


class Library:
    def __init__(self, path):
        self.path = path
        self.conn = db.connect(path / "library.sqlite")
        db.migrate(self.conn)
        self.store = Store(self.conn)
        self.rid = self.store.create_research("SYNTHETIC L9", "academic", "standard", [], "fake", "m", "en")

    def source(self, sid, work=None, included=False, member=True):
        wid = work or sid
        self.conn.execute("INSERT OR IGNORE INTO works(id,created_at) VALUES (?,?)", (wid, db.now()))
        self.conn.execute("INSERT INTO source_versions(id,work_id,title,origin,created_at) VALUES (?,?,?,'provider',?)",
                          (sid, wid, "SYNTHETIC " + sid, db.now()))
        if member:
            self.store.add_to_corpus(self.rid, sid, "library")
        if included:
            version = self.conn.execute("SELECT version FROM selections WHERE research_id=? AND source_version_id=?",
                                        (self.rid, sid)).fetchone()[0]
            self.store.set_user_selection(self.rid, sid, "included", version, "SYNTHETIC")
        return sid

    def identifier(self, sid, scheme, value):
        if scheme == "doi_field":
            self.conn.execute("UPDATE source_versions SET doi=? WHERE id=?", (value, sid))
        else:
            self.conn.execute("INSERT INTO identifier_mappings(source_version_id,scheme,value,provider,retrieved_at)"
                              " VALUES (?,?,?,'synthetic',?)", (sid, scheme, value, db.now()))

    def seal(self):
        self.conn.close()
        destination = self.path.with_name(self.path.name + "-copy")
        shutil.copytree(self.path, destination)
        source = copies.manifest(self.path)
        copied = copies.manifest(destination)
        assert source == copied
        copies.write_json(copies.copy_record_path(destination), {"source": str(self.path.resolve()),
            "destination": str(destination.resolve()), "usable": True,
            "source_manifest": source, "source_after_manifest": source, "copy_manifest": copied})
        self.path = destination
        return self.path


@pytest.fixture
def lib(tmp_path):
    library = Library(tmp_path / "new")
    yield library
    library.conn.close()


def references(tmp_path, works=None):
    paths = []
    for label in kit.REQUIRED_INVENTORIES:
        body = kit.inventory_body(label, "SYNTHETIC reference", {"synthetic": True}, works or [])
        if label == "tracked-docs":
            body["exclude_path_prefixes"] = list(kit.L9_DOC_EXCLUSIONS)
            body["excluded_paths"] = [{"path": p, "git_blob": "a" * 40,
                                       "reason": kit.L9_DOC_EXCLUSION_REASON} for p in kit.L9_DOC_EXCLUSIONS]
        path = tmp_path / (label.replace(" ", "-") + ".json")
        copies.write_json(path, kit.seal(body))
        paths.append(path)
    return paths


@pytest.mark.parametrize("scheme,new,old", [
    ("doi_field", "https://doi.org/10.1234/ABC", "10.1234/abc"),
    ("doi", "doi:10.1234/ABC", "10.1234/abc"),
    ("published_doi", "https://dx.doi.org/10.1234/ABC", "10.1234/abc"),
    ("linked_doi", "10.1234/ABC", "10.1234/abc"),
    ("arxiv", "https://arxiv.org/abs/2006.11239v12", "arXiv:2006.11239v1"),
    ("arxiv", "https://arxiv.org/pdf/hep-th/9901001v3.pdf", "hep-th/9901001"),
    ("openalex", "https://openalex.org/w12345678", "W12345678"),
    ("pmid", "https://pubmed.ncbi.nlm.nih.gov/12345678/", "PMID:12345678"),
])
def test_overlap_on_second_version_through_every_scheme(lib, tmp_path, scheme, new, old):
    lib.source("head", work="w", included=True)
    # Not a member, no PDF: must still participate in K0.
    lib.source("second", work="w", member=False)
    lib.identifier("second", scheme, new)
    path = lib.seal()
    reference = Library(tmp_path / "reference")
    reference.source("reference-head", work="old-work")
    reference.source("reference-second", work="old-work", member=False)
    reference.identifier("reference-second", "doi" if scheme == "doi_field" else scheme, old)
    inventory = kit.build_inventory(reference.seal(), "H9 Q1", "SYNTHETIC")
    paths = references(tmp_path)
    copies.write_json(paths[1], inventory)
    before = copies.manifest(path)
    result = kit.check(path, paths)
    assert result["K0"] == "fail"
    work = result["researches"][0]["included_works"][0]
    assert work["work_id"] == "w"
    assert len(work["versions"]) == 2
    assert work["matches"][0]["inventory"] == "H9 Q1"
    assert work["matches"][0]["source_version_id"] == "reference-second"
    assert copies.manifest(path) == before
    assert kit.main(["check", "--library", str(path), "--inventories", ",".join(map(str, paths)),
                     "--out", str(tmp_path / "fail.json")]) == 1


def test_inventory_accounts_for_missing_ids_unknown_schemes_and_uploads(lib, tmp_path):
    lib.source("unknown", included=True)
    lib.identifier("unknown", "undocumented", "not-an-audited-id")
    lib.identifier("unknown", "doi", "invalid-doi")
    lib.source("no-ids", included=True)
    lib.source("known", included=True)
    lib.identifier("known", "published_doi", "10.1234/Known")
    lib.conn.execute("INSERT INTO source_assets(id,source_version_id,sha256,byte_size,media_type,storage_path,retrieved_at,origin,extraction_status,extraction_version)"
                     " VALUES ('a','unknown',?,1,'application/pdf','synthetic.pdf',?,'user_upload','pending','synthetic-v1')", ("a" * 64, db.now()))
    path = lib.seal()
    before = copies.manifest(path)
    result = kit.build_inventory(path, "L9 NLP", "SYNTHETIC all works")
    assert result["sha256"] == kit.seal(result)["sha256"]
    assert result["provenance"]["manifest_sha256"] == before["sha256"]
    assert result["accounting"] == {"works": 3, "source_versions": 3,
        "independence_unverified_works": 2, "independence_unverified_versions": 2,
        "not_audited_identifier_records": 2, "not_audited_upload_hash_records": 1}
    assert result["schemes_present"] == ["doi", "published_doi", "undocumented"]
    checked = kit.check(path, references(tmp_path))
    assert checked["K0"] == "unverified"
    assert checked["statement"] == kit.NO_OVERLAP
    assert checked["accounting"]["independence_unverified_works"] == 2
    assert sum(w["assessment"] == kit.UNVERIFIED for w in checked["researches"][0]["included_works"]) == 2
    assert copies.manifest(path) == before


def test_no_overlap_retains_order_without_pdf_filter_or_limit(lib, tmp_path):
    for index in range(17):
        sid = f"s{index:02d}"
        lib.source(sid, included=True)
        lib.identifier(sid, "pmid", str(index + 1))
    # Equal selection timestamps exercise Store.included_sources' tie breaker.
    lib.conn.execute("UPDATE selections SET updated_at='2026-01-01T00:00:00Z'")
    expected = lib.store.included_works(lib.rid)
    result = kit.check(lib.seal(), references(tmp_path))
    assert result["K0"] == "no_overlap_detected"
    assert result["statement"] == "no overlap detected within recorded inventories"
    assert [w["head_source_version_id"] for w in result["researches"][0]["included_works"]] == expected
    assert result["accounting"]["included_works"] == 17


@pytest.mark.parametrize("problem", ["absent-label", "absent-file", "method_unavailable", "tampered", "bad-version-union"])
def test_missing_or_unusable_inventory_stops(lib, tmp_path, problem):
    lib.source("head", included=True)
    path = lib.seal()
    paths = references(tmp_path)
    if problem == "absent-label":
        paths = paths[:-1]
    elif problem == "absent-file":
        paths.append(tmp_path / "does-not-exist.json")
    else:
        body = json.loads(paths[0].read_text())
        if problem == "method_unavailable":
            body["status"] = "method_unavailable"
        elif problem == "bad-version-union":
            body["works"] = [{"work_id": "x", "versions": [], "identifiers": ["pmid:42"]}]
        else:
            body["covered_corpora"] = "tampered"
        copies.write_json(paths[0], body if problem == "tampered" else kit.seal(body))
    out = tmp_path / "stopped.json"
    rc = kit.main(["check", "--library", str(path), "--inventories", ",".join(map(str, paths)), "--out", str(out)])
    assert rc == 1
    result = json.loads(out.read_text())
    assert result["status"] == "stopped"
    assert "K0" not in result


@pytest.mark.parametrize("mode", ["missing", "unusable", "changed-manifest", "owner-source"])
def test_copy_record_refusal(lib, tmp_path, mode):
    path = lib.seal()
    sidecar = copies.copy_record_path(path)
    if mode == "missing":
        sidecar.unlink()
    elif mode == "changed-manifest":
        (path / "unexpected.txt").write_text("SYNTHETIC changed copy")
    else:
        record = json.loads(sidecar.read_text())
        record["usable" if mode == "unusable" else "source"] = False if mode == "unusable" else "/never-read/owner-backup/data"
        copies.write_json(sidecar, record)
    with pytest.raises(kit.Refused):
        kit.build_inventory(path, "L9 NLP", "SYNTHETIC")


def test_owner_backup_refusal_before_filesystem_access(tmp_path):
    for path in (Path("/does-not-exist/owner-backup/data"), Path("OWNER-BACKUP.json")):
        with pytest.raises(kit.Refused, match="owner-backup"):
            kit.safe_path(path)
    assert kit.main(["check", "--library", "/owner-backup/data", "--inventories", "none",
                     "--out", str(tmp_path / "out.json")]) == 1


def test_readonly_immutable_uri_and_no_writes(lib, tmp_path, monkeypatch):
    path = lib.seal()
    real_connect = sqlite3.connect
    uris = []
    def connect(database, **kwargs):
        uris.append(database)
        assert database.endswith("?mode=ro&immutable=1")
        return real_connect(database, **kwargs)
    monkeypatch.setattr(sqlite3, "connect", connect)
    before = copies.manifest(path)
    kit.build_inventory(path, "L9 NLP", "SYNTHETIC")
    assert len(uris) == 1
    assert copies.manifest(path) == before


@pytest.fixture
def doc_repo(tmp_path):
    repo = tmp_path / "synthetic-git"
    repo.mkdir()
    def git(*args):
        return subprocess.run(["git", "-c", "user.name=huguryildiz", "-c", "user.email=synthetic@example.invalid",
            "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args],
            cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    git("init")
    files = {
        "README.md": "[DOI](https://doi.org/10.1234/ABC). doi:10.1234/ABC;\n",
        "STATUS.md": "arXiv:2006.11239v12 https://arxiv.org/pdf/2006.11239v2.pdf\n",
        "docs/direct.md": "10.48550/arxiv.<id> 10.5555/H5.<n> 10.48550/arxiv\n",
        "docs/nested/deeper/evidence.md": (
            "10.1234/ABC, https://dx.doi.org/10.9999/NEW: [10.1111/xyz]\n"
            "https://arxiv.org/pdf/hep-th/9901001v3.pdf arXiv:hep-th/9901001v2\n"
            "https://openalex.org/w12345678 W12345678 W1 W123 W700\n"
            "res_4FxDPeGkCoCq4DgQTUi8 res_x res_WXhs res_4FxDPeGkCoCq4DgQTUi8X\n"
            "PMID:12345678 https://pubmed.ncbi.nlm.nih.gov/12345678/\n"),
        "tests/fixtures/not-scanned.md": "10.2222/fixture arXiv:1111.11111 W99999999\n",
        "docs/not-markdown.txt": "10.3333/text\n",
        "other.md": "10.4444/other\n",
        kit.L9_DOC_EXCLUSIONS[0]: "SYNTHETIC frozen G: W22345678\n",
        kit.L9_DOC_EXCLUSIONS[1]: "SYNTHETIC results G: W22345678\n",
        "docs/product/p9-owed-l9-ek-l1.json": '{"G": "W33345678"}\n',
    }
    for name, text in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "Synthetic scan fixture")
    revision = git("rev-parse", "HEAD")
    # Dirty tracked files, staged additions and untracked files must not affect
    # a scan of a fixed historical tree, even after another commit.
    (repo / "README.md").write_text("10.7777/dirty\n")
    (repo / "docs/direct.md").unlink()
    (repo / "docs/staged.md").write_text("10.8888/staged\n")
    git("add", "docs/staged.md")
    git("commit", "-m", "Synthetic later tree")
    (repo / "docs/untracked.md").write_text("10.6666/untracked\n")
    return repo, revision


def doc_reference(tmp_path, revision):
    expected = {
        "source": f"tracked docs/*.md, README.md, STATUS.md at {revision[:7]}",
        "files": 6,
        "doi": ["10.1111/xyz", "10.1234/abc", "10.48550/arxiv", "10.48550/arxiv.<id",
                "10.5555/h5.<n", "10.9999/new"],
        "arxiv": ["2006.11239", "hep-th/9901001"],
        "openalex_work": ["W12345678", "W22345678"],
        "research_ids": ["res_4FxDPeGkCoCq4DgQTUi8"],
        "not_covered": ["uploaded file SHA-256 of old corpora (not in docs)",
                        "old identifiers not written in docs", "provider ids other than OpenAlex W ids"],
    }
    path = tmp_path / "synthetic-doc-reference.json"
    copies.write_json(path, expected)
    return path, expected


def test_doc_inventory_git_blobs_recursive_rules_and_calibration(doc_repo, tmp_path):
    repo, revision = doc_repo
    reference, expected = doc_reference(tmp_path, revision)
    raw = reference.read_bytes()
    result = kit.build_doc_inventory(repo, revision, reference)
    assert result["status"] == "recorded"
    assert {k: result[k] for k in kit.DOC_FIELDS} == expected
    assert result["provenance"]["commit"] == revision
    assert result["sha256"] == kit.seal(result)["sha256"]
    assert {d["path"] for d in result["documents"]} == {
        "README.md", "STATUS.md", "docs/direct.md", "docs/nested/deeper/evidence.md", *kit.L9_DOC_EXCLUSIONS}
    calibration = result["calibration"]
    assert calibration["equal"] is True
    assert calibration["differences"] == {}
    assert calibration["counts"]["files"] == {"actual": 6, "expected": 6, "delta": 0}
    assert calibration["counts"]["doi"] == {"actual": 6, "expected": 6, "missing": 0, "extra": 0}
    assert calibration["counts"]["arxiv"] == {"actual": 2, "expected": 2, "missing": 0, "extra": 0}
    assert calibration["counts"]["openalex_work"] == {"actual": 2, "expected": 2, "missing": 0, "extra": 0}
    assert calibration["counts"]["research_ids"] == {"actual": 1, "expected": 1, "missing": 0, "extra": 0}
    assert reference.read_bytes() == raw
    assert "calibration" not in kit.build_doc_inventory(repo, revision)
    assert kit.build_doc_inventory(repo, revision[:7], reference) == result
    paths = references(tmp_path)
    copies.write_json(paths[0], result)
    assert kit.load_inventories(paths)[0]["works"]
    assert all(not i.startswith(("res_", "pmid:")) for w in result["works"] for i in w["identifiers"])
    out = tmp_path / "docs.json"
    assert kit.main(["build-doc-inventory", "--repo", str(repo), "--commit", revision,
        "--calibrate-against", str(reference), "--out", str(out)]) == 0
    assert json.loads(out.read_text()) == result


@pytest.mark.parametrize("problem", ["ids", "files", "source", "not-covered", "order"])
def test_doc_inventory_calibration_difference_fails_closed(doc_repo, tmp_path, problem):
    repo, revision = doc_repo
    path, expected = doc_reference(tmp_path, revision)
    if problem == "ids":
        expected["doi"].remove("10.1234/abc")
        expected["doi"].append("10.9999/missing")
    elif problem == "files":
        expected["files"] += 1
    elif problem == "source":
        expected["source"] = "different source"
    elif problem == "not-covered":
        expected["not_covered"] = ["different coverage"]
    else:
        expected["doi"].reverse()
    copies.write_json(path, expected)
    out = tmp_path / "diff.json"
    assert kit.main(["build-doc-inventory", "--repo", str(repo), "--commit", revision,
        "--calibrate-against", str(path), "--out", str(out)]) == 1
    result = json.loads(out.read_text())
    assert result["status"] == "method_unavailable"
    assert result["calibration"]["equal"] is False
    assert result["calibration"]["differences"]
    if problem == "ids":
        assert result["calibration"]["counts"]["doi"] == {"actual": 6, "expected": 6, "missing": 1, "extra": 1}
        assert result["calibration"]["differences"]["doi"]["missing"] == ["10.9999/missing"]
        assert result["calibration"]["differences"]["doi"]["extra"] == ["10.1234/abc"]
        assert "10.9999/missing" not in result["doi"]
    assert result["not_covered"] == kit.DOC_NOT_COVERED
    paths = references(tmp_path)
    copies.write_json(paths[0], result)
    with pytest.raises(kit.Refused, match="method_unavailable"):
        kit.load_inventories(paths)


def test_doc_inventory_calibration_input_cannot_be_overwritten(doc_repo, tmp_path):
    repo, revision = doc_repo
    reference, _ = doc_reference(tmp_path, revision)
    raw = reference.read_bytes()
    assert kit.main(["build-doc-inventory", "--repo", str(repo), "--commit", revision,
        "--calibrate-against", str(reference), "--out", str(reference)]) == 1
    assert reference.read_bytes() == raw


def test_doc_inventory_scanned_identifier_establishes_recorded_overlap(lib, doc_repo, tmp_path):
    repo, revision = doc_repo
    paths = references(tmp_path)
    copies.write_json(paths[0], kit.build_doc_inventory(repo, revision,
                                                      exclude_path_prefixes=kit.L9_DOC_EXCLUSIONS))
    lib.source("head", included=True)
    lib.identifier("head", "published_doi", "https://doi.org/10.1234/ABC")
    result = kit.check(lib.seal(), paths)
    assert result["K0"] == "fail"
    assert result["accounting"]["overlapping_works"] == 1
    matches = result["researches"][0]["included_works"][0]["matches"]
    assert {m["inventory"] for m in matches} == {"tracked-docs"}
    assert {m["identifier"] for m in matches} == {"doi:10.1234/abc"}
    assert len(matches) == 2  # README and the nested document retain separate provenance.
    assert all(m["source_version_id"].startswith("git-document:" + revision) for m in matches)


def test_output_cannot_modify_library_or_inventory(lib, tmp_path):
    path = lib.seal()
    paths = references(tmp_path)
    before = copies.manifest(path)
    assert kit.main(["build-inventory", "--library", str(path), "--label", "L9 NLP", "--corpora", "SYNTHETIC",
                     "--out", str(path / "bad.json")]) == 1
    raw = paths[0].read_bytes()
    assert kit.main(["check", "--library", str(path), "--inventories", ",".join(map(str, paths)),
                     "--out", str(paths[0])]) == 1
    assert paths[0].read_bytes() == raw
    sidecar = copies.copy_record_path(path)
    record = sidecar.read_bytes()
    assert kit.main(["build-inventory", "--library", str(path), "--label", "L9 NLP", "--corpora", "SYNTHETIC",
                     "--out", str(sidecar)]) == 1
    assert sidecar.read_bytes() == record
    assert copies.manifest(path) == before


def test_l9_self_reference_exclusions_are_recorded_and_visible(lib, doc_repo, tmp_path):
    repo, revision = doc_repo
    full = kit.build_doc_inventory(repo, revision)
    assert "W22345678" in full["openalex_work"]
    assert full["excluded_paths"] == []
    out = tmp_path / "l9-docs.json"
    args = ["build-doc-inventory", "--repo", str(repo), "--commit", revision, "--out", str(out)]
    for prefix in kit.L9_DOC_EXCLUSIONS:
        args.extend(["--exclude-path-prefix", prefix])
    assert kit.main(args) == 0
    result = json.loads(out.read_text())
    assert result["files"] == full["files"] - 2
    assert result["openalex_work"] == ["W12345678"]
    assert result["sha256"] == kit.seal(result)["sha256"]
    assert result["excluded_paths"] == [{"path": p,
        "git_blob": kit.git(repo, "rev-parse", f"{revision}:{p}").decode().strip(),
        "reason": kit.L9_DOC_EXCLUSION_REASON} for p in kit.L9_DOC_EXCLUSIONS]
    assert "W33345678" not in full["openalex_work"]  # JSON is outside Markdown scope.
    assert not any(c["path"] in kit.L9_DOC_EXCLUSIONS for c in result["identity_candidates"])
    paths = references(tmp_path)
    copies.write_json(paths[0], result)
    lib.source("g", included=True)
    lib.identifier("g", "openalex", "W22345678")
    library = lib.seal()
    checked = kit.check(library, paths)
    assert checked["K0"] == "no_overlap_detected"
    assert checked["excluded_paths"] == result["excluded_paths"]
    assert checked["exclude_path_prefixes"] == list(kit.L9_DOC_EXCLUSIONS)
    output = tmp_path / "checked.json"
    assert kit.main(["check", "--library", str(library), "--inventories", ",".join(map(str, paths)),
                     "--out", str(output)]) == 0
    assert json.loads(output.read_text())["excluded_paths"] == result["excluded_paths"]


def test_g_reference_in_retained_document_still_fails_k0(lib, doc_repo, tmp_path):
    repo, revision = doc_repo
    paths = references(tmp_path)
    body = kit.build_doc_inventory(repo, revision, exclude_path_prefixes=kit.L9_DOC_EXCLUSIONS)
    copies.write_json(paths[0], body)
    lib.source("g", included=True)
    lib.identifier("g", "openalex", "W12345678")
    result = kit.check(lib.seal(), paths)
    assert result["K0"] == "fail"
    assert {m["inventory"] for m in result["researches"][0]["included_works"][0]["matches"]} == {"tracked-docs"}


@pytest.mark.parametrize("problem", ["absent", "none", "missing", "extra", "duplicate", "broad-prefix",
                                         "reason", "blob", "scanned", "candidate", "version"])
def test_l9_check_refuses_changed_exclusion_scope(lib, tmp_path, problem):
    paths = references(tmp_path)
    body = json.loads(paths[0].read_text())
    if problem == "absent":
        del body["excluded_paths"]
    elif problem == "none":
        body["excluded_paths"] = []
        body["exclude_path_prefixes"] = []
    elif problem == "missing":
        body["excluded_paths"].pop()
    elif problem == "extra":
        body["excluded_paths"].append({"path": "docs/other.md", "git_blob": "b" * 40,
                                       "reason": kit.L9_DOC_EXCLUSION_REASON})
    elif problem == "duplicate":
        body["excluded_paths"][1] = body["excluded_paths"][0]
    elif problem == "broad-prefix":
        body["exclude_path_prefixes"] = ["docs/"]
    elif problem in {"reason", "blob"}:
        body["excluded_paths"][0]["reason" if problem == "reason" else "git_blob"] = "wrong"
    elif problem in {"scanned", "candidate"}:
        body["documents" if problem == "scanned" else "identity_candidates"] = [{"path": kit.L9_DOC_EXCLUSIONS[0]}]
    else:
        body["works"] = [{"work_id": "synthetic", "identifiers": [], "versions": [
            {"source_version_id": "synthetic", "identifiers": [], "document_path": kit.L9_DOC_EXCLUSIONS[0]}]}]
    # Reseal: scope enforcement must catch deliberate narrowing, not only bad hashes.
    copies.write_json(paths[0], kit.seal(body))
    out = tmp_path / "scope-stopped.json"
    assert kit.main(["check", "--library", str(lib.path), "--inventories", ",".join(map(str, paths)),
                     "--out", str(out)]) == 1
    stopped = json.loads(out.read_text())
    assert stopped["status"] == "stopped"
    assert "K0" not in stopped
    assert "exclu" in stopped["reason"]


def test_generic_prefix_builder_records_all_matches_but_l9_refuses(doc_repo):
    repo, revision = doc_repo
    body = kit.build_doc_inventory(repo, revision, exclude_path_prefixes=["docs/"])
    assert body["files"] == 2
    assert len(body["excluded_paths"]) == 4
    with pytest.raises(kit.Refused, match="fixed L9 set"):
        kit.validate_l9_doc_exclusions(body)


@pytest.mark.parametrize("prefix", ["", "/docs/", "../docs/", "docs/../", "docs//", "./docs", "docs\\"])
def test_invalid_doc_exclusion_prefix_refused(doc_repo, prefix):
    repo, revision = doc_repo
    with pytest.raises(kit.Refused, match="repository-relative"):
        kit.build_doc_inventory(repo, revision, exclude_path_prefixes=[prefix])


@pytest.mark.parametrize("index", range(4))
def test_each_required_inventory_is_mandatory(tmp_path, index):
    paths = references(tmp_path)
    paths.pop(index)
    with pytest.raises(kit.Refused, match="required inventories missing"):
        kit.load_inventories(paths)


def test_nonempty_wal_refused_without_writable_fallback(lib):
    lib.conn.close()
    (lib.path / "library.sqlite-wal").write_bytes(b"SYNTHETIC nonempty WAL")
    path = lib.seal()
    with pytest.raises(kit.Refused, match="nonempty WAL"):
        kit.build_inventory(path, "L9 NLP", "SYNTHETIC")


def test_unknown_hash_mapping_never_qualifies_as_identity(lib):
    lib.source("hash-only")
    lib.identifier("hash-only", "sha256", "a" * 64)
    result = kit.build_inventory(lib.seal(), "L9 NLP", "SYNTHETIC")
    assert result["accounting"]["independence_unverified_works"] == 1
    assert result["accounting"]["not_audited_identifier_records"] == 1
    assert result["works"][0]["identifiers"] == []
