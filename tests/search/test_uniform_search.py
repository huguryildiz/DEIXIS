"""New discovery search limits and the exact policy hashes kept by earlier runs."""

import pytest

from deixis.domain.rules import PROVIDER_WAIT, SW_READ_LIMIT, TEST_EFFORT_BUDGETS
from deixis.workflow.run import fast_path


OLD_HASHES = {
    "quick": "10af1819ef378802deceb0de13b44456189d07b42c975b3815b0fc87afa7a479",
    "standard": "818f2cfffc2d5056ade22f7a5fc9d25d738d2eceaf7b5d502ab684cfbadbe9f3",
    "detailed": "f63cb0c7d4f000d218fc93ba4d6366d40cb5e4498b4e192879f1c95728133a83",
}


@pytest.mark.parametrize("effort", OLD_HASHES)
def test_shared_search_is_frozen_but_reading_remains_depth_specific(effort):
    policy = fast_path.freeze_budget({}, effort, completion_arm="conditional",
                                     broad_index_arm="conditional", subtopic_arm="conditional")
    shared = policy["uniform_search"]
    assert shared == fast_path.UNIFORM_SEARCH
    assert shared["rule"] == fast_path.UNIFORM_SEARCH_RULE
    assert (shared["seed_semantic_top"], shared["keyword_page_size"],
            shared["max_provider_requests"], shared["s2_bulk_records"]) == (50, 100, 8, 0)
    assert (policy["semantic_top"], policy["keyword_record_cap"], policy["boolean_plans"],
            policy["chain_seeds"], policy["backward_requests"], policy["backward_page_size"],
            policy["forward_requests"], policy["forward_page_size"], policy["chain_rescue"]) == (
                50, 1000, 2, 1, 4, 50, 2, 100, 10)
    assert policy["field_search"] == {"rule": fast_path.FIELD_SEARCH_RULE, "sources": 1,
                                      "records": 250, "share": 0.25,
                                      "table_version": fast_path.SOURCE_ROUTES_VERSION}
    assert policy["completion"]["records"] == 100 and policy["completion"]["snippet_requests"] == 1
    assert policy["broad_index"]["records"] == 100 and policy["subtopic_search"]["records"] == 0
    assert policy["phrase_search"]["count"] == 6
    assert (policy["phrase_search"]["records"], policy["phrase_search"]["plain_records"]) == (50, 30)
    assert fast_path.search_read(policy, effort, "read_limit_per_query") == 400
    assert fast_path.search_read(policy, effort, "provider_wait") == 1
    assert [policy["stage_base_ms"][stage] for stage in fast_path.STAGES[:3]] == [8000, 14000, 15000]
    assert policy["evidence_minimum"]["search_ms"] == 10000
    assert policy["rerank_allowance"]["ms"] == 3000
    assert (policy["N"], policy["K"], policy["stage_base_ms"]["read"],
            policy["stage_base_ms"]["answer"]) == {
                "quick": (25, 10, 14000, 25000),
                "standard": (50, 20, 33000, 50000),
                "detailed": (100, 40, 108000, 90000),
            }[effort]


@pytest.mark.parametrize("effort", OLD_HASHES)
def test_older_policy_has_the_original_hash_and_effort_limits(effort):
    policy = fast_path.freeze_budget({}, effort, uniform_search=False)
    assert "uniform_search" not in policy
    assert policy["policy_hash"] == OLD_HASHES[effort]
    assert fast_path.search_read(policy, effort, "read_limit_per_query") == SW_READ_LIMIT[effort]
    assert fast_path.search_read(policy, effort, "provider_wait") == PROVIDER_WAIT[effort]


def test_non_discovery_request_presets_remain_per_depth():
    assert [TEST_EFFORT_BUDGETS[effort].max_provider_requests
            for effort in ("quick", "standard", "detailed")] == [3, 8, 12]
