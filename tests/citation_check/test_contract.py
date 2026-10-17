"""Verify Citations V1 (D86): the code verdict over plain assessments. No model; every input is written here."""

import pytest

from deixis.domain.citation_check import (MAX_PARTS, RESULTS, STATUSES, PartAssessment as P, check_outcome,
                                          derive_result, valid_status_result, CouldNotCheck)


def reason(parts, covers=True):
    with pytest.raises(CouldNotCheck) as caught:
        derive_result(parts, covers)
    return caught.value.reason


def test_every_part_stated_with_a_located_quote_and_the_whole_sentence_is_found_whole():
    assert derive_result([P("stated", (True,)), P("stated", (False, True))], True) == "found_whole"


def test_every_part_not_stated_over_the_whole_sentence_is_not_found_in_given():
    assert derive_result([P("not_stated"), P("not_stated")], True) == "not_found_in_given"


@pytest.mark.parametrize("parts", [
    [P("stated", (True,)), P("not_stated")],
    [P("partly", (True,))],
    [P("stated", (True,)), P("partly", (True, False))],
])
def test_a_positive_part_beside_a_partly_or_missing_one_is_found_partial(parts):
    assert derive_result(parts, True) == "found_partial"


def test_a_positive_part_with_no_quote_is_never_turned_into_not_stated():
    assert reason([P("stated", ())]) == "positive_part_quote_count"
    assert reason([P("partly", ()), P("not_stated")]) == "positive_part_quote_count"
    assert check_outcome([P("stated", ())], True) == {"status": "could_not_check", "result": None,
                                                     "error": "positive_part_quote_count"}


def test_a_positive_part_whose_quotes_were_all_rejected_cannot_be_checked():
    assert reason([P("stated", (False, False, False))]) == "positive_part_without_located_quote"
    # One rejected positive part spoils the whole assessment, even beside a valid one.
    assert reason([P("stated", (True,)), P("partly", (False,))]) == "positive_part_without_located_quote"


def test_a_stated_part_and_an_omitted_part_never_give_found_whole():
    # The model listed only part A and said its parts do not cover the sentence (part B left out).
    assert reason([P("stated", (True,))], covers=False) == "sentence_not_covered"
    assert check_outcome([P("stated", (True,))], False)["result"] is None


@pytest.mark.parametrize("covers", [False, None, "true", 1])
def test_coverage_must_be_declared_true_for_any_result(covers):
    assert reason([P("not_stated")], covers) == "sentence_not_covered"
    assert reason([P("stated", (True,)), P("not_stated")], covers) == "sentence_not_covered"


def test_shape_limits_fail_closed():
    assert reason([]) == "no_parts"
    assert reason([P("not_stated")] * (MAX_PARTS + 1)) == "too_many_parts"
    assert reason([P("stated", (True,) * 4)]) == "positive_part_quote_count"
    assert reason([P("stated", (True,) * 3), P("stated", (True,) * 3), P("stated", (True,) * 3)]) == "too_many_quotes"
    assert reason([P("supported", (True,))]) == "unknown_assessment"
    assert reason([P("stated", ("yes",))]) == "unknown_assessment"
    assert reason([P("not_stated", (True,))]) == "quote_on_not_stated_part"
    assert reason(["stated"]) == "unknown_assessment"


def test_a_result_belongs_to_done_only():
    assert all(valid_status_result("done", r) for r in RESULTS)
    assert not valid_status_result("done", None)
    for status in STATUSES:
        if status != "done":
            assert valid_status_result(status, None) and not valid_status_result(status, "found_whole")
    assert not valid_status_result("checked", None)
