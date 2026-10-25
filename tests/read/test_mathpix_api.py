"""Mathpix through the app (D40): the key pair routes, the switch and budget, the answer run and the crop image.

The keychain is in memory (conftest), Mathpix and OpenAlex are mocked transports and the PDFs are SYNTHETIC. Passing shows
the app's handling; that Mathpix answers a refused pair with 401 or 403 was not checked live.
"""

import asyncio
import json
import threading
import httpx
import pytest
from fastapi.testclient import TestClient
from deixis.keys import credentials
from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents import mathpix
from deixis.domain import contracts
from deixis.workflow.read import equations
from fakes import FakeAdapter
from mathpix_helpers import FakeMathpix, prose, two_equations
from test_api_flow import create, fake_fetch, openalex_client, session, wait_run
from arxiv_helpers import no_network  # noqa: F401  (fixtures used by name)


def make_app(tmp_path, monkeypatch, fake):
    monkeypatch.setattr(equations.EquationService, "start", lambda self: None)  # only the answer run reads here
    openalex = openalex_client(200)

    async def handler(request):
        if request.url.host == "api.mathpix.com":
            return await fake.handler(request)
        return await openalex._transport.handle_async_request(request)
    settings = Settings(data_dir=tmp_path / "data", port=8765, arxiv_source="off")
    return create_app(settings, adapters={"fake": FakeAdapter()}, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                      fetcher=fake_fetch, extra_hosts=("testserver",), trusted_clients=("testclient",))


@pytest.fixture
def client_for(tmp_path, monkeypatch):
    opened = []

    def build(fake=None):
        fake = fake or FakeMathpix()
        app = make_app(tmp_path, monkeypatch, fake)
        raw = TestClient(app)
        raw.__enter__()
        opened.append(raw)
        return session(raw), app, fake
    yield build
    for raw in opened:
        raw.__exit__(None, None, None)


PAIR_BODY = {"app_id": "synthetic-app", "app_key": "synthetic-key-0001"}


# ---- the key pair -------------------------------------------------------------------------------------------------------
SECRET = "SYNTHETICsecretKEY9"


@pytest.mark.parametrize("route,body", [
    ("/api/credentials/mathpix", {"app_id": "synthetic-app", "app_key": SECRET + " with spaces"}),  # pattern
    pytest.param("/api/credentials/OPENALEX_API_KEY", {"value": SECRET + " x"}, id="/api/credentials/OPENALEX_API_KEY-body5"),  # the generic key route too
])
def test_a_refused_key_never_comes_back_in_the_validation_answer(client_for, memory_keychain, route, body):
    # Sol r1 finding 1: FastAPI's default 422 puts the submitted value in `detail[].input` (and the limit in `ctx`).
    client, _, fake = client_for()
    response = client.put(route, json=body)
    assert response.status_code == 422
    assert SECRET not in response.text and "SYNTHETICsecret" not in response.text
    assert all(set(item) <= {"type", "loc", "msg"} for item in response.json()["detail"])
    assert fake.requests == [] and memory_keychain.items == {}


def test_the_pair_is_tested_then_saved_as_one_keychain_item_and_never_returned(client_for, memory_keychain):
    client, _, fake = client_for()
    saved = client.put("/api/credentials/mathpix", json=PAIR_BODY)
    assert saved.status_code == 200, saved.text
    assert saved.json()["test"]["status"] == "ok" and saved.json()["mathpix"]["pair"] == {"configured": True, "unreadable": False, "keychain_unavailable": False, "keychain_pending": False, "app_id": "synthetic-app"}
    usage = fake.requests[0]
    assert str(usage.url) == mathpix.USAGE_URL and usage.headers["app_id"] == "synthetic-app" and usage.headers["app_key"] == "synthetic-key-0001"
    item = json.loads(memory_keychain.items[("DEIXIS", mathpix.ENV)])
    assert set(item) == {"app_id", "app_key", "revision"} and len(memory_keychain.items) == 1
    assert "synthetic-key-0001" not in client.get("/api/mathpix").text
    assert mathpix.ENV not in {k["env"] for k in client.get("/api/credentials").json()["keys"]}
    again = client.put("/api/credentials/mathpix", json=PAIR_BODY)
    assert json.loads(memory_keychain.items[("DEIXIS", mathpix.ENV)])["revision"] != item["revision"]  # a new revision per save
    assert again.status_code == 200 and client.post("/api/credentials/mathpix/test").json()["status"] == "ok"


# ---- the answer run and the passage sheet ----------------------------------------------------------------------------------
def upload(client, rid):
    response = client.post(f"/api/researches/{rid}/uploads", files={"file": ("paper.pdf", two_equations().tobytes(), "application/pdf")})
    source = next(s for s in response.json()["sources"] if s["access"]["assets"])
    return source["source_version_id"], source["access"]["assets"][0]["id"]


