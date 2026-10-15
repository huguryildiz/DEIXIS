"""Mathpix through the app (D40): the key pair routes, the switch and budget, the answer run and the crop image.

The keychain is in memory (conftest), Mathpix and OpenAlex are mocked transports and the PDFs are SYNTHETIC. Passing shows
the app's handling; that Mathpix answers a refused pair with 401 or 403 was not checked live.
"""

import hashlib
import json
import os

import httpx
import pytest
from fastapi.testclient import TestClient
from keyring.errors import KeyringError

from arxiv_helpers import no_network  # noqa: F401
from deixis import credentials
from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents import mathpix
from deixis.domain import contracts
from deixis.workflow import equations
from fakes import FakeAdapter
from mathpix_helpers import FakeMathpix, two_equations
from test_api_flow import create, fake_fetch, openalex_client, session, wait_run


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
def test_the_pair_is_tested_then_saved_as_one_keychain_item_and_never_returned(client_for, memory_keychain):
    client, _, fake = client_for()
    saved = client.put("/api/credentials/mathpix", json=PAIR_BODY)
    assert saved.status_code == 200, saved.text
    assert saved.json()["test"]["status"] == "ok" and saved.json()["mathpix"]["pair"] == {"configured": True, "unreadable": False, "app_id": "synthetic-app"}
    usage = fake.requests[0]
    assert str(usage.url) == mathpix.USAGE_URL and usage.headers["app_id"] == "synthetic-app" and usage.headers["app_key"] == "synthetic-key-0001"
    item = json.loads(memory_keychain.items[("DEIXIS", mathpix.ENV)])
    assert set(item) == {"app_id", "app_key", "revision"} and len(memory_keychain.items) == 1
    assert "synthetic-key-0001" not in client.get("/api/mathpix").text
    assert mathpix.ENV not in {k["env"] for k in client.get("/api/credentials").json()["keys"]}
    again = client.put("/api/credentials/mathpix", json=PAIR_BODY)
    assert json.loads(memory_keychain.items[("DEIXIS", mathpix.ENV)])["revision"] != item["revision"]  # a new revision per save
    assert again.status_code == 200 and client.post("/api/credentials/mathpix/test").json()["status"] == "ok"


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_pair_is_not_saved(client_for, memory_keychain, status):
    client, _, _ = client_for(FakeMathpix(usage=status))
    refused = client.put("/api/credentials/mathpix", json=PAIR_BODY)
    assert refused.status_code == 422 and refused.json()["code"] == "credential_test_failed" and refused.json()["http_status"] == status
    assert memory_keychain.items == {} and not os.environ.get(mathpix.ENV)


def test_a_pair_that_could_not_reach_mathpix_is_saved_untested(client_for, memory_keychain):
    fake = FakeMathpix()

    async def down(request):
        raise httpx.ConnectError("SYNTHETIC", request=request)
    fake.handler = down
    client, _, _ = client_for(fake)
    saved = client.put("/api/credentials/mathpix", json=PAIR_BODY)
    assert saved.status_code == 200 and saved.json()["test"]["status"] == "failed"
    assert ("DEIXIS", mathpix.ENV) in memory_keychain.items


def test_the_generic_key_routes_refuse_the_pair(client_for):
    client, _, _ = client_for()
    for response in (client.put(f"/api/credentials/{mathpix.ENV}", json={"value": "something-long"}),
                     client.delete(f"/api/credentials/{mathpix.ENV}"), client.post(f"/api/credentials/{mathpix.ENV}/test")):
        assert response.status_code == 422 and response.json()["code"] == "use_pair_route"


def test_delete_removes_the_pair(client_for, memory_keychain):
    client, _, _ = client_for()
    client.put("/api/credentials/mathpix", json=PAIR_BODY)
    removed = client.delete("/api/credentials/mathpix")
    assert removed.status_code == 200 and removed.json()["mathpix"]["pair"]["configured"] is False
    assert memory_keychain.items == {} and not os.environ.get(mathpix.ENV)


def test_a_failed_keychain_write_leaves_the_saved_pair_untouched(client_for, memory_keychain, monkeypatch):
    client, _, _ = client_for()
    client.put("/api/credentials/mathpix", json=PAIR_BODY)
    before = memory_keychain.items[("DEIXIS", mathpix.ENV)]

    def broken(service, username, password):
        raise KeyringError("SYNTHETIC")
    monkeypatch.setattr(memory_keychain, "set_password", broken)
    failed = client.put("/api/credentials/mathpix", json=PAIR_BODY | {"app_key": "another-key-0002"})
    assert failed.status_code == 503 and memory_keychain.items[("DEIXIS", mathpix.ENV)] == before
    assert os.environ[mathpix.ENV] == before


def test_an_unreadable_saved_pair_is_absent_and_says_so(client_for, monkeypatch):
    client, app, fake = client_for()
    monkeypatch.setenv(mathpix.ENV, "{not json")
    client.put("/api/mathpix", json={"switch": "on"})
    status = client.get("/api/mathpix").json()
    assert status["pair"] == {"configured": False, "unreadable": True, "app_id": None}
    assert not app.state.equations.mathpix_ready() and fake.requests == []
    assert client.post("/api/credentials/mathpix/test").status_code == 422


