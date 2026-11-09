"""One open-web search for the full text of a work the DOI routes could not reach.

The last automatic route, and the narrowest. It runs only for a work the report's own plan leaves a sub-question
open on, only after that work's DOI routes have answered without a file, and only while the depth's allowance lasts
(`fast_path.MODES`: none in Quick, three in Standard, five in Deep). The search is metered, so its row is written
**before** the request goes out: the allowance is reserved by the asking, and a crash can lose the answer but never
spend the allowance twice. A work the allowance, the key or the depth rules out gets a row of its own saying which,
so the file-request list can tell a work that was searched for from one that never was.

What it finds is judged by the file, not by the result page. A PDF is attached only when one of its own first
pages bears this record's title at the start of a line **and** carries this record's DOI: that page is its title
page. The DOI by itself proves nothing here, because a paper that cites this work prints this work's DOI, and often
its whole title, in its own reference list. A file that matches on title, author and venue names the **work** and
says nothing about which version it is, so it is left as a candidate with its verdict for the person to confirm —
the same rule the OpenAlex content route follows, and the reason this route never guesses a version.

It is its own queue (`fulltext_searches`), not a row in the DOI routes' lane: that lane takes one row per run and
work with its own two origins, and a metered search of another kind does not belong in it. It opens no run of its
own either; the work is recorded as a step of the run whose depth paid for it.
"""

from __future__ import annotations

import logging
from typing import Any

from deixis.documents import acquisition, fetch
from deixis.storage.db import dumps, new_id, now, transaction
from deixis.workflow.features.report import report_gap_works as gap
from deixis.workflow.run import fast_path

log = logging.getLogger("deixis.fulltext_search")

RULE = "fulltext_search_v1"
STEP_KEY = "recovery:"  # the step one search is recorded under, keyed by the record it searched for
STEP_KIND = "code:fulltext_search"
# A row that will never run again: the file-request list reads these as "this work's search has had its turn". A
# cancelled row is not among them, because a cancelled search was never sent: the run stopped, the question changed
# or the record left the research, and the work is reserved again when its question comes back.
SETTLED = ("skipped", "succeeded", "failed")
# Why no search was sent. Kept apart from "searched and found nothing", which is `no_result`.
NOT_SENT = {"no_allowance": "the depth sends none", "allowance_spent": "the depth's allowance is spent",
            "no_key": "no search key is connected"}


def allowance(store: Any, run_id: str) -> int | None:
    """How many searches the depth that paid for this run allows; None when its policy predates the rule."""
    return gap.frozen_number(store, run_id, "fulltext_search_rule", fast_path.FULLTEXT_SEARCH_RULE,
                             "fulltext_searches")


def searches(store: Any, research_id: str) -> list[dict[str, Any]]:
    """Every open-web search this research has reserved, in the order it reserved them."""
    return [dict(row) for row in store.conn.execute(
        "SELECT * FROM fulltext_searches WHERE research_id = ? ORDER BY position, rowid", (research_id,),
    )]


def settled(store: Any, research_id: str, work_id: str, scope_revision: int) -> bool:
    """Whether this work's open-web search has had its turn under this question: it ran, or none could be sent.

    The question's own revision is part of it. A search cancelled when the person changed the question answers
    nothing about the new one, and a row of the older question is not an answer for this one either.
    """
    return bool(store.conn.execute(
        f"SELECT 1 FROM fulltext_searches WHERE research_id = ? AND work_id = ? AND scope_revision = ?"
        f" AND status IN ({', '.join('?' * len(SETTLED))}) LIMIT 1",
        (research_id, work_id, scope_revision, *SETTLED),
    ).fetchone())


def recover(store: Any) -> None:
    """After a restart, a search that was in flight is written down as failed, never queued again.

    Its request may already have gone out, and the request is what is metered: sending a second one for the same
    work would spend the allowance twice for one work. So the answer is lost, the work is not searched again, and
    the search has had its turn — which is what lets the person be asked for the file instead.
    """
    with transaction(store.conn):
        store.conn.execute(
            "UPDATE fulltext_searches SET status = 'failed', outcome = 'failed', reason = 'search_interrupted',"
            " finished_at = ? WHERE status = 'running'", (now(),))


def advance(store: Any, research_id: str, api_key: str | None = None) -> list[dict[str, Any]]:
    """Reserve one row per work the report's gap points at; the rows it wrote.

    Queued when a search may be sent for that work, `skipped` with its reason when the depth sends none, the
    allowance is spent or no key is connected. Running it again writes nothing: a work is reserved once under one
    question, and a depth that froze no allowance for the rule reserves nothing at all.
    """
    try:
        return _advance(store, research_id, api_key)
    except Exception:  # noqa: BLE001 - the queue never fails the run or the upload that asked for it
        log.exception("full-text search queue failed: %s", research_id)
        return []