def test_an_anchor_found_only_in_a_fallback_is_a_contract_error():
    fixtures = __import__("pathlib").Path(__file__).parent.parent / "fixtures/research"
    step_input = json.loads((fixtures / "step-inputs.json").read_text())["A_answer"]
    case = next(c for c in json.loads((fixtures / "fake-outputs.json").read_text())["cases"]
                if c["step_input"] == "A_answer" and c["expect_ok"])
    output = case["output"]
    anchor = output["citation_anchors"][1]
    passage = next(p for p in step_input["passages"] if p["passage_id"] == anchor["passage_id"])
    passage["text_source"] = "equation_ocr"
    passage["equation_fallbacks"] = [{"n": "1", "text_layer": "UNIQUE FALLBACK WORDS"}]
    assert contracts.check_step_input(step_input) == []
    assert not contracts.validate_model_output(step_input, json.dumps(output)).issues
    anchor["quote"] = "UNIQUE FALLBACK WORDS"
    assert "anchor_not_in_passage" in {i.code for i in contracts.validate_model_output(step_input, json.dumps(output)).issues}
    passage["equation_fallbacks"] = [{"n": "1", "text_layer": "x", "extra": 1}]
    assert [i.code for i in contracts.check_step_input(step_input)] == ["step_input_schema_invalid"]


