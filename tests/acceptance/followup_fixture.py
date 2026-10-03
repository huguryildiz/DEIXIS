"""SYNTHETIC follow-up pages around the unchanged scripted discovery fixture.

Only requests carrying sort are watch reads. No real provider or model is used.
The separate wrapper avoids the shared fixture file owned by parallel batches.
"""

import argparse
import asyncio
from pathlib import Path

import httpx

from tests.acceptance import fixture_server
from deixis.api import app as api_app


def work(identifier, title, *, doi=None, date="2026-09-01"):
    return {"id": f"https://openalex.org/{identifier}", "doi": f"https://doi.org/{doi}" if doi else None,
            "display_name": title, "publication_year": int(date[:4]) if date else 2026,
            "publication_date": date, "type": "article", "ids": {},
            "authorships": [{"author": {"display_name": "SYNTHETIC Ada Smith"}}],
            "primary_location": {"landing_page_url": f"https://synthetic.invalid/{identifier}", "version": "publishedVersion"},
            "abstract_inverted_index": {"SYNTHETIC": [0], "bounded": [1], "followup": [2]}}


BASE_TITLE = "SYNTHETIC bounded followup scheduling with explicit publication dates"
BASE = [work("W980001", BASE_TITLE, doi="10.9999/synthetic.followup.base")]
NEW = [work("W980002", "SYNTHETIC dated followup published record", doi="10.9999/synthetic.followup.new", date="2026-10-03"),
       work("W980003", "SYNTHETIC native-only followup identity", date=None),
       work("W980004", "Correction: " + BASE_TITLE, doi="10.9999/synthetic.followup.notice", date="2026-10-03"),
       work("W980005", BASE_TITLE, doi="10.9999/synthetic.followup.version", date="2026-10-03")]


def wrapper(original, data_dir):
    async def openalex(request):
        if "sort" not in request.url.params:
            result = original(request)
            return await result if hasattr(result, "__await__") else result
        flag = data_dir / "followup-mode"
        mode = flag.read_text().strip() if flag.exists() else "base"
        if mode not in {"base", "new", "partial", "fail", "hold"}:
            raise ValueError("Unknown SYNTHETIC followup-mode")
        if mode == "fail":
            return httpx.Response(500, json={"error": "SYNTHETIC follow-up provider failure"})
        cursor = request.url.params.get("cursor", "*")
        if mode == "hold" and cursor == "*":
            (data_dir / "followup-held").write_text("SYNTHETIC request held\n")
            for _ in range(600):
                if (data_dir / "followup-release").exists():
                    break
                await asyncio.sleep(0.1)
            else:
                return httpx.Response(500, json={"error": "SYNTHETIC follow-up hold timed out"})
        next_cursor = None
        if mode in {"partial", "hold"}:
            # Future dates are deliberate synthetic values, not evidence of future publications.
            results = [work("W980010" if cursor == "*" else "W980011",
                            "SYNTHETIC future publication date for bounded coverage test",
                            doi="10.9999/synthetic.followup.future." + ("1" if cursor == "*" else "2"), date="2099-12-30")]
            next_cursor = "followup-page-2" if cursor == "*" else "followup-page-3"
        else:
            results = BASE + (NEW if mode == "new" else [])
            results = sorted(results, key=lambda record: record["publication_date"] or "", reverse=True)
        return httpx.Response(200, json={"meta": {"count": len(results), "next_cursor": next_cursor}, "results": results})
    return openalex


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--data-dir", type=Path, required=True)
    args, _ = parser.parse_known_args()
    # The current create route derives providers from connections, not its body; the composer has no
    # provider picker. Constrain that fixture-only connection seam, then use the real create/discovery routes.
    api_app.configured_providers = lambda: ["openalex"]
    fixture_server.openalex = wrapper(fixture_server.openalex, args.data_dir)
    fixture_server.main()


if __name__ == "__main__":
    main()
