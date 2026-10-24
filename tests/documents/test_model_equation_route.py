"""The answer model reads numbered display equations from page crops (D113): what is sent, what is accepted, the route
table, budgets, refusals and provenance.

The model is a scripted fake adapter that takes images; no model is called. The PDFs and records are SYNTHETIC. Passing
shows the route's rules and wiring, not how well a model reads equations.
"""

import asyncio
import json

import pytest

from arxiv_helpers import no_network  # noqa: F401
from deixis.documents import equation_model, mathpix, pdf
from deixis.models.adapter import ModelStepResult
from deixis.storage import db
from deixis.workflow import equations
from deixis.workflow.store import EQUATION_PASS, Store
from mathpix_helpers import PAIR, FakeMathpix, prose, two_equations

TARGET = pdf.EXTRACTION_VERSION + "+model-eq-v1"
MODEL = "synthetic-vision-1"
LATEX = {"1": "x=a^{2}+b_{i}", "2": "y=\\frac{c}{d}"}


class FakeImageModel:
    """Answers each call from `script` in order (a ModelStepResult, a LaTeX string, or an exception), else with the right
    LaTeX for the crop's place in a read of the two-equation page. Records what it was sent."""

    connection = "fake_vision"
    accepts_images = True
    key_env = "FAKE_VISION_KEY"

    def __init__(self, script=None, resolved=MODEL):
        self.script = list(script or [])
        self.resolved = resolved
        self.calls = []

    async def run_step(self, base, developer, message, output_schema, requested_model, reasoning_effort=None, image_png=None):
        self.calls.append({"base": base, "developer": developer, "message": message, "schema": output_schema,
                           "model": requested_model, "effort": reasoning_effort, "png": image_png})
        item = self.script.pop(0) if self.script else LATEX[str((len(self.calls) - 1) % 2 + 1)]  # crops (1), (2), (1), ...
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, ModelStepResult):
            return item
        return ModelStepResult("completed", raw_text=json.dumps({"latex": item}), resolved_model=self.resolved,
                               token_usage={"input_tokens": 900, "output_tokens": 40})


class TextOnlyModel:
    connection = "fake_text"

    async def run_step(self, *args, **kwargs):  # pragma: no cover - never called
        raise AssertionError("a connection without image input was asked")


def library(tmp_path, data=None, name="paper.pdf", store=None):
    if store is None:
        conn = db.connect(tmp_path / "library.sqlite")
        db.migrate(conn)
        store = Store(conn)
    svid = store.create_upload_source(f"SYNTHETIC paper {name}")
    papers = tmp_path / "papers"
    papers.mkdir(exist_ok=True)
    path = papers / name
    path.write_bytes(data or two_equations().tobytes())
    aid = store.add_asset_with_pages(svid, f"sha-{name}", 10, name, "user_upload", None, name, pdf.extract_pdf(path),
                                     pdf.EXTRACTION_VERSION, pdf.chunk_page)
    return store, svid, aid, papers


def service(store, papers, tmp_path, model=None, connection="fake_vision", answer_model=MODEL, effort="medium"):
    adapters = {"fake_vision": model if model is not None else FakeImageModel(), "fake_text": TextOnlyModel()}
    svc = equations.EquationService(store, papers, data_dir=tmp_path / "data", adapters=adapters)
    if answer_model:
        store.set_setting("answer", {"model_connection": connection, "model": answer_model, "reasoning_effort": effort})
    return svc


def read(svc, aid, **kw):
    return asyncio.run(svc.read_asset(aid, **kw))


def rows(store):
    return [dict(r) for r in store.conn.execute("SELECT * FROM equation_model_requests ORDER BY rowid")]


def math_of(store, aid):
    row = store.conn.execute("SELECT math_json FROM asset_extractions WHERE asset_id = ? AND extraction_version = ?",
                             (aid, TARGET)).fetchone()
    return json.loads(row["math_json"]) if row else None


