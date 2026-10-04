"""Offline L9 K0 inventories. K1 remains measure_lineage.py's `rows` command.

Library inputs must be sealed byte copies under funnel_counts' copy-record rule.
The required reference set is fixed; identifiers establish only recorded overlap,
never semantic independence or absence from undocumented development corpora.
Inventory SHA-256 covers canonical JSON excluding the `sha256` member itself.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from scripts.p9_owed import funnel_counts as copies
from deixis.workflow.store import Store

REQUIRED_INVENTORIES = ("tracked-docs", "H9 Q1", "H9b B Q3", "L9 NLP")
SCHEMES = ("doi", "arxiv", "openalex", "pmid")
DOI_FAMILY = ("doi", "published_doi", "linked_doi")
UNVERIFIED = "bağımsızlık doğrulanmadı"
NO_OVERLAP = "no overlap detected within recorded inventories"
Refused = copies.MeasurementRefused


def safe_path(path: Path) -> Path:
    path = Path(path)
    if "owner-backup" in str(path.absolute()).casefold():
        raise Refused("owner-backup path refused")
    if "owner-backup" in str(path.resolve()).casefold():
        raise Refused("owner-backup path refused")
    return path


def identity(scheme: str, value: str) -> str | None:
    """Only documented bibliographic namespaces qualify as usable identities."""
    scheme = scheme.strip().casefold()
    value = value.strip()
    if scheme in DOI_FAMILY:
        scheme = "doi"
        value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value, flags=re.I).casefold()
        valid = re.fullmatch(r"10\.\d{4,9}/\S+", value)
    elif scheme == "arxiv":
        value = re.sub(r"^(?:https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/|arxiv:\s*)", "", value, flags=re.I)
        value = re.sub(r"\.pdf$", "", value, flags=re.I)
        value = re.sub(r"v\d+$", "", value.casefold())
        valid = re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-z][a-z.\-]*/\d{7})", value)
    elif scheme == "openalex":
        value = re.sub(r"^https?://(?:www\.)?openalex\.org/", "", value, flags=re.I).upper()
        valid = re.fullmatch(r"W\d+", value)
    elif scheme == "pmid":
        value = re.sub(r"^(?:https?://pubmed\.ncbi\.nlm\.nih\.gov/|pmid:\s*)", "", value, flags=re.I).rstrip("/")
        valid = re.fullmatch(r"[1-9]\d*", value)
    else:
        return None
    return f"{scheme}:{value}" if valid else None


def seal(value: dict) -> dict:
    body = {k: v for k, v in value.items() if k != "sha256"}
    return body | {"sha256": hashlib.sha256(copies.canonical(body)).hexdigest()}


@contextmanager
def library_copy(path: Path):
    root = copies.checked_dir(safe_path(path))
    record_path = copies.outside(safe_path(copies.copy_record_path(root)), root)
    if not record_path.is_file():
        raise Refused("copy record is missing; original libraries cannot be read")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise Refused("copy record must be an object")
    for key in ("source", "destination"):
        if not isinstance(record.get(key), str):
            raise Refused(f"copy record missing {key}")
        # Only inspect the record's text, never stat/resolve/read its source.
        if "owner-backup" in record[key].casefold():
            raise Refused("owner-backup path refused")
    current = copies.manifest(root)
    if (record.get("usable") is not True or record.get("destination") != str(root)
            or record.get("source") == str(root)
            or record.get("source_manifest") != current
            or record.get("source_after_manifest") != current
            or record.get("copy_manifest") != current):
        raise Refused("copy record/manifest does not establish a usable copy")
    with copies.open_readonly(root) as conn:
        yield conn, {"library_path": str(root), "manifest_sha256": current["sha256"],
                     "copy_record_path": str(record_path),
                     "copy_record_sha256": hashlib.sha256(record_path.read_bytes()).hexdigest()}
    if copies.manifest(root) != current:
        raise Refused("copy changed during inventory read")


def work_inventory(conn: sqlite3.Connection) -> list[dict]:
    versions = {}
    for row in conn.execute("SELECT * FROM source_versions ORDER BY work_id, id"):
        versions[row["id"]] = {"source_version_id": row["id"], "work_id": row["work_id"],
            "title": row["title"], "version_label": row["version_label"], "identifiers": [],
            "schemes_present": [], "unusable_identifiers": [], "upload_hashes": []}
        # Read DOI-family fields too if a historical schema has them.
        for scheme in DOI_FAMILY:
            if scheme in row.keys() and row[scheme]:
                add_identifier(versions[row["id"]], scheme, row[scheme])
    for row in conn.execute("SELECT source_version_id, scheme, value FROM identifier_mappings ORDER BY id"):
        add_identifier(versions[row["source_version_id"]], row["scheme"], row["value"])
    for row in conn.execute("SELECT source_version_id, sha256 FROM source_assets WHERE origin='user_upload' ORDER BY id"):
        versions[row["source_version_id"]]["upload_hashes"].append(row["sha256"])
    works = {row["id"]: {"work_id": row["id"], "versions": [], "identifiers": []}
             for row in conn.execute("SELECT id FROM works ORDER BY id")}
    for version in versions.values():
        version["identifiers"] = sorted(set(version["identifiers"]))
        version["schemes_present"] = sorted(set(version["schemes_present"]))
        present = {i.split(":", 1)[0] for i in version["identifiers"]}
        version["missing_dimensions"] = [s for s in SCHEMES if s not in present]
        version["independence_unverified"] = not version["identifiers"]
        works[version["work_id"]]["versions"].append(version)
    for work in works.values():
        work["identifiers"] = sorted({i for v in work["versions"] for i in v["identifiers"]})
        work["independence_unverified"] = not work["identifiers"]
    return list(works.values())


def add_identifier(version: dict, scheme: str, value: str) -> None:
    version["schemes_present"].append(scheme)
    usable = identity(scheme, value)
    if usable:
        version["identifiers"].append(usable)
    else:
        version["unusable_identifiers"].append({"scheme": scheme, "value": value, "status": "not_audited"})


def inventory_body(label: str, corpora: str, provenance: dict, works: list[dict]) -> dict:
    versions = [v for w in works for v in w["versions"]]
    return {"version": 1, "kind": "l9_independence_inventory", "label": label,
        "status": "recorded", "covered_corpora": corpora, "provenance": provenance, "works": works,
        "schemes_present": sorted({s for v in versions for s in v["schemes_present"]}),
        "usable_schemes": sorted({i.split(":", 1)[0] for w in works for i in w["identifiers"]}),
        "accounting": {"works": len(works), "source_versions": len(versions),
            "independence_unverified_works": sum(w["independence_unverified"] for w in works),
            "independence_unverified_versions": sum(v["independence_unverified"] for v in versions),
            "not_audited_identifier_records": sum(len(v["unusable_identifiers"]) for v in versions),
            "not_audited_upload_hash_records": sum(len(v["upload_hashes"]) for v in versions)},
        "missing_dimensions": [
            {"dimension": "upload_hash_identity", "status": "not_audited",
             "reason": "Upload hashes are recorded separately; they are not bibliographic identities."},
            {"dimension": "undocumented_identifiers", "status": "not_audited",
             "reason": "Identifiers absent from stored records cannot be reconstructed."},
            {"dimension": "missing_identifier_schemes_by_version", "status": "recorded",
             "counts": dict(Counter(s for v in versions for s in v["missing_dimensions"]))}],
        "scope": "Every stored work and every source version, including versions outside active corpus memberships."}


def build_inventory(path: Path, label: str, corpora: str) -> dict:
    if not label.strip() or not corpora.strip():
        raise Refused("label and covered corpora must be nonempty")
    with library_copy(path) as (conn, provenance):
        body = inventory_body(label, corpora, provenance, work_inventory(conn))
        body["provenance"]["researches"] = [dict(r) for r in conn.execute(
            "SELECT id FROM researches ORDER BY created_at, id")]
    return seal(body)


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


DOC_NOT_COVERED = [
    "uploaded file SHA-256 of old corpora (not in docs)",
    "old identifiers not written in docs",
    "provider ids other than OpenAlex W ids",
]
DOC_FIELDS = ("source", "files", "doi", "arxiv", "openalex_work", "research_ids", "not_covered")
L9_DOC_EXCLUSIONS = (
    "docs/product/p9-owed-measurements-freeze.md",
    "docs/product/p9-owed-measurements-results.md",
)
L9_DOC_EXCLUSION_REASON = "self-reference: L9 addendum names its own frozen G works"


def calibrate_doc_inventory(body: dict, path: Path) -> dict:
    """Compare the H9 projection, including exact lists, without importing IDs."""
    path = safe_path(path)
    raw = path.read_bytes()
    expected = json.loads(raw)
    if not isinstance(expected, dict) or any(k not in expected for k in DOC_FIELDS):
        raise Refused("calibration artifact missing tracked-docs fields")
    differences, counts = {}, {}
    for key in DOC_FIELDS:
        actual, reference = body[key], expected[key]
        if isinstance(actual, list):
            if not isinstance(reference, list) or any(not isinstance(v, str) for v in reference):
                raise Refused(f"calibration artifact has invalid {key}")
            missing, extra = sorted(set(reference) - set(actual)), sorted(set(actual) - set(reference))
            counts[key] = {"actual": len(actual), "expected": len(reference),
                           "missing": len(missing), "extra": len(extra)}
            if actual != reference:
                differences[key] = {"missing": missing, "extra": extra, "exact_list_equal": False}
        else:
            if key == "files":
                if type(reference) is not int:
                    raise Refused("calibration artifact has invalid files")
                counts[key] = {"actual": actual, "expected": reference, "delta": actual - reference}
            if actual != reference:
                differences[key] = {"actual": actual, "expected": reference}
    return {"equal": not differences, "reference_path": str(path.resolve()),
            "reference_sha256": hashlib.sha256(raw).hexdigest(),
            "compared_fields": list(DOC_FIELDS), "counts": counts, "differences": differences}


def build_doc_inventory(repo: Path, commit: str, calibrate_against: Path | None = None,
                        exclude_path_prefixes: list[str] | tuple[str, ...] = ()) -> dict:
    """Scan commit-owned Markdown; reference records denote lexical occurrences.

    H9 includes DOI placeholders such as ``10.48550/arxiv.<id``. Preserve that
    lexical evidence under the library normalizer; it is not DOI registration
    verification. A reference record is never a reconstructed paper/version.
    """
    repo = safe_path(repo).resolve()
    prefixes = sorted(set(exclude_path_prefixes))
    for prefix in prefixes:
        if (not prefix or prefix.startswith("/") or "\\" in prefix
                or any(part in {"", ".", ".."} for part in
                       (prefix[:-1] if prefix.endswith("/") else prefix).split("/"))):
            raise Refused("exclusion prefix must be a nonempty repository-relative path")
        safe_path(Path(prefix))
    if re.fullmatch(r"[0-9a-fA-F]{7,40}", commit) is None:
        raise Refused("commit must be a hexadecimal Git commit id")
    revision = git(repo, "rev-parse", "--verify", commit + "^{commit}").decode().strip()
    entries = git(repo, "ls-tree", "-rz", "--full-tree", revision).split(b"\0")
    documents, candidates, excluded = [], [], []
    patterns = {
        "doi": r"(?i)\b10\.\d{4,9}/[^\s>)\]}\"'`]+",
        "arxiv": r"(?i)(?:arxiv:\s*|arxiv\.org/(?:abs|pdf)/)(?:\d{4}\.\d{4,5}|[a-z][a-z.\-]*/\d{7})(?:v\d+)?",
        "openalex": r"(?i)\bW\d{6,}\b",
    }
    research_ids = set()
    for entry in entries:
        if not entry:
            continue
        metadata, name = entry.split(b"\t", 1)
        mode, kind, oid = metadata.decode().split()
        path = name.decode()
        safe_path(Path(path))
        if not (path in {"README.md", "STATUS.md"} or path.startswith("docs/") and path.endswith(".md")):
            continue
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise Refused(f"non-regular tracked document: {path}")
        if any(path.startswith(prefix) for prefix in prefixes):
            excluded.append({"path": path, "git_blob": oid, "reason": L9_DOC_EXCLUSION_REASON})
            continue
        blob = git(repo, "cat-file", "blob", oid)
        documents.append({"path": path, "git_blob": oid, "sha256": hashlib.sha256(blob).hexdigest(),
                          "byte_size": len(blob), "identity_extraction": "lexical_regex"})
        text = blob.decode("utf-8")
        research_ids.update(re.findall(r"\bres_[A-Za-z0-9]{20}\b", text))
        for number, line in enumerate(text.splitlines(), 1):
            for scheme, pattern in patterns.items():
                for match in re.finditer(pattern, line):
                    raw = match.group().rstrip(".,;:")
                    if scheme == "arxiv":
                        raw = re.sub(r"^arxiv\.org/", "https://arxiv.org/", raw, flags=re.I)
                    identifier = identity(scheme, raw)
                    if identifier:
                        candidates.append({"path": path, "line": number, "identifier": identifier})
    identifiers = sorted({c["identifier"] for c in candidates})
    works = []
    for identifier in identifiers:
        scheme = identifier.split(":", 1)[0]
        versions = [{"source_version_id": f"git-document:{revision}:{path}:{identifier}",
                     "document_path": path, "identifiers": [identifier], "schemes_present": [scheme],
                     "missing_dimensions": [s for s in SCHEMES if s != scheme],
                     "unusable_identifiers": [], "upload_hashes": [], "independence_unverified": False}
                    for path in sorted({c["path"] for c in candidates if c["identifier"] == identifier})]
        works.append({"work_id": "document-identifier:" + identifier, "versions": versions,
                      "identifiers": [identifier], "independence_unverified": False})
    body = inventory_body("tracked-docs", "Tracked docs/**/*.md, README.md and STATUS.md at the requested commit.",
        {"repository_path": str(repo), "commit": revision,
         "method": "recursive tracked Markdown regex scan of Git blobs; library identity normalization",
         "patterns": patterns, "research_id_pattern": r"\bres_[A-Za-z0-9]{20}\b"}, works)
    body.update({
        "source": f"tracked docs/*.md, README.md, STATUS.md at {revision[:7]}",
        "files": len(documents),
        "doi": [i.split(":", 1)[1] for i in identifiers if i.startswith("doi:")],
        "arxiv": [i.split(":", 1)[1] for i in identifiers if i.startswith("arxiv:")],
        "openalex_work": [i.split(":", 1)[1] for i in identifiers if i.startswith("openalex:")],
        "research_ids": sorted(research_ids), "not_covered": list(DOC_NOT_COVERED),
        "documents": documents, "identity_candidates": candidates,
        "exclude_path_prefixes": prefixes, "excluded_paths": excluded,
        "scope": "Lexical identifier occurrences in tracked Markdown only. Work/version keys are document reference records, not paper/source-version assignments. Research IDs are provenance only, not bibliographic identities.",
        "missing_dimensions": [{"dimension": d, "status": "not_audited"} for d in DOC_NOT_COVERED]})
    if excluded:
        body["scope"] += " Excluded Markdown blobs are listed in excluded_paths and contribute no identifiers."
        body["missing_dimensions"].append({"dimension": "identifiers in excluded Markdown blobs",
            "status": "not_audited", "reason": L9_DOC_EXCLUSION_REASON})
    if calibrate_against is not None:
        body["calibration"] = calibrate_doc_inventory(body, calibrate_against)
        if not body["calibration"]["equal"]:
            body["status"] = "method_unavailable"
            body["reason"] = "Tracked Markdown scan differs from the supplied calibration artifact; see calibration.differences."
    return seal(body)


def reference_label(label: str) -> str:
    key = re.sub(r"[^a-z0-9]", "", label.casefold())
    return {"trackeddocs": "tracked-docs", "h9q1": "H9 Q1", "h9bbq3": "H9b B Q3",
            "h9bb": "H9b B Q3", "l9nlp": "L9 NLP"}.get(key, label)


def load_inventories(paths: list[Path]) -> list[dict]:
    inventories = []
    for path in paths:
        safe_path(path)
        item = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(item, dict) or item.get("kind") != "l9_independence_inventory"
                or item.get("version") != 1 or item.get("sha256") != seal(item)["sha256"]):
            raise Refused(f"invalid inventory/hash: {path}")
        item["inventory_file"] = str(path.resolve())
        inventories.append(item)
    if any(not isinstance(i.get("label"), str) for i in inventories):
        raise Refused("inventory missing label")
    labels = [reference_label(i.get("label", "")) for i in inventories]
    missing = set(REQUIRED_INVENTORIES) - set(labels)
    if missing:
        raise Refused("required inventories missing: " + ", ".join(sorted(missing)))
    if len(labels) != len(set(labels)):
        raise Refused("duplicate inventory labels")
    for item in inventories:
        if item.get("status") != "recorded":
            raise Refused(f"inventory {item['label']}: {item.get('status')}; check stopped")
        if (not isinstance(item.get("covered_corpora"), str) or not item["covered_corpora"].strip()
                or not isinstance(item.get("provenance"), dict)
                or not isinstance(item.get("schemes_present"), list)
                or not isinstance(item.get("missing_dimensions"), list)):
            raise Refused("inventory missing coverage/provenance")
        for key, value in item["provenance"].items():
            if key.endswith("path") and isinstance(value, str):
                safe_path(Path(value))
        if not isinstance(item.get("works"), list):
            raise Refused("inventory missing works")
        for work in item["works"]:
            if (not isinstance(work, dict) or not isinstance(work.get("work_id"), str)
                    or not isinstance(work.get("versions"), list) or not isinstance(work.get("identifiers"), list)):
                raise Refused("inventory work missing versions/identifiers")
            for version in work["versions"]:
                if (not isinstance(version, dict) or not isinstance(version.get("source_version_id"), str)
                        or not isinstance(version.get("identifiers"), list)
                        or any(not isinstance(i, str) for i in version["identifiers"])):
                    raise Refused("inventory version missing identity records")
            gathered = {i for v in work["versions"] for i in v["identifiers"]}
            if set(work["identifiers"]) != gathered:
                raise Refused("inventory work/version identity mismatch")
            for identifier in gathered:
                scheme, separator, value = identifier.partition(":")
                if not separator or identity(scheme, value) != identifier:
                    raise Refused("inventory has noncanonical identifier")
    return inventories


def validate_l9_doc_exclusions(inventory: dict) -> None:
    """Calibration can scan all docs; the L9 gate must use the frozen scope."""
    expected = set(L9_DOC_EXCLUSIONS)
    prefixes = inventory.get("exclude_path_prefixes")
    excluded = inventory.get("excluded_paths")
    if (not isinstance(prefixes, list) or any(not isinstance(p, str) for p in prefixes)
            or len(prefixes) != len(expected) or set(prefixes) != expected
            or not isinstance(excluded, list) or len(excluded) != len(expected)):
        raise Refused("tracked-docs exclusions differ from fixed L9 set: " + ", ".join(L9_DOC_EXCLUSIONS))
    for record in excluded:
        if (not isinstance(record, dict) or record.get("path") not in expected
                or record.get("reason") != L9_DOC_EXCLUSION_REASON
                or not isinstance(record.get("git_blob"), str)
                or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", record["git_blob"]) is None):
            raise Refused("tracked-docs exclusion record needs fixed path, Git blob id and self-reference reason")
    if {r["path"] for r in excluded} != expected:
        raise Refused("tracked-docs exclusions differ from fixed L9 set")
    scanned = [*inventory.get("documents", []), *inventory.get("identity_candidates", [])]
    if (any(r.get("path") in expected for r in scanned)
            or any(v.get("document_path") in expected for w in inventory["works"] for v in w["versions"])):
        raise Refused("tracked-docs excluded path also appears in scanned evidence")


def check(path: Path, inventory_paths: list[Path]) -> dict:
    safe_path(path)
    inventories = load_inventories(inventory_paths)
    docs = next(i for i in inventories if reference_label(i["label"]) == "tracked-docs")
    validate_l9_doc_exclusions(docs)
    owners = {}
    for inventory in inventories:
        for work in inventory["works"]:
            for version in work["versions"]:
                for identifier in version["identifiers"]:
                    owners.setdefault(identifier, []).append({"inventory": inventory["label"],
                        "inventory_file": inventory["inventory_file"], "inventory_sha256": inventory["sha256"],
                        "work_id": work["work_id"], "source_version_id": version["source_version_id"]})
    researches = []
    with library_copy(path) as (conn, provenance):
        works = {w["work_id"]: w for w in work_inventory(conn)}
        source_work = {v["source_version_id"]: w["work_id"] for w in works.values() for v in w["versions"]}
        store = Store(conn)
        for research in conn.execute("SELECT id FROM researches ORDER BY created_at, id"):
            included = []
            # Exactly the heads/order used by measure_lineage.selected_rows,
            # before either the PDF-text filter or row cap. No K1 duplication.
            for head in store.included_works(research["id"]):
                work = works[source_work[head]]
                matches = [{"identifier": i, **owner} for i in work["identifiers"] for owner in owners.get(i, [])]
                included.append({**work, "head_source_version_id": head, "matches": matches,
                    "assessment": "overlap" if matches else UNVERIFIED if work["independence_unverified"] else NO_OVERLAP})
            researches.append({"research_id": research["id"], "included_works": included})
    included = [w for r in researches for w in r["included_works"]]
    overlap = sum(bool(w["matches"]) for w in included)
    unverified = sum(w["independence_unverified"] for w in included)
    return {"version": 1, "K0": "fail" if overlap else "unverified" if unverified or not included else "no_overlap_detected",
        "status": "checked", "statement": "overlap detected" if overlap else NO_OVERLAP,
        "required_inventories": list(REQUIRED_INVENTORIES), "provenance": provenance,
        "exclude_path_prefixes": docs["exclude_path_prefixes"], "excluded_paths": docs["excluded_paths"],
        "inventories": [{k: i[k] for k in ("label", "inventory_file", "sha256", "covered_corpora", "schemes_present", "missing_dimensions")} for i in inventories],
        "researches": researches, "accounting": {"included_works": len(included), "overlapping_works": overlap,
            "independence_unverified_works": unverified},
        "missing_dimensions": [{"dimension": "upload_hashes and undocumented identifiers", "status": "not_audited"}],
        "K1": "Use existing scripts/p6_eval/measure_lineage.py rows; not evaluated here."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build-inventory")
    build.add_argument("--library", type=Path, required=True)
    build.add_argument("--label", required=True)
    build.add_argument("--corpora", required=True)
    doc = commands.add_parser("build-doc-inventory")
    doc.add_argument("--repo", type=Path, required=True)
    doc.add_argument("--commit", required=True)
    doc.add_argument("--calibrate-against", type=Path)
    doc.add_argument("--exclude-path-prefix", action="append", default=[],
                     help="repeatable repository-relative lexical prefix; excluded Markdown blobs remain recorded")
    chk = commands.add_parser("check")
    chk.add_argument("--library", type=Path, required=True)
    chk.add_argument("--inventories", required=True, help="comma-separated files; required labels: " + ", ".join(REQUIRED_INVENTORIES))
    for p in (build, doc, chk):
        p.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        inputs = ([safe_path(args.library), safe_path(copies.copy_record_path(args.library.resolve()))]
                  if args.command != "build-doc-inventory" else [])
        if args.command == "build-doc-inventory" and args.calibrate_against is not None:
            inputs.append(safe_path(args.calibrate_against))
        if args.command == "check":
            paths = [safe_path(Path(p.strip())) for p in args.inventories.split(",") if p.strip()]
            inputs.extend(paths)
        out = copies.outside(safe_path(args.out), *inputs)
        try:
            if args.command == "build-inventory":
                result = build_inventory(args.library, args.label, args.corpora)
            elif args.command == "build-doc-inventory":
                result = build_doc_inventory(args.repo, args.commit, args.calibrate_against,
                                             args.exclude_path_prefix)
            else:
                result = check(args.library, paths)
        except (OSError, ValueError, KeyError, TypeError, sqlite3.DatabaseError, subprocess.CalledProcessError) as exc:
            result = {"status": "stopped", "reason": str(exc)}
        copies.write_json(out, result)
        return 0 if result.get("status") in {"recorded", "checked"} and result.get("K0") not in {"fail", "unverified"} else 1
    except (OSError, ValueError) as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
