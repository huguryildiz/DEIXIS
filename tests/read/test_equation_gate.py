"""Every equation reading passes the text-layer gate before it is placed, and the model reader sends only the crop and its fixed instruction. SYNTHETIC crops; the model is mocked."""

import pytest
from deixis.documents import equation_regions as er
from mathpix_helpers import ANSWERS, prose, two_equations
import asyncio
import json
from deixis.documents import equation_model, pdf
from deixis.models.adapter import ModelStepResult
from deixis.storage import db
from deixis.workflow.read import equations
from deixis.workflow.run.store import Store
from arxiv_helpers import no_network  # noqa: F401  (fixtures used by name)


def detect(tmp_path, doc, name="eq.pdf", **kw):
    path = tmp_path / name
    path.write_bytes(doc.tobytes())
    return path, er.detect(path, **kw)


# ---- the gate ----------------------------------------------------------------------------------------------------------
def candidate(chars, signs=None, rules=0):
    return {"chars": [list(c) for c in chars], "signs": signs or {}, "rules": rules}


def answer(latex, confidence=0.99):
    return {"latex_styled": latex, "confidence": confidence, "confidence_rate": confidence}


X2 = [("x", "base"), ("2", "raised")]


def test_the_gate_passes_a_reading_that_agrees_with_the_text_layer():
    found = er.gate(candidate([("x", "base"), ("a", "base"), ("2", "raised"), ("b", "base"), ("i", "lowered")], {"=": 1, "+": 1}),
                    ANSWERS["1"])
    assert found == {"latex": "x=a^{2}+b_{i}", "reason": None,
                     "checks": {"katex": True, "letters": True, "scripts": True, "known_signs": True, "operators": True,
                                "fractions": True}}


@pytest.mark.parametrize("response", [
    pytest.param(answer("x^{2} \\tag{1}"), id="response4"),
])
def test_a_missing_or_numbered_reading_is_not_a_single_equation(response):
    assert er.gate(candidate(X2), response)["reason"] == "not_single_equation"


def test_sols_counterexamples_are_refused():
    # x^2 read as x_2: same letters, wrong level.
    assert er.gate(candidate(X2), answer("x_{2}"))["reason"] == "script_differs"
    # x_i - y_j read as x_j + y_i: letters and levels agree, the sign does not.
    chars = [("x", "base"), ("i", "lowered"), ("y", "base"), ("j", "lowered")]
    assert er.gate(candidate(chars, {"−": 1}), answer("x_{j}+y_{i}"))["reason"] == "operators_differ"
    # a/b with a bar on the page read as a b.
    assert er.gate(candidate([("a", "base"), ("b", "base")], rules=1), answer("a b"))["reason"] == "fractions_differ"
    assert er.gate(candidate([("a", "base"), ("b", "base")], rules=1), answer("\\frac{a}{b}"))["reason"] is None


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


def test_the_crops_of_a_pdf_are_read_at_once_and_placed_in_order(tmp_path):
    """D136: the model reads up to MODEL_PARALLEL crops of a PDF at the same time; the answers are placed by their crop."""
    class SlowModel(FakeImageModel):
        live = peak = 0

        async def run_step(self, *args, **kwargs):
            SlowModel.live += 1
            SlowModel.peak = max(SlowModel.peak, SlowModel.live)
            await asyncio.sleep(0.05)
            SlowModel.live -= 1
            return await super().run_step(*args, **kwargs)

    store, _, aid, papers = library(tmp_path)
    assert read(service(store, papers, tmp_path, SlowModel()), aid)["state"] == "read"
    assert SlowModel.peak == 2  # both crops of the page in flight together
    assert [r["status"] for r in rows(store)] == ["answered", "answered"]


def test_only_the_crop_and_the_fixed_instruction_are_sent(tmp_path):
    store, _, aid, papers = library(tmp_path)
    model = FakeImageModel()
    read(service(store, papers, tmp_path, model), aid)
    call = model.calls[0]
    assert call["png"].startswith(b"\x89PNG") and call["model"] == MODEL and call["effort"] == "medium"
    assert (call["base"], call["developer"], call["message"]) == (equation_model.INSTRUCTION, "", equation_model.MESSAGE)
    assert call["schema"] == equation_model.SCHEMA
    assert "SYNTHETIC" not in call["base"] + call["message"]  # nothing of the paper's text or record