# ---- the switch, the budget and the estimate ------------------------------------------------------------------------------
def test_the_switch_and_budget_are_stored_and_the_estimate_sends_nothing(client_for):
    client, app, fake = client_for()
    status = client.get("/api/mathpix").json()
    assert status["switch"] == "off" and status["monthly_budget"] == 500 and status["month_requests"] == 0 and status["per_pdf_limit"] == 60
    rid = create(client, source_scope="attached")
    client.post(f"/api/researches/{rid}/uploads", files={"file": ("paper.pdf", two_equations().tobytes(), "application/pdf")})
    estimate = client.get("/api/mathpix/estimate").json()
    assert estimate == {"pdfs": 1, "upper_bound": 2, "crops": 2} and fake.requests == []
    updated = client.put("/api/mathpix", json={"switch": "on", "monthly_budget": 1}).json()
    assert updated["switch"] == "on" and updated["monthly_budget"] == 1
    assert client.get("/api/mathpix/estimate").json()["upper_bound"] == 1
    assert client.put("/api/mathpix", json={"monthly_budget": -1}).status_code == 422


# ---- the answer run and the passage sheet ----------------------------------------------------------------------------------
def upload(client, rid):
    response = client.post(f"/api/researches/{rid}/uploads", files={"file": ("paper.pdf", two_equations().tobytes(), "application/pdf")})
    source = next(s for s in response.json()["sources"] if s["access"]["assets"])
    return source["source_version_id"], source["access"]["assets"][0]["id"]


def test_an_answer_run_reads_with_mathpix_and_the_passage_shows_its_numbers_fallbacks_and_crops(client_for):
    client, app, fake = client_for()
    assert client.put("/api/credentials/mathpix", json=PAIR_BODY).status_code == 200
    client.put("/api/mathpix", json={"switch": "on"})
    rid = create(client, source_scope="attached")
    svid, aid = upload(client, rid)
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"]
    view, run = wait_run(client, rid, run_id)
    assert run["status"] == "completed", run
    store = app.state.store
    step = store.step(run_id, f"equations:{aid}", "read_equations")
    assert step["status"] == "succeeded" and step["output"]["route"] == "mathpix" and step["output"]["state"] == "read"
    asset = next(s for s in view["sources"] if s["source_version_id"] == svid)["access"]["assets"][0]
    assert asset["equations"]["route"] == "mathpix" and asset["equations"]["mathpix"]["placed"] == 2 and asset["rejected_extraction"] is None
    payload = store.step_input_payload(store.step(run_id, "grounded_answer", "model:grounded_answer")["output"]["step_input_id"])
    assert contracts.check_step_input(payload) == []
    passage = next(p for p in payload["passages"] if p["text_source"] == "equation_ocr")
    assert {f["n"] for f in passage["equation_fallbacks"]} == {"1", "2"}
    assert all("equation_fallbacks" not in p for p in payload["passages"] if p["text_source"] != "equation_ocr")
    shown = client.get(f"/api/researches/{rid}/passages/{passage['passage_id']}").json()
    assert shown["text_source"] == "equation_ocr" and sorted(shown["source_equations"]) == ["1", "2"]
    text = client.get(f"/api/researches/{rid}/assets/{aid}/text").json()
    assert sorted(n for p in text["passages"] for n in p["source_equations"]) == ["1", "2"]
    crop = client.get(f"/api/researches/{rid}/passages/{passage['passage_id']}/equations/1/crop")
    assert crop.status_code == 200 and crop.headers["content-type"] == "image/png"
    math = json.loads(store.conn.execute("SELECT math_json FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'", (aid,)).fetchone()[0])
    assert hashlib.sha256(crop.content).hexdigest() == next(p["crop_sha256"] for p in math["placed"] if p["n"] == "1")
    assert client.get(f"/api/researches/{rid}/passages/{passage['passage_id']}/equations/9/crop").status_code == 404


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


@pytest.mark.parametrize("answer", [500, "skip"])
def test_the_answer_run_never_pauses_for_mathpix_and_honours_answer_now(client_for, answer):
    fake = FakeMathpix([500] if answer == 500 else [])
    client, app, _ = client_for(fake)
    client.put("/api/credentials/mathpix", json=PAIR_BODY)
    client.put("/api/mathpix", json={"switch": "on"})
    rid = create(client, source_scope="attached")
    svid, aid = upload(client, rid)
    if answer == "skip":  # "Answer now with PDF text" chosen while the first crop is being read
        store = app.state.store
        fake.before = lambda count: store.request_equation_skip(
            store.conn.execute("SELECT id FROM runs WHERE kind = 'answer' ORDER BY created_at DESC LIMIT 1").fetchone()[0])
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"]
    _, run = wait_run(client, rid, run_id)
    assert run["status"] == "completed", run
    output = app.state.store.step(run_id, f"equations:{aid}", "read_equations")["output"]
    assert output["route"] == "mathpix"
    if answer == 500:
        assert output["state"] == "failed" and output["reason"] == "server_error"
    else:
        assert output["outcome"] == "skipped" and len(fake.text_requests()) == 1
    assert app.state.store.asset(aid)["extraction_version"].endswith("+mathpix-v1") is False


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