# ---- a read ---------------------------------------------------------------------------------------------------------------
def test_a_read_places_the_equations_and_records_the_reader(tmp_path):
    store, svid, aid, papers = library(tmp_path)
    model = FakeImageModel()
    svc = service(store, papers, tmp_path, model)
    assert equations.equation_state(store, aid) == {"state": "pending", "route": "model",
                                                    "reader": {"connection": "fake_vision", "model": MODEL}}
    state = read(svc, aid)
    assert state["state"] == "read" and state["route"] == "model"
    assert state["model"]["placed"] == 2 and state["model"]["refused"] == {}
    assert store.asset(aid)["extraction_version"] == TARGET
    labelled = [p for p in store.passages_for(svid) if p["extraction_version"] == TARGET and p["text_source"] == "equation_ocr"]
    assert "$$\nx=a^{2}+b_{i}\n$$ (1)" in "\n".join(p["text"] for p in labelled)
    math = math_of(store, aid)
    assert math["engine"] == "model" and math["requests"] == 2 and math["reused"] == 0
    assert math["reader"] == {"connection": "fake_vision", "model": MODEL, "reasoning_effort": "medium",
                              "prompt_version": equation_model.PROMPT_VERSION}
    first = math["placed"][0]
    assert first["reader"]["model"] == MODEL and first["reader"]["resolved_model"] == MODEL
    assert all(first["checks"].values()) and first["text_layer"] == "x = a2 + bi" and "confidence" not in first
    assert [r["status"] for r in rows(store)] == ["answered", "answered"] and rows(store)[0]["latex"] == LATEX["1"]
    # Labels and provenance read the reader from the extraction.
    assert equations.equation_reader(TARGET, store, aid) == {"engine": "model", "connection": "fake_vision", "model": MODEL}
    assert equations.crop_provenance(store, aid, TARGET, first["page"], "1")["crop_sha256"] == first["crop_sha256"]
    assert {"n": "1", "text_layer": "x = a2 + bi"} in equations.equation_fallbacks(store, next(p for p in labelled if "(1)" in p["text"]))
    # D45: the model reading is an equation pass laid on the text layer.
    assert EQUATION_PASS.sub("", TARGET) == pdf.EXTRACTION_VERSION


def test_only_the_crop_and_the_fixed_instruction_are_sent(tmp_path):
    store, _, aid, papers = library(tmp_path)
    model = FakeImageModel()
    read(service(store, papers, tmp_path, model), aid)
    call = model.calls[0]
    assert call["png"].startswith(b"\x89PNG") and call["model"] == MODEL and call["effort"] == "medium"
    assert (call["base"], call["developer"], call["message"]) == (equation_model.INSTRUCTION, "", equation_model.MESSAGE)
    assert call["schema"] == equation_model.SCHEMA
    assert "SYNTHETIC" not in call["base"] + call["message"]  # nothing of the paper's text or record


def test_a_second_pdf_with_the_same_crop_reuses_the_answer(tmp_path):
    store, _, aid, papers = library(tmp_path)
    model = FakeImageModel()
    svc = service(store, papers, tmp_path, model)
    read(svc, aid)
    _, _, other, _ = library(tmp_path, name="copy.pdf", store=store)
    state = read(svc, other)
    assert state["state"] == "read" and len(model.calls) == 2
    assert math_of(store, other)["reused"] == 2 and math_of(store, other)["requests"] == 0


def test_another_model_or_effort_does_not_reuse_an_answer(tmp_path):
    store, _, aid, papers = library(tmp_path)
    model = FakeImageModel()
    svc = service(store, papers, tmp_path, model)
    read(svc, aid)
    store.set_setting("answer", {"model_connection": "fake_vision", "model": MODEL, "reasoning_effort": "high"})
    _, _, other, _ = library(tmp_path, name="copy.pdf", store=store)
    read(svc, other)
    assert len(model.calls) == 4 and model.calls[-1]["effort"] == "high"


# ---- answers that are not placed ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("answer,reason", [
    (ModelStepResult("completed", raw_text=json.dumps({"latex": LATEX["1"]}), resolved_model="another-model"), "model_mismatch"),
    (ModelStepResult("completed", raw_text=json.dumps({"latex": LATEX["1"]}), resolved_model=None), "model_mismatch"),
    (ModelStepResult("completed", raw_text="x=a^{2}+b_{i}", resolved_model=MODEL), "invalid_output"),
    (ModelStepResult("completed", raw_text=json.dumps({"latex": LATEX["1"], "note": "x"}), resolved_model=MODEL), "invalid_output"),
    (ModelStepResult("isolation_violation", raw_text="{}", resolved_model=MODEL, tool_item_types=["tool_use"]), "tool_item"),
])
def test_an_answer_that_is_not_accepted_refuses_its_crop_and_is_never_reused(tmp_path, answer, reason):
    store, _, aid, papers = library(tmp_path)
    model = FakeImageModel([answer])
    state = read(service(store, papers, tmp_path, model), aid)
    assert state["state"] == "read" and state["model"]["placed"] == 1 and state["model"]["refused"] == {reason: 1}
    first = rows(store)[0]
    assert first["status"] == "error" and first["reason"] == reason and first["latex"] is None
    assert first["requested_model"] == MODEL and first["resolved_model"] == answer.resolved_model


