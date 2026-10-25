"""What happens to a model's output after it answers: identity stamps, normalisation that is recorded, the transport
record, image input and exact model identity.

FakeAdapter and mocked HTTP. Passing shows workflow handling, not model quality.
"""

import asyncio
import base64
import copy
import httpx
import json
import pytest

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents import equation_model
from deixis.documents.fetch import FetchResult
from deixis.domain import contracts
from deixis.domain import skill
from deixis.domain.contracts import normalise_output
from deixis.models import anthropic_api
from deixis.models import gemini
from deixis.models import openai_api
from deixis.models.adapter import ModelStepResult
from deixis.models.gemini import GeminiAdapter
from deixis.providers.registry import CONNECTORS
from deixis.storage import db
from deixis.storage.db import new_id
from deixis.workflow.flow import FlowDeps
from deixis.workflow.flow import ResearchFlow
from deixis.workflow.flow import RunStopped
from deixis.workflow.store import Store
from fakes import FakeAdapter
from fakes import valid_response
from test_abstract_flow import Pool
from test_abstract_flow import client_of
from test_abstract_flow import discover
from test_abstract_flow import work
from test_contracts import STEP_INPUTS
from test_report_path_fix import Capture
from test_report_path_fix import run_step
from test_report_path_fix import sessions
from test_report_step_input import report_flow


FOREIGN_ID = "sti_FOREIGNREQUEST01"


def id_changes(row):
    return [c for c in json.loads(row["validation_json"])["normalised"] if c.get("stamped") == "step_input_id"]


@pytest.mark.parametrize("model_id", [FOREIGN_ID])
@pytest.mark.parametrize("task,key", [
    ("report_section", "C_report_section_IV"),
])
def test_new_behavior_initial_wrong_or_missing_id_is_stamped(tmp_path, task, key, model_id):
    def response(si, schema, message):
        draft = json.loads(valid_response(si))
        if model_id is None:
            draft.pop("step_input_id")
        else:
            draft["step_input_id"] = model_id
        return draft

    output, store, adapter, _, _ = run_step(tmp_path, task, STEP_INPUTS[key], response)
    assert not output.get("invalid"), output
    assert len(adapter.calls) == 1
    row = sessions(store)[0]
    assert output["result"]["step_input_id"] == output["step_input_id"] == row["step_input_id"]
    assert id_changes(row) == [{"path": "/step_input_id", "stamped": "step_input_id", "model_value": model_id}]
    assert json.loads(row["raw_output"]).get("step_input_id") == model_id


def setup_request(tmp_path, response, *, attempt_record=None):
    flow, store, _, run, scope, _, _ = report_flow(tmp_path)
    adapter = Capture(response)
    flow.deps.adapters["fake"] = adapter

    def builder(step_id):
        si = copy.deepcopy(STEP_INPUTS["C_report_section_IV"])
        si.update(step_id=step_id, step_input_id=new_id("sti"), research_id=run["research_id"], run_id=run["id"],
                  scope_revision=run["scope_revision"], skill_package_hash=flow.deps.package.package_hash,
                  model={"connection": "fake", "requested_model": "fake-model"})
        si["report_target"].setdefault("validation_context", None)
        return si

    async def execute():
        return await flow._model_step(run, scope, "RF6:section", "report_section",
                                      model=("fake", "fake-model", None), step_input_builder=builder,
                                      attempt_record=attempt_record)

    return flow, store, adapter, run, execute


@pytest.mark.parametrize("change", ["session_closed"])
def test_new_behavior_late_or_superseded_result_is_recorded_without_step_change(tmp_path, change):
    expected_step = None
    expected_session = None

    def response(si, schema, message):
        nonlocal expected_step, expected_session
        row = sessions(store)[0]
        if change.startswith("session_closed"):
            previous = {"raw_output": "SYNTHETIC previous result", "validation_json": {"ok": True}} if change.endswith("with_output") else {}
            store.finish_model_session(row["id"], status="interrupted", **previous)
            expected_session = dict(sessions(store)[0])
        elif change == "new_session_same_input":
            store.start_model_session(run["research_id"], run["id"], si["step_id"], si["step_input_id"], "fake", "fake-model")
        elif change == "new_input":
            newer = dict(si, step_input_id=new_id("sti"))
            store.insert_step_input(si["step_id"], run["research_id"], run["id"], 1, newer, "base", "developer", "message", schema)
        else:
            store.finish_step(si["step_id"], "cancelled", output={"sentinel": "keep"})
            if change == "step_reopened":
                store.start_step(si["step_id"])
        expected_step = dict(store.conn.execute("SELECT * FROM run_steps WHERE id = ?", (si["step_id"],)).fetchone())
        return json.loads(valid_response(si))

    _, store, adapter, run, execute = setup_request(tmp_path, response)
    with pytest.raises(RunStopped):
        asyncio.run(execute())
    assert dict(store.conn.execute("SELECT * FROM run_steps WHERE id = ?", (adapter.calls[0]["step_id"],)).fetchone()) == expected_step
    row = sessions(store)[0]
    assert row["raw_output"] == ("SYNTHETIC previous result" if change == "session_closed_with_output" else adapter.raw[0])
    assert json.loads(row["validation_json"])["discarded_results"][0]["code"] == "model_attempt_inactive"
    if change.startswith("session_closed"):
        assert row["status"] == "interrupted"
        assert row["finished_at"] == expected_session["finished_at"]
    if change == "session_closed_with_output":
        assert json.loads(row["validation_json"])["ok"]
        assert json.loads(row["validation_json"])["discarded_results"][0]["raw_output"] == adapter.raw[0]
    if change == "new_session_same_input":
        assert sessions(store)[1]["status"] == "started" and sessions(store)[1]["raw_output"] is None


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


