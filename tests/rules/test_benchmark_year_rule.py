"""The one year rule every benchmark arm is read under.

A comparison is only a comparison when both arms were given the same condition. One arm cuts at the provider,
with OpenAlex's own `to_publication_date`, which returns no work without a date; the other is cut here, after the
search. So a record with no year is outside the bound on both sides, and how many records each arm dropped, for
which reason, is reported beside its scores instead of being lost in the filter. These rules are code, not
measurement: a passing test says the arms are read alike, not that either arm is good.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2] / "scripts" / "benchmark"))
import bioasq  # noqa: E402


def test_a_record_at_the_question_s_own_year_is_inside_the_bound():
    assert bioasq.in_time({"year": 2014}, 2014) is True
    assert bioasq.in_time({"year": 2013}, 2014) is True


def test_a_record_published_after_the_question_is_outside_it():
    assert bioasq.in_time({"year": 2015}, 2014) is False


def test_a_record_with_no_year_is_outside_a_bound_on_both_sides_of_a_comparison():
    """The arm that cuts at the provider cannot return it, so the arm cut afterwards does not keep it either."""
    assert bioasq.in_time({"year": None}, 2014) is False
    assert bioasq.in_time({}, 2014) is False


def test_the_two_reasons_a_record_is_dropped_are_different_facts():
    """One is a place the search spent on a record published after the question; the other is a record whose year
    the provider never gave. A report that added them would say the search reached further back than it did."""
    records = [{"year": 2013}, {"year": 2016}, {"year": None}]
    kept = [r for r in records if bioasq.in_time(r, 2014)]
    after = [r for r in records if r.get("year") is not None and r["year"] > 2014]
    unknown = [r for r in records if r.get("year") is None]
    assert (len(kept), len(after), len(unknown)) == (1, 1, 1)
    assert len(kept) + len(after) + len(unknown) == len(records)


def test_every_scorer_reads_a_record_the_same_way():
    """Four readers judge a record's year: both BioASQ reports and the two LitSearch ones. A reader of its own
    would make one arm lenient, which is the inequality this package closed."""
    sources = [Path(__file__).resolve().parents[2] / "scripts" / "benchmark" / name
               for name in ("bioasq_run.py", "m1_score.py", "litsearch_run.py")]
    for path in sources:
        text = path.read_text()
        assert "r.get('year') is None or" not in text, f"{path.name} reads years with a rule of its own"
        assert "bioasq.in_time" in text
