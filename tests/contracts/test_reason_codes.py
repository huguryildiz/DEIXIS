"""The reason code table a stage decision is written with (SW9, SW11)."""

import pytest

from deixis.domain.reason_codes import DECIDERS, NEXT_STEPS, OUTCOMES, REASON_CODES, STAGES, reason


def test_every_code_names_a_stage_an_outcome_of_that_stage_a_decider_and_a_next_step():
    for code, entry in REASON_CODES.items():
        assert entry.code == code
        assert entry.stage in STAGES
        assert entry.outcome in OUTCOMES[entry.stage]
        assert entry.decided_by in DECIDERS
        assert entry.next_step in NEXT_STEPS


def test_only_the_human_codes_are_decided_by_the_user():
    human = {code for code, entry in REASON_CODES.items() if entry.decided_by == "human"}
    assert human == {code for code in REASON_CODES if code.startswith("human_")}
    assert human  # the table is not empty, so the check above means something


def test_an_unknown_code_is_a_key_error_naming_the_code():
    with pytest.raises(KeyError, match="no_such_code"):
        reason("no_such_code")


def test_a_known_code_comes_back_with_its_fields():
    assert reason("all_parts_verified") == REASON_CODES["all_parts_verified"]
    assert (reason("all_parts_verified").stage, reason("all_parts_verified").outcome) == ("fulltext", "include")