def _advance(store: Any, research_id: str, api_key: str | None) -> list[dict[str, Any]]:
    found = gap.gap_works(store, research_id)
    if found is None or not found["works"]:
        return []
    report, depth = found["report"], found["depth"]
    limit = allowance(store, depth) if depth else None
    # A depth that froze no allowance for this rule is not a depth of zero: nothing was decided, so nothing is
    # reserved and nothing is written down. The work keeps waiting for a run under a policy that names the rule,
    # which is also why the file-request list does not read it as a search that had its turn.
    if limit is None:
        return []
    with transaction(store.conn):
        # A search still queued for a question the person has moved past is cancelled here, where the new question
        # is being read, and not left for the queue to notice. Cancelled now, it holds no place in the allowance
        # the new question is about to spend; left queued, it would hold one and then be cancelled anyway, and the
        # work would be written down as past an allowance nothing ever used.
        store.conn.execute(
            "UPDATE fulltext_searches SET status = 'cancelled', reason = 'scope_revised', finished_at = ?"
            " WHERE research_id = ? AND scope_revision != ? AND status = 'queued'",
            (now(), research_id, report["scope_revision"]))
        held = {row["work_id"] for row in store.conn.execute(
            "SELECT work_id FROM fulltext_searches WHERE research_id = ? AND scope_revision = ?"
            " AND status != 'cancelled'", (research_id, report["scope_revision"]))}
        # What the allowance has already paid for, over the research's whole life: every row whose request went
        # out, and every row still to send. A row the depth or the key stopped before the request spent nothing,
        # and neither did one cancelled while it was still queued — but a row cancelled after its request was sent
        # (`attempts`) did, so a changed question cannot hand the allowance back.
        spent = store.conn.execute(
            "SELECT COUNT(*) FROM fulltext_searches WHERE research_id = ?"
            " AND (attempts > 0 OR status NOT IN ('skipped', 'cancelled'))", (research_id,)).fetchone()[0]
        written = []
        for work in found["works"]:
            if work["work_id"] in held:
                continue
            # The row is written before anything is sent, so the allowance is spent by the reservation. A work no
            # search can be sent for is written down too, with the reason, and never searched for later — and a row
            # like that spends nothing, so it never pushes the next work past the limit.
            queued = sum(1 for held_row in written if held_row["status"] == "queued")
            not_sent = ("no_allowance" if limit == 0 else
                        "allowance_spent" if spent + queued >= limit else
                        "no_key" if not api_key else None)
            row = {"id": new_id("fts"), "research_id": research_id, "run_id": depth, "report_id": report["id"],
                   "scope_revision": report["scope_revision"], "work_id": work["work_id"],
                   "source_version_id": work["source_version_id"], "rule": RULE,
                   "axes_json": dumps([{key: axis[key] for key in ("axis_id", "label", "column_id", "cell_id",
                                                                   "state")} for axis in work["axes"]]),
                   "query_text": None, "position": len(held) + len(written),
                   "status": "skipped" if not_sent else "queued", "outcome": not_sent,
                   "reason": NOT_SENT.get(not_sent or ""), "queued_at": now(),
                   "finished_at": now() if not_sent else None}
            store.conn.execute(
                f"INSERT INTO fulltext_searches ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                tuple(row.values()))
            store._event(research_id, "fulltext_search_reserved",
                         {"work_id": row["work_id"], "source_version_id": row["source_version_id"], "rule": RULE,
                          "status": row["status"], "outcome": row["outcome"]}, report["run_id"])
            written.append(row)
        return written


def query_for(source: dict[str, Any]) -> str | None:
    """What to search for: the record's own title with its first author's family name, else its DOI.

    The title is what a result page is matched on, and the author narrows a title other papers share. A record whose
    title carries too little to search on falls back to its DOI, and one with neither is not searched at all.
    """
    title = (source.get("title") or "").strip()
    family = ""
    authors = source.get("authors") or []
    if authors:
        first = authors[0]
        name = first.get("family") or first.get("name") or "" if isinstance(first, dict) else str(first)
        family = (name.split(",")[0] if "," in name else name.split()[-1] if name.split() else "").strip()
    if len(title.split()) >= 3:
        return f'"{title}" {family}'.strip()
    return source.get("doi") or (f'"{title}"' if title else None)


async def run_one(flow: Any, row: dict[str, Any], api_key: str | None) -> None:
    """Send the one search this row reserved, read what it finds, and keep only a file that names this record.

    The step is the run's whose depth paid for the search, so its provider requests are counted there. A file is
    attached only when one of its first pages bears this record's title at the start of a line and carries this
    record's DOI; one that matches by title, author and venue stays a candidate with its verdict, because nothing
    about it says which version it is.
    """
    store, settings = flow.store, flow.deps.settings
    svid, research_id = row["source_version_id"], row["research_id"]
    step = store.step(row["run_id"], f"{STEP_KEY}{svid}", STEP_KIND)
    if step["status"] == "succeeded":  # a step that succeeded never runs again
        held = step.get("output") or {}
        _finish(store, row, "succeeded", held.get("outcome") or "no_result", held.get("reason"))
        return
    if not _mark_running(store, row):
        return  # the row is no longer the one queued here: another turn has it, or a restart settled it
    store.start_step(step["id"])
    source = store.source(svid)
    doi = source.get("doi")
    query = query_for(source)
    if not query:
        store.finish_step(step["id"], "succeeded", output={"outcome": "no_result", "reason": "nothing_to_search_on"})
        _finish(store, row, "succeeded", "no_result", "nothing_to_search_on")
        return
    store.conn.execute("UPDATE fulltext_searches SET query_text = ? WHERE id = ?", (query, row["id"]))
    answer = acquisition.attempted(
        await acquisition.web_lookup(flow.deps.http, doi or "", source["title"], api_key, query=query))
    run_id = store.record_pdf_discovery(research_id, svid, "web_search", query, answer, row["run_id"])
    store.record_pdf_candidates(svid, run_id, answer.candidates, doi)
    if answer.status != "completed" or not answer.candidates:
        outcome = "no_result" if answer.status in ("completed", "zero_results") else "failed"
        store.finish_step(step["id"], "succeeded", output={"outcome": outcome, "reason": answer.error_code})
        _finish(store, row, "succeeded", outcome, answer.error_code)
        return
    outcome, reason = "no_match", None
    published = store.provider_record_id(svid, "published_doi")
    for candidate in acquisition.candidate_order(store.pdf_candidates(svid)):
        if candidate["provider"] != "web_search":
            continue
        # A copy already read is not read again — unless its file came down and never became this record's full
        # text. That is the one case worth another turn: the attach was cut off, and skipping it would leave a
        # verified file nowhere while the search reported finding none.
        if candidate["access_status"] == "downloaded" and (candidate["error_code"] or store.has_asset(svid)):
            continue
        result = await fetch.fetch_pdf(candidate["candidate_url"], email=settings.contact_email)
        store.record_pdf_attempt(candidate["id"], result)
        if result.status != "ok":
            continue
        verdict = await acquisition.file_verdict(store, svid, candidate["candidate_url"], result.data,
                                                 settings.papers_dir, published)
        if verdict["verdict"] != "match":
            store.note_candidate_reason(candidate["id"], f"identity_{verdict['verdict']}")
            continue
        if doi and doi in (verdict.get("dois") or []) and "title_at_top" in (verdict.get("fields") or []):
            # The file's own title page carries this record's DOI **and** its title at the top of that page. The
            # DOI alone would not do it, and neither would the title anywhere on the page: a paper citing this work
            # prints this work's DOI and its whole title in its own reference list, which a cover page or a short
            # paper puts inside the title pages. A title borne at the top of the page that also carries the DOI is
            # this record's own title page, so the file is its full text and not a copy whose version nobody
            # settled. A verdict read back from the store predates this field and never attaches: the file is read
            # again or the person decides.
            if store.research(research_id)["current_scope_revision"] != row["scope_revision"] \
                    or not store.is_active_member(research_id, svid):
                # The question changed or the record left the research while the file was coming down. Nothing is
                # attached to a record this research no longer holds, and nothing is claimed for a question nobody
                # asked any more.
                store.finish_step(step["id"], "cancelled", output={"reason": "source_changed", "query": query})
                _finish(store, row, "cancelled", None, "source_changed")
                return
            try:
                await acquisition.attach_searched_file(store, svid, result.data, settings.papers_dir,
                                                       result.final_url or candidate["candidate_url"],
                                                       research_id=research_id, recovery_dir=settings.recovery_dir)
            except Exception:  # noqa: BLE001 - the file is named on the candidate, so another turn can try again
                log.exception("attaching a searched file failed: %s", svid)
                store.note_candidate_reason(candidate["id"], "attach_failed")
                outcome, reason = "failed", "attach_failed"
                break
            outcome, reason = "attached", "doi_on_title_page"
            break
        # A title, author and venue match names the work, never the version: the person decides. The search keeps
        # reading the rest of the results, because a later copy may carry the DOI on its own title page.
        store.note_candidate_reason(candidate["id"], "version_unsettled")
        outcome, reason = "candidate_listed", verdict["verdict"]
    store.finish_step(step["id"], "succeeded" if outcome != "failed" else "failed",
                      output={"outcome": outcome, "reason": reason, "query": query})
    _finish(store, row, "succeeded" if outcome != "failed" else "failed", outcome, reason)


def _mark_running(store: Any, row: dict[str, Any]) -> bool:
    """Take the row, and say whether this turn got it: only a queued row may be sent for."""
    with transaction(store.conn):
        return store.conn.execute(
            "UPDATE fulltext_searches SET status = 'running', attempts = attempts + 1, started_at = ?"
            " WHERE id = ? AND status = 'queued'", (now(), row["id"])).rowcount == 1


def _finish(store: Any, row: dict[str, Any], status: str, outcome: str | None, reason: str | None) -> None:
    with transaction(store.conn):
        store.conn.execute(
            "UPDATE fulltext_searches SET status = ?, outcome = ?, reason = ?, finished_at = ? WHERE id = ?",
            (status, outcome, reason, now(), row["id"]))
        store._event(row["research_id"], "fulltext_search_settled",
                     {"work_id": row["work_id"], "source_version_id": row["source_version_id"], "rule": RULE,
                      "outcome": outcome, "reason": reason}, row["run_id"])