def test_a_missing_required_field_is_not_normalised():
    draft = {"parts": [{"verdict": "present", "quote": "q", "rationale": "r"}],
             "step_input_id": "x", "scope_revision": 1, "skill_package_hash": "h", "schema_version": "v"}
    result, changes = contracts.normalise_output("fulltext_adjudication", draft)
    assert "passage_id" not in result["parts"][0]
    assert result["parts"][0]["label"] == "present"
    assert len(changes) == 1


def test_raw_output_is_unchanged_by_normalisation():
    raw = '{"parts": [{"name": "m", "verdict": "present", "quote": "q", "passage_id": "p1", "rationale": "r"}]}'
    draft = json.loads(raw)
    contracts.normalise_output("fulltext_adjudication", draft)
    assert json.loads(raw) != draft


ON_TOPIC = "SYNTHETIC greenhouse crop irrigation scheduling report"


ON_ABSTRACT = "We vary the irrigation scheduling of a greenhouse tomato crop and report the marketable yield."


def _app_with_adapter(tmp_path, monkeypatch, adapter, handler):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    return create_app(
        Settings(data_dir=tmp_path / "data", port=8765, search_query="code",
                 fulltext_fetch="off", fulltext_adjudication="off"),
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


TRANSPORT = {"schema_transform": "SYNTHETIC.v1", "sent_schema_sha256": "sha256:" + "0" * 64, "filled_nulls": ["/x"]}


def run(tmp_path, transport):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("SYNTHETIC question?", "attached", "quick", [], "fake", "fake-model", "en")
    sid = store.create_upload_source("SYNTHETIC source")
    pid = store._insert_passage(sid, None, "abstract", None, None, "synthetic_fixture", None, None,
                                "SYNTHETIC passage about release scheduling.")
    adapter = FakeAdapter(fail=lambda si: ModelStepResult("completed", raw_text=valid_response(si),
                                                          resolved_model="fake-model", transport=transport))
    flow = ResearchFlow(FlowDeps(Settings(data_dir=tmp_path / "data", port=8873), store, {"fake": adapter},
                                 skill.load_skill_package(), None))
    run = store.create_run(rid, "answer", {"max_model_calls": 2, "max_provider_requests": 0}, None)
    store.update_run(run["id"], status="running")
    result = asyncio.run(flow._model_step(store.run(run["id"]), store.scope(rid), "synthetic:answer", "grounded_answer",
                                          source_ids=[sid], passage_rows=[store.passage(pid)]))
    validation = json.loads(store.conn.execute("SELECT validation_json FROM model_sessions WHERE step_input_id = ?",
                                               (result["step_input_id"],)).fetchone()[0])
    store.conn.close()
    return result, validation


def test_the_adapters_transport_record_is_stored_with_the_validation(tmp_path):
    result, validation = run(tmp_path, TRANSPORT)
    assert not result.get("invalid") and validation["ok"]
    assert validation["transport"] == TRANSPORT


PNG = b"\x89PNG\r\n\x1a\nSYNTHETIC"


ENCODED = base64.standard_b64encode(PNG).decode()


def sent(module, cls, env, monkeypatch, image):
    monkeypatch.setenv(env, "test-key")
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(400, json={"error": {"type": "invalid_request_error"}})

    adapter = cls(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    kwargs = {"image_png": PNG} if image else {}
    asyncio.run(adapter.run_step(equation_model.INSTRUCTION, "", equation_model.MESSAGE, equation_model.SCHEMA, "m-1", None, **kwargs))
    assert adapter.accepts_images is True and adapter.key_env == env
    return seen[0]


@pytest.mark.parametrize("image", [True])
def test_anthropic_puts_the_png_before_the_message(monkeypatch, image):
    body = sent(anthropic_api, anthropic_api.AnthropicAdapter, "ANTHROPIC_API_KEY", monkeypatch, image)
    content = body["messages"][0]["content"]
    if image:
        assert content == [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": ENCODED}},
                           {"type": "text", "text": equation_model.MESSAGE}]
    else:
        assert content == equation_model.MESSAGE
    assert len(body["messages"]) == 1 and body["system"].startswith(equation_model.INSTRUCTION)


@pytest.mark.parametrize("image", [True])
def test_openai_sends_the_png_as_an_input_image(monkeypatch, image):
    body = sent(openai_api, openai_api.OpenAIAdapter, "OPENAI_API_KEY", monkeypatch, image)
    if image:
        assert body["input"] == [{"role": "user", "content": [
            {"type": "input_image", "image_url": "data:image/png;base64," + ENCODED},
            {"type": "input_text", "text": equation_model.MESSAGE}]}]
    else:
        assert body["input"] == equation_model.MESSAGE
    assert body["store"] is False


@pytest.mark.parametrize("requested,answered,accepted", [
    ("gemini-x", "gemini-x", True),
    ("gemini-x", "gemini-x-001", False),
])
def test_exact_identity_rule(requested, answered, accepted, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "SYNTHETIC-key")
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        "modelVersion": answered, "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "{}"}]}}],
    })))
    result = asyncio.run(GeminiAdapter(client).run_step("b", "d", "m", {}, requested))
    assert result.status == "completed" and result.resolved_model == answered
    assert result.requested_model_verified is False
    # This is the acceptance expression read in flow.py; completion alone is not identity verification.
    assert (result.resolved_model == requested or result.requested_model_verified) is accepted
