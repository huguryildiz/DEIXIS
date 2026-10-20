"""The Mathpix route in the equation service (D40): requests, budgets, the route table, the write guard and provenance.

Mathpix is a scripted `httpx.MockTransport` (`mathpix_helpers.FakeMathpix`). No answer model is set in Settings, so the model route is off.
The PDFs and records are SYNTHETIC. Passing shows the route's rules and wiring, not how well Mathpix reads equations.
"""

import asyncio
import json

import httpx
import pytest

from arxiv_helpers import no_network  # noqa: F401
from deixis.documents import equation_regions, mathpix, pdf
from deixis.storage import db
from deixis.storage.db import now
from deixis.workflow import equations
from deixis.workflow.store import Store
from mathpix_helpers import ANSWERS, PAIR, FakeMathpix, prose, two_equations
from test_arxiv_source_route import FakeFetch

TARGET = pdf.EXTRACTION_VERSION + "+mathpix-v1"


def library(tmp_path, data=None):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    svid = store.create_upload_source("SYNTHETIC paper with numbered equations")
    papers = tmp_path / "papers"
    papers.mkdir(exist_ok=True)
    path = papers / "paper.pdf"
    path.write_bytes(data or two_equations().tobytes())
    aid = store.add_asset_with_pages(svid, "sha-a", 10, "paper.pdf", "user_upload", None, "paper.pdf", pdf.extract_pdf(path),
                                     pdf.EXTRACTION_VERSION, pdf.chunk_page)
    return store, svid, aid, papers


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv(mathpix.ENV, PAIR)


def service(store, papers, tmp_path, fake=None, mode="off", switch="on"):
    svc = equations.EquationService(store, papers)
    svc.configure_arxiv_source(mode, tmp_path / "data", fetch_file=FakeFetch())
    svc.configure_mathpix(tmp_path / "data", (fake or FakeMathpix()).client())
    if switch:
        store.set_setting(equations.MATHPIX_SWITCH, switch)
    return svc


def read(svc, aid, **kw):
    return asyncio.run(svc.read_asset(aid, **kw))


def rows(store):
    return [dict(r) for r in store.conn.execute("SELECT * FROM mathpix_requests ORDER BY rowid")]


def mathpix_extraction(store, aid):
    return store.conn.execute("SELECT * FROM asset_extractions WHERE asset_id = ? AND extraction_version = ?", (aid, TARGET)).fetchone()


# ---- a read ---------------------------------------------------------------------------------------------------------------
def test_a_read_places_the_equations_labels_their_chunks_and_records_provenance(tmp_path, on):
    store, svid, aid, papers = library(tmp_path)
    fake = FakeMathpix()
    svc = service(store, papers, tmp_path, fake)
    assert equations.equation_state(store, aid) == {"state": "pending", "route": "mathpix"}
    state = read(svc, aid)
    assert state["state"] == "read" and state["route"] == "mathpix" and state["mathpix"] == {"placed": 2, "pages": [1], "refused": {}}
    assert store.asset(aid)["extraction_version"] == TARGET
    passages = [p for p in store.passages_for(svid) if p["extraction_version"] == TARGET]
    labelled = [p for p in passages if p["text_source"] == "equation_ocr"]
    assert labelled and all("$$" in p["text"] for p in labelled)
    assert "$$\nx=a^{2}+b_{i}\n$$ (1)" in "\n".join(p["text"] for p in labelled)
    assert all("$$" not in p["text"] for p in passages if p["text_source"] == "text_layer")
    math = json.loads(mathpix_extraction(store, aid)["math_json"])
    assert math["engine"] == "mathpix" and math["requests"] == 2 and math["reused"] == 0 and math["candidates"] == 2
    first = math["placed"][0]
    assert {"page", "n", "start", "end", "box", "crop", "crop_sha256", "request_row_id", "request_id", "provider_version",
            "confidence", "confidence_rate", "checks", "text_layer"} <= set(first)
    assert first["request_id"] == "req-1" and first["provider_version"] is None and first["text_layer"] == "x = a2 + bi"
    assert all(first["checks"].values()) and first["crop"]["page"] == 1 and first["crop"]["dpi"] == equation_regions.DPI
    assert [r["status"] for r in rows(store)] == ["answered", "answered"] and rows(store)[0]["id"] == first["request_row_id"]
    # The passage lists its own Mathpix numbers, and the model input carries the text layer of each one beside it.
    passage = next(p for p in labelled if "(1)" in p["text"])
    assert equations.chunk_numbers(equations.latex_numbers(store, aid, TARGET), passage["physical_page"], passage["payload_ref"]) == ["1"] \
        or "1" in equations.chunk_numbers(equations.latex_numbers(store, aid, TARGET), passage["physical_page"], passage["payload_ref"])
    fallbacks = equations.equation_fallbacks(store, passage)
    assert {"n": "1", "text_layer": "x = a2 + bi"} in fallbacks
    assert equations.equation_fallbacks(store, passage | {"text_source": "text_layer"}) is None


