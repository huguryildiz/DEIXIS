"""Occurrence identity and deterministic text-retry policy; no file or model IO."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from deixis.documents import pdf

RECOVERY_TOKEN = "+reextract-"
DECISION_CODES = (
    "no_change", "recovered_text", "password_diagnosed", "no_text_diagnosed",
    "text_updated", "recovered_from_corrupt_input", "candidate_failed",
    "augmented_text_would_be_lost", "status_worse", "page_count_changed",
    "legacy_page_count_untrusted", "text_page_lost", "upgraded", "fewer_text_pages",
    "ocr_found_no_text", "input_not_verified",
)
STATUS_RANK = {"succeeded": 3, "partial": 2, "no_text": 1, "failed": 0}
Manifest = list[tuple[int, str | None, str | None, str, str]]


def recovery_token(version: str) -> str:
    if RECOVERY_TOKEN not in version:
        return ""
    if version.count(RECOVERY_TOKEN) != 1:
        raise ValueError("An occurrence must have at most one recovery token")
    token = re.search(r"\+reextract-([A-Za-z0-9_]+)(?=\+|$)", version)
    if token is None:
        raise ValueError("Malformed recovery token")
    return token.group(0)


def profile_of(version: str) -> str:
    token = recovery_token(version)
    return version.replace(token, "", 1) if token else version


def occurrence(profile: str, operation_id: str) -> str:
    if recovery_token(profile) or not re.fullmatch(r"[A-Za-z0-9_]+", operation_id):
        raise ValueError("Invalid recovery occurrence identity")
    return profile + RECOVERY_TOKEN + operation_id


def text_base(current_version: str | None) -> str:
    return pdf.EXTRACTION_VERSION + recovery_token(current_version or "")


def coverage_manifest(extraction: Any, chunker: Any) -> Manifest:
    """Match the first-chunk deduplication and chunk provenance of Store's writer."""
    manifest: Manifest = []
    seen: set[tuple[int, str]] = set()
    for page in extraction.pages:
        placed = getattr(page, "latex_blocks", None) or ()
        for start, end, text in chunker(page.text):
            digest = hashlib.sha256(text.encode()).hexdigest()
            key = (page.physical_page, digest)
            if key in seen:
                continue
            seen.add(key)
            source = "latex_source" if any(start <= s and e <= end for s, e, _ in placed) else getattr(page, "text_source", "text_layer")
            manifest.append((page.physical_page, page.printed_label, f"chars:{start}-{end}", digest, source))
    return manifest


def stored_manifest(conn: Any, asset_id: str, version: str) -> Manifest:
    return [tuple(row) for row in conn.execute(
        "SELECT physical_page, printed_label, payload_ref, text_sha256, text_source FROM passages"
        " WHERE asset_id = ? AND extraction_version = ? AND kind = 'pdf_page' ORDER BY rowid",
        (asset_id, version),
    )]


def pages(manifest: Manifest) -> set[int]:
    return {item[0] for item in manifest}


@dataclass(frozen=True)
class Decision:
    promote: bool
    diagnostic_only: bool
    decision_code: str
    missing_pages: list[int]
    old_coverage: Manifest
    new_coverage: Manifest


def decide(baseline: dict[str, Any], candidate: dict[str, Any]) -> Decision:
    old, new = baseline["manifest"], candidate["manifest"]
    missing = sorted(pages(old) - pages(new))

    def result(code: str, promote: bool = False, diagnostic: bool = False) -> Decision:
        return Decision(promote, diagnostic, code, missing, old, new)

    if (old == new and all(baseline[key] == candidate[key] for key in
                          ("status", "error", "page_count", "extractor_profile"))
            and baseline.get("ocr_json") is None and baseline.get("math_json") is None):
        return result("no_change")
    if baseline["passage_count"] == 0 and baseline["status"] in ("failed", "no_text"):
        if candidate["status"] in ("partial", "succeeded") and pages(new):
            return result("recovered_text", True)
        if (candidate["status"] == "failed" and candidate["error"] == pdf.ERROR_PASSWORD
                and baseline["status"] == "no_text"):
            return result("password_diagnosed", True, True)
        if candidate["status"] == "no_text":
            return result("no_text_diagnosed", True, True)
        return result("candidate_failed")
    if candidate["status"] == "failed":
        return result("candidate_failed")
    if (any(item[4] != "text_layer" for item in old)
            or baseline.get("ocr_json") is not None or baseline.get("math_json") is not None):
        return result("augmented_text_would_be_lost")
    if STATUS_RANK.get(candidate["status"], 0) < STATUS_RANK.get(baseline["status"], 0):
        return result("status_worse")
    if candidate["page_count"] != baseline["page_count"]:
        integrity = baseline.get("input_integrity")
        if integrity == "mismatch":
            return result("text_page_lost") if missing else result("recovered_from_corrupt_input", True)
        return result("page_count_changed" if integrity == "verified" else "legacy_page_count_untrusted")
    return result("text_page_lost") if missing else result("text_updated", True)
