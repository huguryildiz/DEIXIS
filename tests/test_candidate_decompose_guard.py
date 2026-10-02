"""Paused candidate runs block new starts, but never an idempotent replay."""
import pytest

from test_candidate_api import api, candidate_url, open_owner


def decompose(api, candidate, key):
    return api.client.post(candidate_url(api, candidate) + "/decompose", headers={"Idempotency-Key": key})


@pytest.mark.parametrize("kind", ["claim_decomposition", "kill_search"])
def test_paused_candidate_blocks_both_starts_but_not_another_candidate_or_replay(api, kind):
    candidate = open_owner(api)
    first = decompose(api, candidate, "first").json()
    api.store.update_run(first["id"], status="paused", pause_reason="user_requested")
    if kind == "kill_search":
        api.conn.execute("UPDATE runs SET kind='kill_search' WHERE id=?", (first["id"],))
    refused = decompose(api, candidate, "second")
    assert refused.status_code == 409
    assert refused.json()["detail"] == f"Resume or cancel paused candidate run {first['id']} first"
    refused_search = api.client.post(candidate_url(api, candidate) + "/kill-search", json={"preview_fingerprint": "a" * 64})
    assert refused_search.status_code == 409
    assert refused_search.json()["detail"] == refused.json()["detail"]
    if kind == "claim_decomposition":
        assert decompose(api, candidate, "first").json()["id"] == first["id"]
    other = open_owner(api, text="SYNTHETIC another sentence")
    assert decompose(api, other, "other").status_code == 202


@pytest.mark.parametrize("status", ["cancelled", "completed"])
def test_terminal_run_does_not_block_a_new_decomposition(api, status):
    candidate = open_owner(api)
    first = decompose(api, candidate, "first").json()
    api.store.update_run(first["id"], status=status)
    assert decompose(api, candidate, "next").status_code == 202