def test_the_request_carries_the_pair_one_crop_and_the_no_training_flag(tmp_path, on):
    store, _, aid, papers = library(tmp_path)
    fake = FakeMathpix()
    read(service(store, papers, tmp_path, fake), aid)
    request = fake.text_requests()[0]
    assert str(request.url) == mathpix.TEXT_URL and request.method == "POST"
    assert request.headers["app_id"] == "synthetic-app" and request.headers["app_key"] == "synthetic-key-0001"
    body = json.loads(request.content)
    assert set(body) == {"src", "formats", "rm_spaces", "metadata"}
    assert body["src"].startswith("data:image/png;base64,") and body["formats"] == ["latex_styled"] and body["rm_spaces"] is True
    assert body["metadata"] == {"improve_mathpix": False}


def test_a_pdf_without_numbered_displays_is_no_candidates_and_sends_nothing(tmp_path, on):
    import pymupdf

    doc = pymupdf.open()
    prose(doc.new_page(width=612, height=792), 90)
    store, _, aid, papers = library(tmp_path, doc.tobytes())
    fake = FakeMathpix()
    svc = service(store, papers, tmp_path, fake)
    assert read(svc, aid)["state"] == "no_candidates" and fake.requests == [] and svc.next_asset() is None


def test_every_crop_refused_is_none_placed_with_its_reasons_and_terminal(tmp_path, on):
    store, _, aid, papers = library(tmp_path)
    low = {"latex_styled": "x=a^{2}+b_{i}", "confidence": 0.2}
    svc = service(store, papers, tmp_path, FakeMathpix([low, {"latex_styled": "y=c d", "confidence": 0.9}]))
    state = read(svc, aid)
    assert state == {"state": "none_placed", "route": "mathpix", "refused": {"low_confidence": 1, "fractions_differ": 1}}
    assert svc.next_asset() is None and store.asset(aid)["extraction_version"] == pdf.EXTRACTION_VERSION


# ---- nothing is sent ------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("case", ["switch_off", "keys_missing", "pair_unreadable"])
def test_no_request_without_the_switch_or_a_readable_pair(tmp_path, monkeypatch, case):
    monkeypatch.setenv(mathpix.ENV, "not json" if case == "pair_unreadable" else PAIR)
    if case == "keys_missing":
        monkeypatch.delenv(mathpix.ENV)
    store, _, aid, papers = library(tmp_path)
    fake = FakeMathpix()
    svc = service(store, papers, tmp_path, fake, switch="off" if case == "switch_off" else "on")
    off = {"state": "off", "reason": "no_answer_model", "route": "model"}
    assert equations.equation_state(store, aid) == off
    assert not svc.mathpix_active()
    assert read(svc, aid) == off
    assert fake.requests == []


def test_an_extraction_changed_after_detection_stops_before_the_first_request(tmp_path, on, monkeypatch):
    store, _, aid, papers = library(tmp_path)
    fake = FakeMathpix()
    svc = service(store, papers, tmp_path, fake)
    real = equation_regions.detect

    def detect(*args, **kw):
        found = real(*args, **kw)
        store.conn.execute("UPDATE asset_extractions SET outcome = 'superseded' WHERE asset_id = ?", (aid,))
        return found
    monkeypatch.setattr(equation_regions, "detect", detect)
    state = read(svc, aid)
    assert state["outcome"] == "extraction_changed" and fake.requests == [] and rows(store) == []


