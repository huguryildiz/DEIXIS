"""How long one page's `record_search` takes as the candidate pool grows (slice 04c, Task 5).

Paging turns one `record_search` per query into one per page, and every call runs `links.link_records` over all of the
research's candidates (slice 03), rebuilding the title trigrams each time. The transaction runs on the event-loop
thread, so while it runs the API waits too. This probe measures that cost at the pool size a read limit of 2,000
allows, in a temporary data directory, with no network and no model.

Records are the real first-round titles of the 2026-09-18 quantum round when that file is present (real title
neighbourhoods, which is what the trigram index costs money on); otherwise they are seeded SYNTHETIC titles. Which
one was used is written into the output. A number here measures this machine, not the product's recall.

    PYTHONPATH=backend:. uv run --no-sync python scripts/probes/time_link_records.py
"""

from __future__ import annotations

import argparse
import json
import platform
import random
import tempfile
import time
from pathlib import Path

from deixis.providers.common import ProviderRecord
from deixis.storage import db
from deixis.workflow import links, store as store_module
from deixis.workflow.store import Store

ROUND = Path(".local/quantum-rank-fusion-2026-09-18/round.json")
OUT = Path(".local/sw-paging-timing-2026-09-21/timing.json")
WORDS = ("release scheduling diffusion channel packet size energy budget molecular relay receiver decoding"
         " estimation throughput latency quantum repeater entanglement purification network routing").split()


def titles(count: int) -> tuple[list[str], str]:
    """Real first-round titles when they are on disk, otherwise seeded synthetic ones; says which."""
    if ROUND.exists():
        real = [d["title"] for d in json.loads(ROUND.read_text(encoding="utf-8"))["docs"] if d.get("title")]
        if len(real) >= count:
            return real[:count], f"real: {ROUND} first round"
        rng = random.Random(4)
        padding = [f"SYNTHETIC {' '.join(rng.sample(WORDS, 6))} {i}" for i in range(count - len(real))]
        return real + padding, f"real: {ROUND} first round ({len(real)}) + {len(padding)} SYNTHETIC"
    rng = random.Random(4)
    return [f"SYNTHETIC {' '.join(rng.sample(WORDS, 6))} {i}" for i in range(count)], "SYNTHETIC seeded titles"


def record(number: int, title: str) -> ProviderRecord:
    return ProviderRecord(
        provider_record_id=f"W{number}", title=title, authors=["Author, A."], year=2024, venue=None,
        publication_type="article", doi=f"10.1/probe.{number}", landing_url=None, oa_pdf_url=None,
        oa_pdf_version=None, version_label=None, abstract=None, abstract_origin=None, identifiers={}, raw={},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=int, default=1500)
    parser.add_argument("--page-size", type=int, default=200)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    names, origin = titles(args.candidates)
    linked: list[float] = []
    original = links.link_records

    def timed(*call_args, **call_kwargs):
        start = time.perf_counter()
        try:
            return original(*call_args, **call_kwargs)
        finally:
            linked.append(time.perf_counter() - start)

    store_module.links.link_records = timed
    with tempfile.TemporaryDirectory(prefix="deixis-timing-") as data_dir:
        conn = db.connect(Path(data_dir) / "library.sqlite")
        db.migrate(conn)
        store = Store(conn)
        rid = store.create_research("SYNTHETIC timing question?", "academic", "standard", ["openalex"], "fake",
                                    "fake-model", "en", search_workflow="sw")
        run = store.create_run(rid, "discovery", {"max_model_calls": 4, "max_provider_requests": 4,
                                                  "max_candidates": args.candidates, "max_answer_passages": 8}, None)
        pages = []
        for number, first in enumerate(range(0, args.candidates, args.page_size)):
            batch = [record(i, names[i]) for i in range(first, min(first + args.page_size, args.candidates))]
            key = "search:0" if number == 0 else f"search:0:page:{number}"
            step = store.step(run["id"], key, "provider_search:openalex")
            fields = dict(research_id=rid, run_id=run["id"], step_id=step["id"], scope_revision=1, provider="openalex",
                          query_text="probe", request_description="none: no request was sent", access_mode="keyless",
                          status="completed", delivery_class=None, result_count=len(batch), provider_total=args.candidates,
                          page_limit=args.page_size, error_json=None, raw_payload_path=None, page_number=number,
                          read_limit=args.candidates, read_total=first + len(batch), stop_reason=None, unread_count=None)
            linked.clear()
            start = time.perf_counter()
            store.record_search(fields, "openalex", batch, None, step["id"], "succeeded",
                                step_output={"status": "completed", "result_count": len(batch)}, first_rank=first)
            elapsed = time.perf_counter() - start
            pool = conn.execute("SELECT COUNT(*) FROM candidates WHERE research_id = ?", (rid,)).fetchone()[0]
            pages.append({"page": number, "records": len(batch), "candidates_after": pool,
                          "record_search_seconds": round(elapsed, 4),
                          "link_records_seconds": round(sum(linked), 4)})
        conn.close()

    result = {
        "measured_at": "2026-09-21", "machine": f"{platform.platform()} {platform.machine()} python {platform.python_version()}",
        "records": origin, "page_size": args.page_size, "candidates": args.candidates,
        "total_seconds": round(sum(p["record_search_seconds"] for p in pages), 4),
        "link_records_seconds": round(sum(p["link_records_seconds"] for p in pages), 4),
        "slowest_page_seconds": max(p["record_search_seconds"] for p in pages),
        "pages": pages,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "pages"}, indent=2))
    for page in pages:
        print(f"  page {page['page']:>2}  pool {page['candidates_after']:>5}  "
              f"record_search {page['record_search_seconds']:>7.3f}s  link_records {page['link_records_seconds']:>7.3f}s")


if __name__ == "__main__":
    main()
