"""Every equation reading passes the text-layer gate before it is placed, and the model reader sends only the crop and its fixed instruction. SYNTHETIC crops; the model is mocked."""

import pytest
from deixis.documents import equation_regions as er
import pymupdf
from mathpix_helpers import AFTER, ANSWERS, fraction, number, prose, scripted, two_equations
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


def test_the_finder_crops_displays_beside_lead_in_words_painted_bars_and_page_numbers(tmp_path):
    # D139: a fraction bar painted as a thin image, a lone "where" above a display and "i.e.," above one refused all
    # three; each now gets a crop of exactly its own lines. An image that is not a bar still refuses.
    def page(picture=False):
        doc = pymupdf.open()
        pg = doc.new_page(width=612, height=792)
        y = prose(pg, 90) + 20
        x = scripted(pg, 250, y, [("y = ", "base")])
        end = fraction(pg, x, y, "c", "d", bar=False)
        bar = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 4, 1), False)
        bar.clear_with(0)
        pg.insert_image(pymupdf.Rect(x, y - 3.74, end, y - 3.26), pixmap=bar, keep_proportion=False)
        if picture:
            square = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 4, 4), False)
            square.clear_with(0)
            pg.insert_image(pymupdf.Rect(x + 1, y - 9, x + 5, y + 1), pixmap=square)
        number(pg, y, "1")
        y = prose(pg, y + 30, [AFTER, "where"]) + 10
        scripted(pg, 250, y, [("u = v + w", "base")])
        number(pg, y, "2")
        y = prose(pg, y + 24, [AFTER])
        pg.insert_text((260, y + 4), "i.e.,", fontsize=10, fontname="helv")
        scripted(pg, 250, y + 24, [("p = q", "base"), ("2", "raised")])
        number(pg, y + 24, "3")
        return doc
    _, found = detect(tmp_path, page(), render=False)
    assert [(f["n"], f.get("refused"), f["text_layer"]) for f in found] == [
        ("1", None, "y = c\nd"), ("2", None, "u = v + w"), ("3", None, "p = q2")]
    assert found[0]["rules"] == 1  # the painted bar counts as the fraction's bar for the gate
    _, found = detect(tmp_path, page(picture=True), name="picture.pdf", render=False)
    assert found[0]["refused"] == "crop_has_other_content"

    # Sol r1: a digit just under a display and last on the page may be its denominator; a row under it with a sentence
    # word and a relation may be its constraint; a small square image is not a bar. None of these is left out of
    # a crop that is sent.
    def tricky(kind):
        doc = pymupdf.open()
        pg = doc.new_page(width=612, height=792)
        y = prose(pg, 90) + 20
        scripted(pg, 250, y, [("y = c", "base")])
        number(pg, y, "1")
        if kind == "digit":
            pg.insert_text((262, y + 11), "7", fontsize=10, fontname="helv")
        elif kind == "far denominator":  # Sol r2: a bar under `c`, its `7` set low and last on the page
            pg.draw_line((262, y - 3.5), (270, y - 3.5), width=0.4)
            pg.insert_text((262, y + 24), "7", fontsize=10, fontname="helv")
        elif kind == "bar below":  # Sol r3: the bar itself just below the crop, the `7` under it
            pg.draw_line((262, y + 6), (270, y + 6), width=0.4)
            pg.insert_text((262, y + 25), "7", fontsize=10, fontname="helv")
        elif kind == "bar through c":  # Sol r4: the bar crosses `c`'s text box, the `7` far below
            pg.draw_line((262, y + 1.5), (270, y + 1.5), width=0.4)
            pg.insert_text((262, y + 25), "7", fontsize=10, fontname="helv")
        elif kind == "constraint":
            pg.insert_text((72, y + 14), "average power satisfies x = y", fontsize=10, fontname="helv")
            prose(pg, y + 40, [AFTER])
        else:
            dot = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 1, 1), False)
            dot.clear_with(0)
            pg.insert_image(pymupdf.Rect(270, y - 5, 271, y - 4), pixmap=dot)
            prose(pg, y + 30, [AFTER])
        return doc
    for kind in ("digit", "far denominator", "bar below", "bar through c", "constraint", "square"):
        _, found = detect(tmp_path, tricky(kind), name=kind + ".pdf", render=False)
        assert found[0].get("refused") in ("region_unclear", "crop_has_other_content") or (
            "digit" in kind and "7" in found[0]["text_layer"]), kind  # refused, or the digit is in the crop


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