def test_a_dated_snapshot_of_the_model_is_accepted(tmp_path):
    store, _, aid, papers = library(tmp_path)
    model = FakeImageModel(resolved=MODEL + "-20261001")
    assert read(service(store, papers, tmp_path, model), aid)["model"]["placed"] == 2


def test_the_gate_refuses_a_reading_the_text_layer_contradicts(tmp_path):
    store, _, aid, papers = library(tmp_path)
    model = FakeImageModel(["x=a^{3}+b_{j}", "y=c d"])
    state = read(service(store, papers, tmp_path, model), aid)
    assert state["state"] == "none_placed" and state["refused"] == {"letters_differ": 1, "fractions_differ": 1}
    assert store.asset(aid)["extraction_version"] == pdf.EXTRACTION_VERSION


def test_a_pdf_without_numbered_displays_sends_nothing(tmp_path):
    import pymupdf

    doc = pymupdf.open()
    prose(doc.new_page(width=612, height=792), 90)
    store, _, aid, papers = library(tmp_path, doc.tobytes())
    model = FakeImageModel()
    svc = service(store, papers, tmp_path, model)
    assert read(svc, aid)["state"] == "no_candidates" and model.calls == [] and svc.next_asset() is None


# ---- the route is off -----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("case,reason", [("no_default", "no_answer_model"), ("text_only", "model_no_images"),
                                         ("gone", "connection_unavailable"), ("switch_off", "switch_off")])
def test_without_a_model_that_reads_images_the_route_is_off_and_nothing_is_sent(tmp_path, case, reason):
    store, _, aid, papers = library(tmp_path)
    model = FakeImageModel()
    connection = {"text_only": "fake_text", "gone": "nowhere"}.get(case, "fake_vision")
    svc = service(store, papers, tmp_path, model, connection=connection, answer_model=None if case == "no_default" else MODEL)
    if case == "switch_off":
        store.set_setting(equations.MODEL_SWITCH, "off")
    assert equations.equation_state(store, aid) == {"state": "off", "reason": reason, "route": "model"}
    assert read(svc, aid)["state"] == "off" and model.calls == [] and rows(store) == []
    assert not svc.crop_active() and svc.next_asset() is None and equations.background_read_waiting(store, aid) is None
    assert svc.model_status()["ready"] is False and svc.model_status()["reason"] == reason


def test_mathpix_ready_reads_first(tmp_path, monkeypatch):
    monkeypatch.setenv(mathpix.ENV, PAIR)
    store, _, aid, papers = library(tmp_path)
    model = FakeImageModel()
    svc = service(store, papers, tmp_path, model)
    svc.configure_mathpix(tmp_path / "data", FakeMathpix().client())
    store.set_setting(equations.MATHPIX_SWITCH, "on")
    assert read(svc, aid)["route"] == "mathpix" and model.calls == []
    assert svc.model_status()["mathpix_first"] is True


def test_an_earlier_marker_reading_is_kept_and_never_read_again(tmp_path):
    store, _, aid, papers = library(tmp_path)
    version = equations.target_version(pdf.EXTRACTION_VERSION)
    store.conn.execute("UPDATE source_assets SET extraction_version = ? WHERE id = ?", (version, aid))
    model = FakeImageModel()
    svc = service(store, papers, tmp_path, model)
    assert equations.equation_state(store, aid)["state"] == "read" and equations.equation_state(store, aid)["route"] == "marker"
    assert read(svc, aid)["state"] == "read" and model.calls == [] and svc.next_asset() is None


# ---- failures and budgets -------------------------------------------------------------------------------------------------
def test_a_refused_key_stops_sending_until_the_key_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_VISION_KEY", "key-one")
    store, _, aid, papers = library(tmp_path)
    refused = ModelStepResult("failed", error="HTTP 401: API request failed", http_status=401, error_kind="auth_failed",
                              delivery_class="after_send_unknown")
    model = FakeImageModel([refused])
    svc = service(store, papers, tmp_path, model)
    state = read(svc, aid)
    assert state["state"] == "model_refused" and len(model.calls) == 1
    assert read(svc, aid, retry=True)["state"] == "model_refused" and len(model.calls) == 1 and svc.next_asset() is None
    monkeypatch.setenv("FAKE_VISION_KEY", "key-two")  # a new key: a new revision
    assert equations.equation_state(store, aid)["state"] == "pending"
    model.calls.clear()
    assert read(svc, aid)["state"] == "read"


