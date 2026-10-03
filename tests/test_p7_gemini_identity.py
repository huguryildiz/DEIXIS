"""The existing fail-closed equality rule, without assuming live alias mappings."""
import asyncio

import httpx
import pytest

from deixis.models.gemini import GeminiAdapter
from deixis.config import Settings
from deixis.domain import skill
from deixis.storage import db
from deixis.workflow.flow import FlowDeps, ResearchFlow, RunStopped
from deixis.workflow.store import Store


@pytest.mark.parametrize("requested,answered,accepted", [
    ("gemini-x", "gemini-x", True),
    ("gemini-x", "gemini-x-001", False),
    ("gemini-x", "gemini-x-20261003", False),
    ("gemini-x", "gemini-x-10-03", False),
    ("gemini-x-001", "gemini-x-001", True),
    ("gemini-x-001", "gemini-x-002", False),
    ("gemini-x", "gemini-y", False),
    ("gemini-x", None, False),
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


@pytest.mark.parametrize("answered", ["gemini-x-001", "gemini-x-20261003", "gemini-y", None])
def test_workflow_rejects_nonexact_identity(answered, monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "SYNTHETIC-key")
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        "modelVersion": answered, "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "{}"}]}}],
    })))
    conn = db.connect(tmp_path / "library.sqlite")
    try:
        db.migrate(conn)
        store = Store(conn)
        rid = store.create_research("SYNTHETIC question", "attached", "quick", [], "gemini", "gemini-x", "en")
        run = store.create_run(rid, "answer", {"max_model_calls": 2, "max_provider_requests": 0}, None)
        store.update_run(run["id"], status="running")
        flow = ResearchFlow(FlowDeps(Settings(data_dir=tmp_path / "data", port=8871), store,
                                   {"gemini": GeminiAdapter(client)}, skill.load_skill_package(), None))
        with pytest.raises(RunStopped):
            asyncio.run(flow._model_step(store.run(run["id"]), store.scope(rid), "synthetic:answer", "grounded_answer"))
        assert store.run(run["id"])["pause_reason"] == "model_mismatch"
        assert conn.execute("SELECT COUNT(*) FROM answers").fetchone()[0] == 0
        saved = conn.execute("SELECT resolved_model, raw_output FROM model_sessions").fetchone()
        assert tuple(saved) == (answered, "{}")
    finally:
        conn.close()
