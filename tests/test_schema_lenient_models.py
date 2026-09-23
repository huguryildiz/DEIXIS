"""Schema-lenient model support (D86, slice 13a).

Tests that a non-enforcing adapter sees the schema and skeleton, that the alias table normalises
field names without changing values, that an enforcing adapter's StepInput is unchanged, and that
the reading run completes with `not_reached` instead of pausing when repairs consume the budget.
Records are SYNTHETIC and from two fields.
"""

import json
import time

import httpx
import pytest
from jsonschema import Draft202012Validator

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents.fetch import FetchResult
from deixis.domain import contracts
from deixis.domain.contracts import normalise_output
from deixis.models import prompt
from deixis.models.adapter import ModelStepResult
from deixis.providers.registry import CONNECTORS
from deixis.workflow.decisions import DecisionStore
from fakes import FakeAdapter, envelope, parse_step_input, valid_response
from helpers import make_pdf
from test_abstract_flow import QUESTION, Pool, client_of, discover, records_of, wait, work


# ---------------------------------------------------------------------------
# Task 2: skeleton appendix
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("task_type", ["abstract_screening", "fulltext_adjudication", "grounded_answer"])
def test_skeleton_carries_every_required_field_and_validates(task_type):
    schema = contracts.step_output_schema(task_type)
    appendix = prompt.schema_appendix(task_type, schema)
    assert "Use exactly these field names" in appendix
    skeleton_json = appendix.split("--- Example skeleton (use exactly these field names) ---\n")[1].split(
        "\n\nUse exactly these field names")[0]
    skeleton = json.loads(skeleton_json)
    for field in schema.get("required", []):
        assert field in skeleton, f"required field {field!r} missing from skeleton"


# ---------------------------------------------------------------------------
# Task 3: alias normalisation
# ---------------------------------------------------------------------------

def test_a_renamed_field_is_normalised_and_recorded():
    draft = {"parts": [{"name": "method", "verdict": "present", "quote": "q", "passage_id": "p1", "rationale": "r"}],
             "step_input_id": "x", "scope_revision": 1, "skill_package_hash": "h", "schema_version": "v"}
    result, changes = contracts.normalise_output("fulltext_adjudication", draft)
    assert result["parts"][0]["part"] == "method"
    assert result["parts"][0]["label"] == "present"
    assert "name" not in result["parts"][0]
    assert "verdict" not in result["parts"][0]
    assert len(changes) == 2
    assert any(c["renamed_to"] == "part" for c in changes)
    assert any(c["renamed_to"] == "label" for c in changes)


def test_claim_label_case_is_lowered_and_recorded():
    draft = {"claims": [{"claim_label": "C1", "text": "t", "passage_ids": ["p1"], "support_type": "source_stated", "section": "s"}],
             "citation_anchors": [{"claim_label": "C1", "passage_id": "p1", "quote": "q"}],
             "title": "t", "answer_language": "en", "limitations": [], "unanswered_aspects": [], "capability_notice": None,
             "step_input_id": "x", "scope_revision": 1, "skill_package_hash": "h", "schema_version": "v"}
    result, changes = contracts.normalise_output("grounded_answer", draft)
    assert result["claims"][0]["claim_label"] == "c1"
    assert result["citation_anchors"][0]["claim_label"] == "c1"
    assert len(changes) == 2
    assert all(c["lowered_to"] == "c1" for c in changes)


def test_a_missing_required_field_is_not_normalised():
    draft = {"parts": [{"verdict": "present", "quote": "q", "rationale": "r"}],
             "step_input_id": "x", "scope_revision": 1, "skill_package_hash": "h", "schema_version": "v"}
    result, changes = contracts.normalise_output("fulltext_adjudication", draft)
    assert "passage_id" not in result["parts"][0]
    assert result["parts"][0]["label"] == "present"
    assert len(changes) == 1


def test_a_wrong_label_value_is_not_changed():
    draft = {"parts": [{"part": "method", "label": "yes", "quote": "q", "passage_id": "p1", "rationale": "r"}],
             "step_input_id": "x", "scope_revision": 1, "skill_package_hash": "h", "schema_version": "v"}
    result, changes = contracts.normalise_output("fulltext_adjudication", draft)
    assert result["parts"][0]["label"] == "yes"
    assert changes == []


def test_both_source_and_target_present_leaves_both_untouched():
    draft = {"parts": [{"name": "extra", "part": "method", "label": "present", "quote": "q", "passage_id": "p1", "rationale": "r"}],
             "step_input_id": "x", "scope_revision": 1, "skill_package_hash": "h", "schema_version": "v"}
    result, changes = contracts.normalise_output("fulltext_adjudication", draft)
    assert "name" in result["parts"][0] and "part" in result["parts"][0]
    assert changes == []


def test_raw_output_is_unchanged_by_normalisation():
    raw = '{"parts": [{"name": "m", "verdict": "present", "quote": "q", "passage_id": "p1", "rationale": "r"}]}'
    draft = json.loads(raw)
    contracts.normalise_output("fulltext_adjudication", draft)
    assert json.loads(raw) != draft