def test_a_rate_limit_is_a_failed_attempt_tried_again_and_counted(tmp_path):
    store, _, aid, papers = library(tmp_path)
    limited = ModelStepResult("failed", error="HTTP 429", http_status=429, error_kind="rate_limited")
    model = FakeImageModel([limited])
    svc = service(store, papers, tmp_path, model)
    state = read(svc, aid)
    assert state["state"] == "failed" and state["reason"] == "rate_limited" and state["attempts"] == 1
    assert equations.model_counts(store, aid)["asset"] == 1
    model.calls.clear()
    assert read(svc, aid, retry=True)["state"] == "read"


def test_an_error_before_sending_is_not_counted(tmp_path):
    store, _, aid, papers = library(tmp_path)
    unsent = ModelStepResult("unavailable", error="ConnectError", delivery_class="before_send")
    svc = service(store, papers, tmp_path, FakeImageModel([unsent]))
    assert read(svc, aid)["state"] == "failed"
    assert rows(store)[0]["status"] == "error" and equations.model_counts(store, aid)["asset"] == 0


def test_a_call_cancelled_mid_request_stays_counted_as_unknown(tmp_path):
    store, _, aid, papers = library(tmp_path)
    svc = service(store, papers, tmp_path, FakeImageModel([asyncio.CancelledError()]))
    with pytest.raises(asyncio.CancelledError):
        read(svc, aid)
    assert [r["status"] for r in rows(store)] == ["unknown"] and equations.model_counts(store, aid)["asset"] == 1
    cost = equations.model_month_cost(store)
    assert cost["calls_without_cost"] == 1  # an unknown call has no known cost, never 0


def test_the_monthly_budget_stops_sending_and_the_answered_crop_is_placed(tmp_path):
    store, _, aid, papers = library(tmp_path)
    model = FakeImageModel()
    svc = service(store, papers, tmp_path, model)
    store.set_setting(equations.MODEL_BUDGET, 1)
    state = read(svc, aid)
    assert state["state"] == "read" and state["model"]["placed"] == 1 and state["model"]["refused"] == {"budget_reached": 1}
    assert len(model.calls) == 1
    status = svc.model_status()
    assert status["month_requests"] == 1 and status["monthly_budget"] == 1 and status["month_cost"]["calls_without_cost"] == 1


def test_an_adapter_error_is_a_failed_attempt_bounded_like_a_network_failure(tmp_path):
    store, _, aid, papers = library(tmp_path)
    svc = service(store, papers, tmp_path, FakeImageModel([ValueError("unreadable body")]))
    state = read(svc, aid)
    assert state["state"] == "failed" and state["reason"] == "network" and state["attempts"] == 1
    assert [r["status"] for r in rows(store)] == ["unknown"] and equations.model_month_cost(store)["calls_without_cost"] == 1


def test_an_unknown_call_with_partial_usage_has_no_known_cost(tmp_path):
    store, _, aid, papers = library(tmp_path)
    partial = ModelStepResult("failed", error="Incomplete stream", delivery_class="after_send_unknown",
                              resolved_model=MODEL, token_usage={"input_tokens": 900, "output_tokens": 3})
    read(service(store, papers, tmp_path, FakeImageModel([partial])), aid)
    assert rows(store)[0]["status"] == "unknown" and equations.model_month_cost(store)["calls_without_cost"] == 1


def test_a_model_read_is_not_shown_as_an_arxiv_read_while_the_source_route_is_on(tmp_path, monkeypatch):
    store, _, aid, papers = library(tmp_path)
    svc = service(store, papers, tmp_path)
    monkeypatch.setattr(equations.arxiv_source, "posix_available", lambda: True)
    svc.reading = {"asset_id": aid, "title": None, "pages": 1, "started_at": "x", "route": "model"}
    asset = store.asset(aid)
    assert equations._source_state(store, asset)["state"] != "reading"


# ---- the spend ledger (D115) ----------------------------------------------------------------------------------------------
# The equation reader on a paid-API connection books each request in the spend ledger, so the day's total, the daily
# threshold and Settings → Usage count it. claude-sonnet-5-5 is $2 / $10 per million: 900 in + 40 out is $0.0022.

PAID_MODEL = "claude-sonnet-5-5"


def paid_service(store, papers, tmp_path, model):
    svc = equations.EquationService(store, papers, data_dir=tmp_path / "data", adapters={"anthropic": model})
    store.set_setting("answer", {"model_connection": "anthropic", "model": PAID_MODEL, "reasoning_effort": "medium"})
    return svc


