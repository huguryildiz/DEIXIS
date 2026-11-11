"""What the conditional reviewer rule would do to a library of stored answers, counted without a model call.

    uv run python scripts/benchmark/review_pilot.py ~/Library/Application\\ Support/DEIXIS/library.sqlite

Every structurally valid answer in the library is read back and the rule is replayed over its stored draft and the
reading depth of the passages it cites. Nothing is written and nothing is sent: the script only counts.

Two arms are paired on the same answers, so the comparison is not between two sets of questions:

- **all**, what the product did before the rule: every valid answer is read a second time.
- **conditional**, what the rule does: only an answer that meets one of the conditions is.

An answer whose stored review marked a claim anything but `supported` is called a catch: that reading found
something. Catches can only be counted where a reading finished, so the catch numbers are reported over the answers
with a completed review and nothing else. An answer never read, or whose reading failed, is counted apart: what that
reading would have found is not known, and the script does not guess it. The saving is reported over every answer,
because a reading the rule does not open is saved whether or not a comparable one ever ran.

The count per condition is printed too, because a condition that fires on everything buys nothing. The review
verdicts are one model's reading, not verification, so a catch is a signal to look, never a judgement that the claim
is wrong.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

from deixis.workflow.answer import review_trigger

# A claim the stored review did not call supported: that reading had something to say about it.
UNSUPPORTED = ("partially_supported", "not_supported", "cannot_assess")


def passage_kinds(conn, draft):
    """The stored reading depth of every passage this draft cites, by passage id."""
    ids = tuple({pid for claim in draft.get("claims") or [] for pid in claim.get("passage_ids") or []})
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    return {row[0]: row[1] for row in conn.execute(f"SELECT id, kind FROM passages WHERE id IN ({marks})", ids)}


def answers(conn):
    """Every structurally valid answer with its draft, and the verdicts of the completed review it got, if any.

    `completed` is False for an answer never read and for one whose reading failed: neither says what a reading
    would have found, so both are kept out of the catch counts.
    """
    for row in conn.execute("SELECT id, research_id, draft_json FROM answers WHERE status = 'structurally_valid'"):
        review = conn.execute("SELECT status, review_json FROM answer_reviews WHERE answer_id = ?", (row[0],)).fetchone()
        completed = bool(review) and review[0] == "completed" and bool(review[1])
        verdicts = [r.get("verdict") for r in (json.loads(review[1]).get("reviews") or [])] if completed else []
        yield row[0], row[1], json.loads(row[2]), verdicts, completed


def count(path):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        per_condition, totals = Counter(), Counter()
        # The person's own request is not computed from a draft, so it is read from the rows where it was recorded.
        per_condition[review_trigger.PERSON_ASKED] = conn.execute(
            "SELECT COUNT(*) FROM answer_review_decisions WHERE occasion = 'person'").fetchone()[0]
        for _answer_id, _research_id, draft, verdicts, completed in answers(conn):
            fired = review_trigger.fired(draft, passage_kinds(conn, draft))
            caught = completed and any(v in UNSUPPORTED for v in verdicts)
            totals["answers"] += 1
            totals["completed"] += completed
            totals["catches"] += caught
            for condition in fired:
                per_condition[condition] += 1
            if fired:
                totals["conditional_reviews"] += 1
                totals["conditional_completed"] += completed
                totals["conditional_catches"] += caught
                # A reading the rule keeps whose finished review found nothing: the cost of firing wide.
                totals["conditional_quiet"] += completed and not caught
            else:
                totals["skipped"] += 1
                totals["skipped_completed"] += completed
                # A catch the rule would have skipped: the cost of the conditions being too narrow.
                totals["missed_catches"] += caught
                # An answer the rule skips whose outcome nobody knows: it is neither a catch nor a saving proved safe.
                totals["skipped_unknown"] += not completed
        return per_condition, totals
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library", type=Path, help="a DEIXIS library.sqlite, opened read only")
    args = parser.parse_args()
    per_condition, totals = count(args.library)
    print(f"answers (structurally valid): {totals['answers']}")
    print(f"  with a completed second reading (the only ones a catch can be counted on): {totals['completed']}")
    print(f"  of those, readings that marked a claim unsupported: {totals['catches']}")
    print()
    print("conditions met (an answer can meet several; person_asked is counted from the recorded requests):")
    for condition in review_trigger.TRIGGERS:
        print(f"  {condition}: {per_condition[condition]}")
    print()
    print(f"arm 'all'        : {totals['answers']} readings")
    print(f"arm 'conditional': {totals['conditional_reviews']} readings")
    print(f"  readings saved: {totals['skipped']}")
    print()
    print(f"over the {totals['completed']} answers with a completed reading:")
    print(f"  catches the rule keeps: {totals['conditional_catches']} of {totals['catches']}")
    print(f"  catches the rule loses: {totals['missed_catches']}")
    print(f"  kept readings that found nothing: {totals['conditional_quiet']} of {totals['conditional_completed']}")
    print(f"  skipped answers whose reading finished: {totals['skipped_completed']}")
    print()
    print(f"outcome not known for {totals['skipped_unknown']} of the {totals['skipped']} answers the rule skips:"
          " they were never read, or their reading failed")


if __name__ == "__main__":
    main()