# ---- failures, reuse and budgets -------------------------------------------------------------------------------------------
def test_a_rate_limited_read_fails_and_its_retry_reuses_the_answered_crop(tmp_path, on):
    store, _, aid, papers = library(tmp_path)
    fake = FakeMathpix([ANSWERS["1"], 429])
    svc = service(store, papers, tmp_path, fake)
    state = read(svc, aid)
    assert state["state"] == "failed" and state["reason"] == "rate_limited" and state["attempts"] == 1
    assert [(r["status"], r["http_status"]) for r in rows(store)] == [("answered", 200), ("error", 429)]
    fake.script = [ANSWERS["2"]]
    state = read(svc, aid, retry=True)
    assert state["state"] == "read" and len(fake.text_requests()) == 3  # crop 1 was not sent again
    math = json.loads(mathpix_extraction(store, aid)["math_json"])
    assert math["reused"] == 1 and math["requests"] == 1


def test_the_monthly_budget_stops_sending_and_the_answered_crops_are_still_placed(tmp_path, on):
    # Sol r1 finding 2: a budget that stops sending keeps what was paid for; the crop left unsent is refused budget_reached.
    store, _, aid, papers = library(tmp_path)
    fake = FakeMathpix()
    svc = service(store, papers, tmp_path, fake)
    store.set_setting(equations.MATHPIX_BUDGET, 1)
    state = read(svc, aid)
    assert len(fake.text_requests()) == 1
    assert state["state"] == "read" and state["mathpix"] == {"placed": 1, "pages": [1], "refused": {"budget_reached": 1}}
    assert store.asset(aid)["extraction_version"] == TARGET and svc.next_asset() is None


def many_equations(n):
    """`n` numbered displays `x = k` (k = 1..n), each between two prose lines, over as many pages as they need."""
    import pymupdf

    from mathpix_helpers import AFTER, number, scripted

    doc = pymupdf.open()
    k = 0
    while k < n:
        page = doc.new_page(width=612, height=792)
        y = prose(page, 80, [AFTER])
        while k < n and y < 700:
            y += 22
            k += 1
            scripted(page, 250, y, [(f"x = {k}", "base")])
            number(page, y, str(k))
            y = prose(page, y + 26, [AFTER])
    return doc


def test_a_pdf_with_61_candidates_places_the_60_answered_and_refuses_the_61st(tmp_path, on):
    # Sol r1 finding 2: the per-PDF cap stopped the read at the 61st reservation and placed nothing, for good.
    store, _, aid, papers = library(tmp_path, many_equations(61).tobytes())
    fake = FakeMathpix([{"latex_styled": f"x={k}", "confidence": 0.99} for k in range(1, 61)])
    svc = service(store, papers, tmp_path, fake)
    state = read(svc, aid)
    assert len(fake.text_requests()) == equations.MAX_ASSET_REQUESTS == 60
    assert state["state"] == "read" and state["mathpix"]["placed"] == 60 and state["mathpix"]["refused"] == {"budget_reached": 1}
    refused = json.loads(mathpix_extraction(store, aid)["math_json"])["refused"]
    assert refused == [{"page": refused[0]["page"], "n": refused[0]["n"], "reason": "budget_reached"}]


def test_a_pdf_at_its_budget_is_read_again_from_stored_answers_alone(tmp_path, on):
    # Sol r1 finding 2: the state gate blocked a read that needs no new request. Crop (1) was answered earlier; the month
    # is used up; the background reader leaves the PDF alone, and an asked-for read places (1) without sending anything.
    store, _, aid, papers = library(tmp_path)
    crop = next(c for c in equation_regions.detect(papers / "paper.pdf", set()) if c["n"] == "1")
    store.conn.execute("INSERT INTO mathpix_requests (id, crop_sha256, asset_id, file_sha256, page, n, attempt, status, http_status,"
                       " response_json, credential_revision, reserved_at, answered_at) VALUES ('mpx_old', ?, ?, 'f', 1, '1', 1,"
                       " 'answered', 200, ?, 'rev-1', ?, ?)", (crop["crop_sha256"], aid, json.dumps(ANSWERS["1"]), now(), now()))
    fake = FakeMathpix()
    svc = service(store, papers, tmp_path, fake)
    store.set_setting(equations.MATHPIX_BUDGET, 1)
    before = equations.equation_state(store, aid)
    assert before["state"] == "budget_reached" and before["stored_answers"] is True and svc.next_asset() is None
    state = read(svc, aid, retry=True)
    assert fake.requests == []
    assert state["state"] == "read" and state["mathpix"] == {"placed": 1, "pages": [1], "refused": {"budget_reached": 1}}
    math = json.loads(mathpix_extraction(store, aid)["math_json"])
    assert math["requests"] == 0 and math["reused"] == 1 and math["placed"][0]["request_row_id"] == "mpx_old"