def ledger_rows(store):
    return {r["session_id"]: dict(r) for r in store.conn.execute("SELECT * FROM spend_ledger")}


def test_paid_equation_requests_count_in_the_days_total_the_threshold_and_the_usage_rows(tmp_path):
    from datetime import UTC, datetime

    from deixis.api import usage_routes
    from deixis.workflow import spend
    store, _, aid, papers = library(tmp_path)
    assert read(paid_service(store, papers, tmp_path, FakeImageModel(resolved=PAID_MODEL)), aid)["state"] == "read"
    booked = ledger_rows(store)
    assert set(booked) == {r["id"] for r in rows(store)} and len(booked) == 2  # one row per request, under its own id
    assert all(r["connection"] == "anthropic" and r["model"] == PAID_MODEL and r["basis"] == "reported"
               and r["cost_usd"] == pytest.approx(0.0022) for r in booked.values())
    total = spend.day_total(store.conn, spend.day_of(store.clock))
    assert total["estimated_usd"] == pytest.approx(0.0044) and total["priced_calls"] == 2 and total["unpriced_calls"] == 0
    assert spend.over_threshold(store) is None  # threshold off
    store.set_setting(spend.THRESHOLD_SETTING, 0.004)
    assert spend.over_threshold(store)["estimated_usd"] == pytest.approx(0.0044)
    store.set_setting(spend.THRESHOLD_SETTING, 0.01)
    assert spend.over_threshold(store) is None
    usage = {r["connection"]: r for r in asyncio.run(usage_routes.connection_rows(store, {}, datetime.now(UTC)))}
    assert usage["anthropic"]["roles"] == ["answer"]
    assert usage["anthropic"]["spend"]["estimated_usd"] == pytest.approx(0.0044) and usage["anthropic"]["spend"]["priced_calls"] == 2
    # The route's own month figure reads the same rows: one source, nothing counted twice.
    assert equations.model_month_cost(store) == {"usd": pytest.approx(0.0044), "calls_without_cost": 0}


def test_an_unknown_paid_request_is_booked_unpriced_and_one_never_sent_is_not_booked(tmp_path):
    from deixis.workflow import spend
    store, _, aid, papers = library(tmp_path)
    partial = ModelStepResult("failed", error="Incomplete stream", delivery_class="after_send_unknown",
                              resolved_model=PAID_MODEL, token_usage={"input_tokens": 900, "output_tokens": 3})
    unsent = ModelStepResult("unavailable", error="ConnectError", delivery_class="before_send")
    svc = paid_service(store, papers, tmp_path, FakeImageModel([partial]))
    read(svc, aid)
    svc.adapters["anthropic"] = FakeImageModel([unsent])
    read(svc, aid, retry=True)
    statuses = {r["id"]: r["status"] for r in rows(store)}
    assert sorted(statuses.values()) == ["error", "unknown"]
    booked = ledger_rows(store)
    (unknown,) = [i for i, s in statuses.items() if s == "unknown"]
    assert set(booked) == {unknown} and booked[unknown]["cost_usd"] is None and booked[unknown]["basis"] == "unpriced"
    total = spend.day_total(store.conn, spend.day_of(store.clock))
    assert total["estimated_usd"] == 0 and total["unpriced_calls"] == 1  # may have been billed: never read as $0
    assert equations.model_month_cost(store) == {"usd": 0, "calls_without_cost": 1}


def test_requests_stored_before_the_ledger_are_booked_once_at_start_and_repriced_like_sessions(tmp_path, monkeypatch):
    from deixis.workflow import spend
    store, _, aid, papers = library(tmp_path)
    read(paid_service(store, papers, tmp_path, FakeImageModel(resolved=PAID_MODEL)), aid)
    store.conn.execute("DELETE FROM spend_ledger")  # as a library from before D115
    store.conn.commit()
    real = spend.price_table()
    monkeypatch.setattr(spend, "price_table", lambda: {**real, "models": {**real["models"], "anthropic": {}}})
    with db.transaction(store.conn):
        assert spend.book_equation_requests(store.conn) == 2
    assert {r["basis"] for r in ledger_rows(store).values()} == {"unpriced"}
    with db.transaction(store.conn):
        assert spend.book_equation_requests(store.conn) == 0
    monkeypatch.setattr(spend, "price_table", lambda: real)
    with db.transaction(store.conn):
        assert spend.reprice_unpriced(store.conn) == 2
    assert all(r["cost_usd"] == pytest.approx(0.0022) and r["repriced_price_list"] == real["as_of"]
               for r in ledger_rows(store).values())