def test_normalisation_returns_empty_changes_for_unlisted_task():
    draft = {"labels": [{"phrase": "a", "block": "setting"}], "step_input_id": "x", "scope_revision": 1,
             "skill_package_hash": "h", "schema_version": "v"}
    _, changes = contracts.normalise_output("vocabulary_labels", draft)
    assert changes == []


def test_abstract_screening_verdict_is_renamed_to_label():
    draft = {"records": [{"candidate_id": "c1", "verdict": "candidate", "quote": "q", "rationale": "r"}],
             "step_input_id": "x", "scope_revision": 1, "skill_package_hash": "h", "schema_version": "v"}
    result, changes = contracts.normalise_output("abstract_screening", draft)
    assert result["records"][0]["label"] == "candidate"
    assert "verdict" not in result["records"][0]
    assert len(changes) == 1


# ---------------------------------------------------------------------------
# Task 2 + flow: enforcing vs non-enforcing StepInput
# ---------------------------------------------------------------------------

ON_TOPIC = "SYNTHETIC greenhouse crop irrigation scheduling report"
ON_ABSTRACT = "We vary the irrigation scheduling of a greenhouse tomato crop and report the marketable yield."


def _app_with_adapter(tmp_path, monkeypatch, adapter, handler):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    return create_app(
        Settings(data_dir=tmp_path / "data", port=8765, search_workflow="sw", search_query="code",
                 protocol_approval="as_proposed", fulltext_fetch="off", fulltext_adjudication="off"),
        adapters={"fake": adapter},
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        fetcher=lambda url: FetchResult("http_error", final_url=url, http_status=404),
        extra_hosts=("testserver",), trusted_clients=("testclient",),
    )


def _step_inputs(store, run_id):
    rows = store.conn.execute(
        "SELECT developer_instructions FROM step_inputs WHERE run_id = ? ORDER BY rowid", (run_id,)
    ).fetchall()
    return [row[0] for row in rows]


def test_non_enforcing_adapter_step_input_carries_schema_appendix(tmp_path, monkeypatch):
    pool = Pool([work(1, ON_TOPIC, ON_ABSTRACT)])
    adapter = FakeAdapter(valid_response, enforces_schema=False)
    app = _app_with_adapter(tmp_path, monkeypatch, adapter, pool)
    client = client_of(app)
    rid, run_id, view, run = discover(client, effort="quick")
    devs = _step_inputs(app.state.store, run_id)
    schema_devs = [d for d in devs if "--- Output schema ---" in d]
    assert len(schema_devs) > 0, "no StepInput carries the schema appendix"
    for d in schema_devs:
        assert "Use exactly these field names" in d


def test_enforcing_adapter_step_input_has_no_schema_appendix(tmp_path, monkeypatch):
    pool = Pool([work(1, ON_TOPIC, ON_ABSTRACT)])
    adapter_enforcing = FakeAdapter(valid_response, enforces_schema=True)
    adapter_non = FakeAdapter(valid_response, enforces_schema=False)
    app_e = _app_with_adapter(tmp_path, monkeypatch, adapter_enforcing, pool)
    client_e = client_of(app_e)
    rid_e, run_id_e, _, _ = discover(client_e, effort="quick")
    devs_e = _step_inputs(app_e.state.store, run_id_e)
    for d in devs_e:
        assert "--- Output schema ---" not in d


# ---------------------------------------------------------------------------
# Task 4: budget with repair allowance — reading run completes with not_reached
# ---------------------------------------------------------------------------

def _adjudication_app(tmp_path, monkeypatch, *, adapter, budget, concurrency=1, num_works=20):
    """Build an sw research through discovery + fulltext + adjudication."""
    works_list = [work(i, ON_TOPIC, ON_ABSTRACT) for i in range(1, num_works + 1)]
    pool = Pool(works_list)

    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    return create_app(
        Settings(data_dir=tmp_path / "data", port=8765, search_workflow="sw", search_query="code",
                 protocol_approval="as_proposed", fulltext_fetch="off",
                 fulltext_adjudication="auto", model_concurrency=concurrency),
        adapters={"fake": adapter},
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(pool)),
        fetcher=lambda url: FetchResult("http_error", final_url=url, http_status=404),
        extra_hosts=("testserver",), trusted_clients=("testclient",),
    ), pool


def test_a_review_output_given_as_text_has_its_claim_labels_lowered():
    raw = json.dumps({"reviews": [{"claim_label": "C1", "verdict": "supported", "reason": "SYNTHETIC"}]})
    draft, changes = normalise_output("answer_review", raw)
    assert draft["reviews"][0]["claim_label"] == "c1"
    assert changes == [{"path": "/reviews/0/claim_label", "lowered_to": "c1"}]


def test_text_that_is_not_a_json_object_is_returned_as_it_came():
    assert normalise_output("fulltext_adjudication", "{") == ("{", [])
    assert normalise_output("fulltext_adjudication", "[1]") == ("[1]", [])