def test_a_pdf_at_its_budget_without_stored_answers_is_not_read_again(tmp_path, on):
    store, _, aid, papers = library(tmp_path)
    fake = FakeMathpix()
    svc = service(store, papers, tmp_path, fake)
    store.set_setting(equations.MATHPIX_BUDGET, 0)
    assert read(svc, aid, retry=True) == {"state": "budget_reached", "month": 0, "budget": 0, "asset": 0, "stored_answers": False,
                                             "route": "mathpix"}
    assert fake.requests == [] and mathpix_extraction(store, aid) is None


def insert_row(store, aid, status, http_status=None, crop="c" * 64, at=None):
    store.conn.execute("INSERT INTO mathpix_requests (id, crop_sha256, asset_id, file_sha256, page, n, attempt, status, http_status,"
                       " credential_revision, reserved_at) VALUES (?, ?, ?, 'f', 1, '1', 1, ?, ?, 'rev-1', ?)",
                       (db.new_id("mpx"), crop, aid, status, http_status, at or now()))


def test_unknown_and_answered_rows_count_against_the_budgets_and_unsent_errors_do_not(tmp_path, on):
    store, _, aid, papers = library(tmp_path)
    fake = FakeMathpix()
    svc = service(store, papers, tmp_path, fake)
    store.set_setting(equations.MATHPIX_BUDGET, 2)
    insert_row(store, aid, "error")  # never reached Mathpix
    insert_row(store, aid, "error", 500)
    assert equations.mathpix_counts(store, aid) == {"month": 1, "budget": 2, "asset": 1}
    insert_row(store, aid, "unknown")
    assert equations.equation_state(store, aid)["state"] == "budget_reached"
    insert_row(store, "other", "answered", 200, at="2020-01-01T00:00:00.000+00:00")  # an earlier month
    assert equations.mathpix_counts(store)["month"] == 2
    assert read(svc, aid)["state"] == "budget_reached" and fake.requests == []


def test_one_pdf_sends_at_most_sixty_requests_over_all_its_attempts(tmp_path, on):
    store, _, aid, papers = library(tmp_path)
    fake = FakeMathpix()
    svc = service(store, papers, tmp_path, fake)
    for k in range(equations.MAX_ASSET_REQUESTS):
        insert_row(store, aid, "error", 500, crop=f"{k:064d}", at="2020-01-01T00:00:00.000+00:00")
    assert equations.equation_state(store, aid)["state"] == "budget_reached"
    assert read(svc, aid)["state"] == "budget_reached" and fake.requests == []


def test_a_timeout_leaves_the_row_unknown_and_counted(tmp_path, on):
    store, _, aid, papers = library(tmp_path)
    svc = service(store, papers, tmp_path, FakeMathpix([httpx.ReadTimeout("SYNTHETIC")]))
    state = read(svc, aid)
    assert state["state"] == "failed" and state["reason"] == "network"
    assert [r["status"] for r in rows(store)] == ["unknown"] and equations.mathpix_counts(store)["month"] == 1


def test_a_connection_refused_before_sending_is_an_error_not_counted(tmp_path, on):
    store, _, aid, papers = library(tmp_path)
    svc = service(store, papers, tmp_path, FakeMathpix([httpx.ConnectError("SYNTHETIC")]))
    assert read(svc, aid)["reason"] == "network"
    assert [(r["status"], r["http_status"]) for r in rows(store)] == [("error", None)] and equations.mathpix_counts(store)["month"] == 0


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_pair_is_keys_rejected_never_retried_and_cleared_by_saving_the_pair_again(tmp_path, on, monkeypatch, status):
    store, _, aid, papers = library(tmp_path)
    fake = FakeMathpix([status])
    svc = service(store, papers, tmp_path, fake)
    assert read(svc, aid)["state"] == "keys_rejected"
    assert svc.next_asset() is None and read(svc, aid)["state"] == "keys_rejected" and len(fake.text_requests()) == 1
    assert equations.mathpix_keys_rejected(store)
    monkeypatch.setenv(mathpix.ENV, json.dumps(json.loads(PAIR) | {"revision": "rev-2"}))
    assert equations.equation_state(store, aid)["state"] == "pending" and svc.next_asset() == aid


