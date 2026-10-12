"""The contract of a search plan a person saves (UI parity S23a, F18). It is not a model output: no StepInput, no
envelope, no repair. The terms are held to the SearchQuery term rules (D92). SYNTHETIC values."""

import copy

import pytest

from deixis.domain import contracts

PLAN = {"schema_version": "deixis.user_search_plan.v1",
        "setting": [{"term": "rail freight"}], "task": [{"term": "timetable scheduling"}],
        "setting_backup": [], "task_backup": [{"term": "crew rostering"}],
        "criterion": {"text": "SYNTHETIC: a method that schedules rail freight timetables.",
                      "parts": [{"name": "scheduling method", "definition": "Builds a timetable.", "role": "core",
                                 "phrases": ["timetable"]}],
                      "exclusion_title_words": []},
        "providers": ["openalex", "crossref"]}


def codes(plan):
    return {issue.code for issue in contracts.check_user_search_plan(plan).issues}


def changed(path, value):
    plan = copy.deepcopy(PLAN)
    *parents, last = path
    node = plan
    for key in parents:
        node = node[key]
    node[last] = value
    return plan


def test_the_contract_is_registered_and_a_valid_plan_passes():
    assert contracts.SCHEMA_FILES["UserSearchPlan"] == "user-search-plan.schema.json"
    assert contracts.SCHEMA_VERSIONS["UserSearchPlan"] == "deixis.user_search_plan.v1"
    assert "UserSearchPlan" not in {name for outputs in contracts.TASK_OUTPUTS.values() for name in outputs}
    report = contracts.check_user_search_plan(PLAN)
    assert report.ok and report.result == PLAN
    assert contracts.check_user_search_plan(changed(["criterion"], None)).ok  # the person may set no criterion


@pytest.mark.parametrize(("path", "value", "code"), [
    (["task"], [{"term": "timetable OR rostering"}], "query_syntax_in_term"),
    (["task"], [{"term": "timetable (rail)"}], "query_syntax_in_term"),
    (["task"], [{"term": "freight:timetable"}], "query_syntax_in_term"),
    (["task"], [{"term": "one two three four five"}], "query_term_too_long"),
    (["task"], [{"term": "   "}], "query_term_empty"),
    (["setting"], [{"term": "nul\x00here"}], "blank_text"),
    (["task_backup"], [{"term": "Rail Freight"}], "duplicate_query_term"),
    (["task"], [], "user_plan_schema_invalid"),
    (["providers"], ["crossref"], "openalex_required"),
    (["providers"], ["openalex", "ieee_xplore"], "user_plan_schema_invalid"),
    (["providers"], ["openalex", "openalex"], "user_plan_schema_invalid"),
    (["criterion", "parts", 0, "role"], "aspect", "criterion_core_missing"),
    (["criterion", "parts", 0, "phrases"], ["a b c d e"], "criterion_phrase_too_long"),
    (["criterion", "parts", 0, "phrases"], ["timetable", "Timetable"], "duplicate_criterion_phrase"),
    (["criterion", "text"], " ", "blank_text"),
])
def test_a_plan_that_breaks_a_rule_is_refused_with_that_rule(path, value, code):
    assert code in codes(changed(path, value))


def test_two_parts_with_one_name_are_refused():
    part = PLAN["criterion"]["parts"][0]
    assert "duplicate_criterion_part" in codes(changed(["criterion", "parts"], [part, part | {"role": "aspect"}]))


def test_six_chosen_terms_pass_and_seven_are_refused():
    six = changed(["task"], [{"term": f"t{i}"} for i in range(5)])
    assert contracts.check_user_search_plan(six).ok
    seven = six | {"setting": [{"term": "s0"}, {"term": "s1"}]}
    assert "too_many_query_terms" in codes(seven)
