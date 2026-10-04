"""Model-free P9 preparation; each online command sends at most one request.

Run with .venv/bin/python scripts/p9_owed/prep_lookup.py --help. Online
commands require --item and --cap (the cumulative item allowance); --global-cap
defaults to 60 across both items. Use the SAME ledger for all preparation.
Offline helpers accept a single record, a list, or the lookup output envelope.
No server, credentials, model, application library, or dotenv is initialized.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextlib import contextmanager
import fcntl
from functools import partial
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
from types import FunctionType
from datetime import datetime, timezone
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from deixis.providers import crossref, lookup, openalex  # noqa: E402
from deixis.providers.common import ProviderRecord, normalize_doi  # noqa: E402
from deixis.workflow.candidates.run import ABSTRACT_CHARS, shown_passages  # noqa: E402

USER_AGENT = "DEIXIS/0.1 (local research workspace)"
DEFAULT_LEDGER = Path(".local/p9-owed/prep/ledger.jsonl")
ITEMS = ("k6", "l9")

# lookup.py:152-183 has no retry parameter. Reuse its exact function body with
# a private globals mapping, binding only send to the zero-retry policy. Never
# patch the shared module: another caller must retain its own retry policy.
_crossref_once = FunctionType(
    lookup.crossref_work.__code__,
    dict(lookup.crossref_work.__globals__, send=partial(
        lookup.send, max_rate_limit_retries=0, retry_rate_limit=False)),
    lookup.crossref_work.__name__, lookup.crossref_work.__defaults__,
    lookup.crossref_work.__closure__,
)


class PrepError(Exception):
    pass


def text_hash(text: str | None) -> str | None:
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text is not None else None


def record_view(record: ProviderRecord, provider: str) -> dict:
    first = record.authors[0] if record.authors else None
    family = ((record.raw.get("author") or [{}])[0].get("family")
              if provider == "crossref" else None)
    # OpenAlex supplies display names, not structured surnames. Preserve the
    # full name and label this approximation; compound surnames need inspection.
    surname = family or (first.split()[-1] if first and first.split() else None)
    return {
        "provider": provider,
        "openalex_id": record.provider_record_id if provider == "openalex" else None,
        "doi": record.doi, "title": record.title, "authors": record.authors,
        "first_author": first, "first_author_surname": surname,
        "surname_basis": "provider_family" if family else "display_name_last_token" if surname else None,
        "year": record.year, "abstract": record.abstract,
        "abstract_sha256": text_hash(record.abstract), "abstract_origin": record.abstract_origin,
        "identifiers": record.identifiers,
        "version_label": record.version_label,
    }


def read_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    admissions = {}
    outcomes = set()
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                row = json.loads(line)
                if (not isinstance(row, dict) or row["item"] not in ITEMS
                        or row.get("event") not in {None, "admitted", "outcome"}
                        or row["counted_attempts"] != (0 if row.get("event") == "outcome" else 1)):
                    raise ValueError
                if row.get("event") is not None:
                    request_id = row["request_id"]
                    if not isinstance(request_id, str) or not request_id:
                        raise ValueError
                    if row["event"] == "admitted":
                        if request_id in admissions or row["outcome"] != "admitted":
                            raise ValueError
                        admissions[request_id] = row["item"]
                    else:
                        if admissions.get(request_id) != row["item"] or request_id in outcomes:
                            raise ValueError
                        outcomes.add(request_id)
            except (ValueError, KeyError, TypeError):
                raise PrepError("ledger_unreadable: refusing to send") from None
            rows.append(row)
    return rows


@contextmanager
def ledger_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Serialize count/send/append across cooperating CLI processes. A separate
    # lock leaves the append-only ledger byte-identical when admission fails.
    with path.with_name(path.name + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def admit(rows: list[dict], item: str, cap: int, global_cap: int, planned: int = 1):
    # Historical single-line outcomes also consume one slot. New outcome lines
    # settle an admission and never consume a second slot.
    used = [row for row in rows if row.get("event") != "outcome"]
    if len(used) + planned > global_cap:
        raise PrepError("global_cap_exceeded: nothing sent")
    if sum(row["item"] == item for row in used) + planned > cap:
        raise PrepError("item_cap_exceeded: nothing sent")


def append_ledger(path: Path, entry: dict):
    try:
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        raise PrepError("ledger_append_failed: refusing further sends") from None


class OneRequestTransport(httpx.AsyncBaseTransport):
    """Defense against adapter retries, redirects and accidental second sends."""

    def __init__(self, transport: httpx.AsyncBaseTransport):
        self.transport = transport
        self.attempts = 0
        self.url = None
        self.http_status = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.attempts:
            raise PrepError("second_send_refused")
        if (request.url.host not in {"api.openalex.org", "api.crossref.org"}
                or request.url.scheme != "https"
                or "authorization" in request.headers
                or "mailto" in request.url.params or "api_key" in request.url.params):
            raise PrepError("request_policy_refused")
        self.attempts = 1
        # Query parameters are omitted, as in common.collect_transport().
        self.url = str(request.url.copy_with(query=None, fragment=None))
        response = await self.transport.handle_async_request(request)
        self.http_status = response.status_code
        return response

    async def aclose(self):
        await self.transport.aclose()


async def perform_lookup(args, *, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """Transport injection is for offline tests; caller owns this HTTP client."""
    with ledger_lock(args.ledger):
        admit(read_ledger(args.ledger), args.item, args.cap, args.global_cap)
        admission = {"utc_time": datetime.now(timezone.utc).isoformat(), "item": args.item,
                     "command": args.command, "request_id": uuid4().hex,
                     "event": "admitted", "outcome": "admitted", "counted_attempts": 1}
        append_ledger(args.ledger, admission)
        guard = OneRequestTransport(transport if transport is not None else httpx.AsyncHTTPTransport(retries=0))
        status = "interrupted"
        error = None
        try:
            async with httpx.AsyncClient(
                transport=guard, headers={"User-Agent": USER_AGENT},
                follow_redirects=False, trust_env=False,
            ) as client:
                if args.command == "search":
                    outcome = await openalex.search_works(
                        client, args.query, args.per_page, api_key=None,
                        contact_email=None, max_rate_limit_retries=0)
                    records = outcome.records
                    provider = "openalex"
                elif args.command == "ids":
                    outcome = await openalex.works_by_ids(
                        client, args.ids, api_key=None, contact_email=None, max_rate_limit_retries=0)
                    records = outcome.records
                    provider = "openalex"
                else:
                    _, outcome = await _crossref_once(client, args.doi, contact_email=None)
                    provider = "crossref"
                    records = ([crossref.record_from_item(outcome.raw_payload)]
                               if outcome.status == "completed" and outcome.raw_payload is not None else [])
                status = outcome.status
                result = {"item": args.item, "command": args.command, "provider": provider,
                        "outcome": status, "http_status": guard.http_status,
                        "records": [record_view(r, provider) for r in records]}
        except Exception as exc:
            # Do not print provider response bodies, credentials or exception text.
            status = "error_" + type(exc).__name__
            error = PrepError(status)
        # Process termination/cancellation can leave only the durable admission;
        # it still consumes the allowance, even when no outcome was recorded.
        entry = dict(admission, utc_time=datetime.now(timezone.utc).isoformat(),
                     event="outcome", url=guard.url, http_status=guard.http_status,
                     outcome=status, counted_attempts=0, sent_attempts=guard.attempts)
        append_ledger(args.ledger, entry)
        if error is not None:
            raise error from None
        return result


def supplied_text(record: dict) -> dict:
    abstract = record.get("abstract")
    if abstract is not None and not isinstance(abstract, str):
        raise PrepError("abstract_must_be_text_or_null")
    provider_hash = text_hash(abstract)
    if "abstract_sha256" in record and record["abstract_sha256"] != provider_hash:
        raise PrepError("provider_abstract_hash_mismatch")
    # store.py:1267,1413,1546-1563 stores record.abstract unchanged. run.py:133-146
    # selects and caps it. flow.py:5290-5294 passes text unchanged, with title in
    # a separate source field (5285-5287); there is no title prefix in the passage.
    rows = [{"kind": "abstract", "text": abstract}] if abstract is not None else []
    shown = shown_passages(rows)
    text = shown["passages"][0]["text"] if shown["passages"] else None
    return dict(record, provider_abstract_sha256=provider_hash,
                supplied_text=text, supplied_text_sha256=text_hash(text),
                supplied_text_chars=len(text) if text is not None else 0,
                abstract_cap_chars=ABSTRACT_CHARS, reading_depth=shown["reading_depth"],
                supplied_text_scope="kill_search_abstract_passage_only")


def lineage_module():
    path = ROOT / "scripts/p6_eval/measure_lineage.py"
    spec = importlib.util.spec_from_file_location("p9_prep_lineage", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def match_identity(record: dict, match: str, first_author: str, years: list[int]) -> dict:
    lineage = lineage_module()
    tokens = lineage.title_tokens(match)
    if not tokens or not first_author.strip() or not years:
        raise PrepError("identity_rule_must_not_be_empty")
    authors = record.get("authors")
    if authors is None:
        first = record.get("first_author") or record.get("first_author_surname")
        authors = [first] if first else []
    view = {"nodes": {"record": {"live": True, "title": record.get("title"), "year": record.get("year")}}}
    g = {"works": [{"key": "work", "match": match, "first_author": first_author, "years": years}]}
    found, rejected = lineage.g_nodes(g, view, {"record": authors})
    return {"status": "matched" if found["work"] else "identity_unverified",
            "title_tokens": list(lineage.title_tokens(record.get("title"))),
            "match_tokens": list(tokens), "title_head_matches": bool(found["work"] or rejected["work"]),
            "year_matches": record.get("year") in years,
            "first_author_matches": first_author.casefold() in lineage.title_tokens(" ".join(authors[:1])),
            "rule_source": "scripts/p6_eval/measure_lineage.py:title_tokens,g_nodes"}


def map_records(value, function):
    if isinstance(value, list):
        return [function(r) for r in value]
    if isinstance(value, dict) and "records" in value:
        return dict(value, records=[function(r) for r in value["records"]])
    if isinstance(value, dict):
        return function(value)
    raise PrepError("record_must_be_object_or_list")


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def nonnegative(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return number


def work_ids(value):
    ids = value.split(",")
    if not 1 <= len(ids) <= 100 or any(not re.fullmatch(r"W[0-9]+", w) for w in ids):
        raise argparse.ArgumentTypeError("supply 1-100 comma-separated short OpenAlex IDs (W1,W2)")
    return ids


def allowed_years(value):
    try:
        years = [int(y) for y in value.split(",")]
        if any(not 1 <= year <= 9999 for year in years):
            raise ValueError
        return years
    except ValueError:
        raise argparse.ArgumentTypeError("supply comma-separated years") from None


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="command", required=True)
    for name in ("search", "ids", "crossref", "supplied-text", "match-identity", "ledger-summary"):
        command = commands.add_parser(name)
        online = name in {"search", "ids", "crossref"}
        command.add_argument("--item", choices=ITEMS, required=online)
        command.add_argument("--cap", type=nonnegative, required=online,
                             help="cumulative item request allowance; offline commands send zero")
        command.add_argument("--global-cap", type=nonnegative, default=60)
        command.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
        if name not in {"ledger-summary", "match-identity"}:
            command.add_argument("--out", type=Path, required=True)
        if name == "search":
            command.add_argument("--query", required=True)
            command.add_argument("--per-page", type=int, required=True)
        elif name == "ids":
            command.add_argument("--ids", type=work_ids, required=True)
        elif name == "crossref":
            command.add_argument("--doi", required=True)
        elif name in {"supplied-text", "match-identity"}:
            command.add_argument("--record", type=Path, required=True)
            if name == "match-identity":
                command.add_argument("--match", required=True)
                command.add_argument("--first-author", required=True)
                command.add_argument("--years", type=allowed_years, required=True)
    return cli


def main(argv=None, *, transport=None) -> int:
    cli = parser()
    args = cli.parse_args(argv)
    try:
        if args.command in {"search", "ids", "crossref"}:
            if args.command == "search" and (not args.query.strip() or not 1 <= args.per_page <= 200):
                raise PrepError("search_requires_query_and_per_page_1_to_200")
            if args.command == "crossref":
                args.doi = normalize_doi(args.doi)
                if not args.doi or not re.fullmatch(r"10\.[0-9]{4,9}/[^\s?#]+", args.doi):
                    raise PrepError("invalid_doi")
            # Output must never overwrite request evidence.
            if args.out.resolve() in {args.ledger.resolve(), args.ledger.with_name(args.ledger.name + ".lock").resolve()}:
                raise PrepError("output_must_not_overwrite_ledger")
            result = asyncio.run(perform_lookup(args, transport=transport))
            write_json(args.out, result)
            if result["outcome"] not in {"completed", "zero_results"}:
                print("lookup_" + result["outcome"] + ": recorded; operator decides next attempt", file=sys.stderr)
                return 1
        elif args.command == "ledger-summary":
            with ledger_lock(args.ledger):
                rows = read_ledger(args.ledger)
            admitted = [row for row in rows if row.get("event") != "outcome"]
            # Completed means an outcome was durably recorded, including errors;
            # it does not imply provider success or that a request was sent.
            completed = [row for row in rows if row.get("event") != "admitted"]
            counts = Counter(row["item"] for row in admitted)
            print(json.dumps({"total_requests": len(admitted), "admitted_requests": len(admitted),
                              "completed_requests": len(completed),
                              "by_item": {item: counts[item] for item in ITEMS}}))
        else:
            value = json.loads(args.record.read_text(encoding="utf-8"))
            if args.command == "supplied-text":
                write_json(args.out, map_records(value, supplied_text))
            else:
                print(json.dumps(map_records(value, lambda r: match_identity(
                    r, args.match, args.first_author, args.years)), ensure_ascii=False, indent=2))
        return 0
    except (PrepError, OSError, ValueError, TypeError, KeyError) as exc:
        print(str(exc) if isinstance(exc, PrepError) else "local_error_" + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