def test_the_read_again_action_is_offered_for_saved_mathpix_answers_with_an_honest_label():
    # Sol r2 finding 3: the retry route accepts a Mathpix PDF at its budget with saved answers; the UI offered it only on
    # `failed`. The label says nothing new is sent; without saved answers, or for a reading, it is not offered.
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    script = r"""
const fs = require('fs'), ts = require('typescript'), assert = require('assert');
require.extensions['.ts'] = (module, file) => module._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
}).outputText, file);
const labels = require('./src/lib/labels.ts'), i18n = require('./src/lib/i18n.ts');
const at = { state: 'budget_reached', route: 'mathpix', month: 5, budget: 5, asset: 2 };
i18n.setUiLanguage('en');
assert.strictEqual(labels.rereadEquationsLabel({ ...at, stored_answers: true }), 'Read again from saved results · no new requests');
assert.strictEqual(labels.rereadEquationsLabel({ ...at, stored_answers: false }), null);
assert.strictEqual(labels.rereadEquationsLabel({ state: 'read', route: 'mathpix', mathpix: { placed: 1, pages: [1], refused: {} } }), null);
assert.strictEqual(labels.rereadEquationsLabel({ state: 'failed', route: 'mathpix', reason: 'network', attempts: 1 }), 'Read equations again');
assert.strictEqual(labels.rereadEquationsLabel(undefined), null);
i18n.setUiLanguage('tr');
assert.strictEqual(labels.rereadEquationsLabel({ ...at, stored_answers: true }), 'Kayıtlı sonuçlardan yeniden oku · yeni istek gönderilmez');
for (const file of ['src/reading/PassageSheet.tsx', 'src/research/SourceRow.tsx']) {
  const source = fs.readFileSync(file, 'utf8');
  assert(source.includes('rereadEquationsLabel(asset.equations)'), file);
  assert(!/equations\?\.state === 'failed' && <(DropdownMenuItem|button)/.test(source), file);
}
"""
    result = subprocess.run(["node", "-e", script], cwd=root / "web", capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_every_step_that_takes_passages_accepts_their_equation_fallbacks():
    # Sol r1 (fallback scope): `_step_input` builds passages for every model step, so each one carries the field for an
    # equation_ocr passage. Every task shares the one StepInput passage schema; this checks each fixture task accepts it.
    fixtures = __import__("pathlib").Path(__file__).parent.parent / "fixtures/research"
    inputs = json.loads((fixtures / "step-inputs.json").read_text())
    tasks = set()
    for name, step_input in inputs.items():
        pdf_passages = [p for p in (step_input.get("passages") or []) if p.get("text_source")] if isinstance(step_input, dict) else []
        if not pdf_passages:
            continue
        pdf_passages[0]["text_source"] = "equation_ocr"
        pdf_passages[0]["equation_fallbacks"] = [{"n": "1", "text_layer": "x = a2 + bi"}]
        assert contracts.check_step_input(step_input) == [], name
        tasks.add(step_input["task_type"])
    assert {"grounded_answer", "followup_answer", "report_section", "fulltext_adjudication", "lineage_links"} <= tasks


def test_an_anchor_inside_a_mathpix_equation_is_warned_and_one_outside_is_not():
    # Sol r1 finding 5 (r3): the answer validator names a quote that rests on Mathpix's reading of the page image.
    fixtures = __import__("pathlib").Path(__file__).parent.parent / "fixtures/research"
    step_input = json.loads((fixtures / "step-inputs.json").read_text())["A_answer"]
    case = next(c for c in json.loads((fixtures / "fake-outputs.json").read_text())["cases"]
                if c["step_input"] == "A_answer" and c["expect_ok"])
    output = case["output"]
    anchor = output["citation_anchors"][1]
    passage = next(p for p in step_input["passages"] if p["passage_id"] == anchor["passage_id"])
    passage["text"] += "\n$$\nq_{k}=\\frac{r_{k}}{s_{k}}\n$$ (7)\nwhere SYNTHETIC trailing words follow."
    warned = lambda: [w for w in contracts.validate_model_output(step_input, json.dumps(output)).warnings if w.code == "anchor_in_ocr_equation"]
    anchor["quote"] = "q_{k}=\\frac{r_{k}}{s_{k}}"
    assert warned() == []  # the same passage as text layer: nothing to say
    passage["text_source"] = "equation_ocr"
    assert [w.path for w in warned()] == ["/citation_anchors/1/quote"]
    assert not contracts.validate_model_output(step_input, json.dumps(output)).issues  # a warning, not a refusal
    anchor["quote"] = "SYNTHETIC trailing words follow"
    assert warned() == []


def test_the_contracts_and_the_method_package_name_equation_ocr():
    from deixis.domain import skill
    from test_arxiv_source_migration import section_case, validate

    assert contracts.SCHEMA_VERSIONS["ReportSectionDraft"] == "deixis.report_section_draft.v3"
    step_input, output = section_case()
    claim = output["claims"][0]
    cited = claim["passage_ids"][0]
    passage = next(p for p in step_input["passages"] if p["passage_id"] == cited)
    passage["text"] += " $$x=1$$ (1)"
    passage["text_source"] = "equation_ocr"
    passage["equation_fallbacks"] = [{"n": "1", "text_layer": "x = 1"}]
    claim["equation_origin"] = {"passage_id": cited, "text_source": "equation_ocr"}
    assert not [i for i in validate(step_input, output).issues if i.code.startswith("equation_origin")]
    claim["equation_origin"] = {"passage_id": cited, "text_source": "latex_source"}
    assert "equation_origin_mismatch" in {i.code for i in validate(step_input, output).issues}
    assert skill.integrity_issues() == []
    for name in ("source-grounded-answer.md", "evidence-table.md"):
        text = (skill.SKILL_DIR / "references" / name).read_text()
        assert "`equation_ocr` is the PDF's own text of a passage" in text and "cannot be cited" in text


# 'Answer now with PDF text': the person stops reading equations during an answer run.

def skip_upload(client, rid, name):
    doc = two_equations()
    prose(doc.new_page(width=612, height=792), 90, [f"SYNTHETIC appendix of {name}."])  # a different file per name
    response = client.post(f"/api/researches/{rid}/uploads", files={"file": (name, doc.tobytes(), "application/pdf")})
    assert response.status_code == 201, response.text[:300]


def skip_mathpix_on(client):
    assert client.put("/api/credentials/mathpix", json=PAIR_BODY).status_code == 200
    client.put("/api/mathpix", json={"switch": "on"})


def skip_steps_of(run):
    return {s["operation_key"]: s for s in run["steps"]}


def test_pressing_the_button_mid_way_skips_the_remaining_pdfs_and_the_answer_is_written(client_for):
    gate, entered = threading.Event(), threading.Event()

    async def before(count):
        entered.set()
        while not gate.is_set():
            await asyncio.sleep(0.01)
    fake = FakeMathpix(before=before)
    client, app, _ = client_for(fake)
    skip_mathpix_on(client)
    rid = create(client, source_scope="attached")
    for name in ("a.pdf", "b.pdf", "c.pdf"):
        skip_upload(client, rid, name)
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"]
    assert entered.wait(20)
    assert client.post(f"/api/runs/{run_id}/skip-equations").status_code == 200
    assert client.post(f"/api/runs/{run_id}/skip-equations").status_code == 200  # pressed twice: recorded once
    gate.set()
    _, run = wait_run(client, rid, run_id)
    assert run["status"] == "completed", run
    steps = skip_steps_of(run)
    assert len(fake.text_requests()) == 1  # the crop in flight finished; nothing else was sent
    assert steps["equations_skipped"]["output"] == {"pdfs_read": 1, "pdfs_skipped": 2}
    assert steps["equations_skip"]["status"] == "succeeded" and "grounded_answer" in steps