def test_a_response_over_one_megabyte_is_cut_and_refused(tmp_path, on):
    store, _, aid, papers = library(tmp_path)
    big = httpx.Response(200, content=b'{"latex_styled": "' + b"x" * (mathpix.MAX_RESPONSE_BYTES + 10) + b'"}')
    svc = service(store, papers, tmp_path, FakeMathpix([big]))
    state = read(svc, aid)
    assert state["state"] == "failed" and state["reason"] == "server_error"
    assert [(r["status"], r["http_status"], r["response_json"]) for r in rows(store)] == [("error", 200, None)]


class SlowStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'{"latex_styled": "x'
        await asyncio.sleep(5)
        yield b'"}'


def test_a_slow_drip_response_trips_the_outer_deadline(tmp_path, on, monkeypatch):
    monkeypatch.setattr(mathpix, "TIMEOUT_SECONDS", 0.3)
    store, _, aid, papers = library(tmp_path)
    svc = service(store, papers, tmp_path, FakeMathpix([httpx.Response(200, stream=SlowStream())]))
    state = read(svc, aid)
    assert state["reason"] == "network" and [r["status"] for r in rows(store)] == ["unknown"]


def test_a_shutdown_mid_request_leaves_the_row_unknown(tmp_path, on):
    store, _, aid, papers = library(tmp_path)
    started = asyncio.Event()

    async def hang(request):
        started.set()
        await asyncio.sleep(60)

    svc = service(store, papers, tmp_path, FakeMathpix([hang]))

    async def scenario():
        task = asyncio.create_task(svc.read_asset(aid))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(scenario())
    assert [r["status"] for r in rows(store)] == ["unknown"] and mathpix_extraction(store, aid) is None


# ---- the route table --------------------------------------------------------------------------------------------------------
def set_version(store, aid, version):
    store.conn.execute("UPDATE source_assets SET extraction_version = ? WHERE id = ?", (version, aid))


def test_row_2_an_earlier_marker_reading_is_kept_and_mathpix_never_reads_it(tmp_path, on):
    store, _, aid, papers = library(tmp_path)
    fake = FakeMathpix()
    svc = service(store, papers, tmp_path, fake)
    set_version(store, aid, equations.target_version(pdf.EXTRACTION_VERSION))
    state = equations.equation_state(store, aid)
    assert state["state"] == "read" and state["route"] == "marker"
    assert read(svc, aid)["state"] == "read" and fake.requests == [] and svc.next_asset() is None


def test_row_2b_a_mathpix_reading_is_kept_whatever_the_switch_and_the_arxiv_route_say(tmp_path, on):
    store, _, aid, papers = library(tmp_path)
    svc = service(store, papers, tmp_path, mode="auto")
    store.conn.execute("INSERT INTO asset_arxiv_versions (asset_id, eligibility, checked_at) VALUES (?, 'no_version', ?)", (aid, now()))
    assert read(svc, aid)["state"] == "read"
    store.set_setting(equations.MATHPIX_SWITCH, "off")
    assert equations.equation_state(store, aid)["route"] == "mathpix" and equations.equation_state(store, aid)["state"] == "read"


def test_row_3_an_arxiv_reading_stays_with_the_source_route(tmp_path, on):
    store, _, aid, papers = library(tmp_path)
    service(store, papers, tmp_path, mode="auto")
    set_version(store, aid, pdf.EXTRACTION_VERSION + "+arxiv-latex-v1")
    assert equations.equation_state(store, aid)["route"] == "arxiv_source"


