"""'Answer now with PDF text': a person's choice to stop reading equations during an answer run.

Mathpix (D40) is a scripted mock transport and the PDFs are SYNTHETIC; passing these tests shows the workflow, not
reading quality.
"""

import asyncio
import threading

from arxiv_helpers import no_network  # noqa: F401
from mathpix_helpers import FakeMathpix, prose, two_equations
from test_api_flow import create, wait_run
from test_mathpix_api import PAIR_BODY, client_for  # noqa: F401


def upload(client, rid, name):
    doc = two_equations()
    prose(doc.new_page(width=612, height=792), 90, [f"SYNTHETIC appendix of {name}."])  # a different file per name
    response = client.post(f"/api/researches/{rid}/uploads", files={"file": (name, doc.tobytes(), "application/pdf")})
    assert response.status_code == 201, response.text[:300]


def mathpix_on(client):
    assert client.put("/api/credentials/mathpix", json=PAIR_BODY).status_code == 200
    client.put("/api/mathpix", json={"switch": "on"})


def steps_of(run):
    return {s["operation_key"]: s for s in run["steps"]}


def test_pressing_the_button_mid_way_skips_the_remaining_pdfs_and_the_answer_is_written(client_for):
    gate, entered = threading.Event(), threading.Event()

    async def before(count):
        entered.set()
        while not gate.is_set():
            await asyncio.sleep(0.01)
    fake = FakeMathpix(before=before)
    client, app, _ = client_for(fake)
    mathpix_on(client)
    rid = create(client, source_scope="attached")
    for name in ("a.pdf", "b.pdf", "c.pdf"):
        upload(client, rid, name)
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"]
    assert entered.wait(20)
    assert client.post(f"/api/runs/{run_id}/skip-equations").status_code == 200
    assert client.post(f"/api/runs/{run_id}/skip-equations").status_code == 200  # pressed twice: recorded once
    gate.set()
    _, run = wait_run(client, rid, run_id)
    assert run["status"] == "completed", run
    steps = steps_of(run)
    assert len(fake.text_requests()) == 1  # the crop in flight finished; nothing else was sent
    assert steps["equations_skipped"]["output"] == {"pdfs_read": 1, "pdfs_skipped": 2}
    assert steps["equations_skip"]["status"] == "succeeded" and "grounded_answer" in steps


def test_without_the_button_every_pdf_is_read_and_no_skip_is_recorded(client_for):
    fake = FakeMathpix()
    client, app, _ = client_for(fake)
    mathpix_on(client)
    rid = create(client, source_scope="attached")
    for name in ("a.pdf", "b.pdf"):
        upload(client, rid, name)
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"]
    _, run = wait_run(client, rid, run_id)
    # both PDFs draw the same two equations: the second reuses the first one's answered crops
    assert run["status"] == "completed" and len(fake.text_requests()) == 2
    steps = steps_of(run)
    assert "equations_skipped" not in steps and "equations_skip" not in steps
    assert [s["output"]["state"] for k, s in steps.items() if k.startswith("equations:")] == ["read", "read"]


def test_the_route_refuses_a_run_that_is_not_reading(client_for):
    client, app, _ = client_for(FakeMathpix())
    mathpix_on(client)
    rid = create(client, source_scope="attached")
    upload(client, rid, "a.pdf")
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"]
    _, run = wait_run(client, rid, run_id)
    assert run["status"] == "completed"
    assert client.post(f"/api/runs/{run_id}/skip-equations").status_code == 409
    assert not app.state.store.equation_skip_requested(run_id)