def test_row_4_a_transient_arxiv_state_makes_mathpix_wait(tmp_path, on):
    store, _, aid, papers = library(tmp_path)
    fake = FakeMathpix()
    service(store, papers, tmp_path, fake, mode="auto")
    assert equations.equation_state(store, aid) == {"state": "pending", "route": "arxiv_source"}  # eligibility not decided yet
    for state in ({"state": "pending"}, {"state": "reading"}, {"state": "source_waiting"},
                  {"state": "failed", "reason": equations.EXTRACTION_FAILED, "attempts": 1},
                  {"state": "no_source", "reason": "cache_corrupt"}):
        assert not equations._source_settled(state)
    for state in ({"state": "no_source", "reason": "no_version"}, {"state": "no_source", "reason": "withdrawn"},
                  {"state": "no_source", "reason": "nothing_placed"}, {"state": "failed", "reason": "offsets_unresolved"},
                  {"state": "failed", "reason": equations.EXTRACTION_FAILED, "attempts": equations.MAX_ATTEMPTS}):
        assert equations._source_settled(state)
    assert fake.requests == []


def test_row_5_a_pdf_the_arxiv_route_settles_for_good_goes_to_mathpix(tmp_path, on):
    store, _, aid, papers = library(tmp_path)
    fake = FakeMathpix()
    svc = service(store, papers, tmp_path, fake, mode="auto")
    first = read(svc, aid)  # the source route decides: no arXiv version, nothing fetched
    assert first == {"state": "no_source", "reason": "no_version", "route": "arxiv_source"} or first["route"] == "mathpix"
    assert equations.equation_state(store, aid)["route"] == "mathpix"
    assert read(svc, aid)["state"] == "read" and len(fake.text_requests()) == 2


def test_row_6_with_the_arxiv_route_off_or_unavailable_mathpix_reads(tmp_path, on, monkeypatch):
    store, _, aid, papers = library(tmp_path)
    service(store, papers, tmp_path, mode="off")
    assert equations.equation_state(store, aid)["route"] == "mathpix"
    store2, _, aid2, papers2 = library(tmp_path / "b")
    service(store2, papers2, tmp_path / "b", mode="auto")
    monkeypatch.setattr(equations.arxiv_source, "posix_available", lambda: False)
    assert equations.equation_state(store2, aid2)["route"] == "mathpix"


def test_row_7_with_the_switch_off_and_no_answer_model_the_state_is_off(tmp_path, on):
    store, _, aid, papers = library(tmp_path)
    service(store, papers, tmp_path, switch="off")
    assert equations.equation_state(store, aid) == {"state": "off", "reason": "no_answer_model", "route": "model"}


# ---- the write guard ---------------------------------------------------------------------------------------------------------
def guard_case(case, store, svc, aid):
    def before(count):
        if count < 2:
            return
        if case == "asset_removed":
            store.conn.execute("UPDATE source_assets SET removed_at = ? WHERE id = ?", (now(), aid))
        elif case == "extraction_changed":
            store.conn.execute("UPDATE asset_extractions SET outcome = 'superseded' WHERE asset_id = ?", (aid,))
        elif case == "file_changed":
            store.conn.execute("UPDATE source_assets SET sha256 = 'sha-b' WHERE id = ?", (aid,))
        elif case == "switch_off":
            store.set_setting(equations.MATHPIX_SWITCH, "off")
        elif case == "arxiv_reading_landed":
            set_version(store, aid, pdf.EXTRACTION_VERSION + "+arxiv-latex-v1")
    return before


@pytest.mark.parametrize("case", ["asset_removed", "extraction_changed", "file_changed", "switch_off",
                                  "arxiv_reading_landed"])
def test_the_guard_writes_nothing_when_the_pdf_or_the_route_changed_during_the_read_and_keeps_the_answers(tmp_path, on, case):
    store, svid, aid, papers = library(tmp_path)
    fake = FakeMathpix()
    svc = service(store, papers, tmp_path, fake)
    fake.before = guard_case(case, store, svc, aid)
    count = "SELECT COUNT(*) FROM passages WHERE source_version_id = ?"
    passages = store.conn.execute(count, (svid,)).fetchone()[0]
    state = read(svc, aid)
    assert state.get("outcome") not in ("current", None), state
    assert mathpix_extraction(store, aid) is None and store.conn.execute(count, (svid,)).fetchone()[0] == passages
    assert [r["status"] for r in rows(store)] == ["answered", "answered"]

