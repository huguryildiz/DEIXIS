"""Every view field that names a page says whether the page is Europe PMC's text drawn by DEIXIS (SW21, D106).

The flag is read from the passage's own file, so an old answer citing a removed or replaced drawing still says it. A
SYNTHETIC file is turned into a rendition by writing the three facts `jats.RENDITION_SQL` reads; nothing is drawn or
fetched here. Passing shows the view models carry the flag; the interface's wording is checked in the browser.
"""

from __future__ import annotations

from deixis.storage import db
from deixis.workflow import person_reading, queue
from test_criterion_passage_flow import CRITERION_PAGE, TOPIC_PAGE, answer, app_for, client_of, research_with_pdf
from test_queue import Lib, store  # noqa: F401  (the fixture)

URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1000001/fullTextXML"


def make_rendition(conn, asset_id, origin="download"):
    with db.transaction(conn):
        conn.execute("UPDATE source_assets SET origin = ?, retrieved_from = ?, original_filename = ? WHERE id = ?",
                     (origin, URL, "PMC1000001.europepmc.pdf", asset_id))


def test_answer_evidence_passage_and_text_document_carry_the_flag_and_an_old_answer_keeps_it(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch, workflow="legacy")
    client = client_of(app)
    try:
        store_ = app.state.store
        rid = research_with_pdf(client, pages=(CRITERION_PAGE, TOPIC_PAGE))
        view, run, _ = answer(client, rid)
        assert run["status"] == "completed", run
        evidence = [e for claim in view["answers"][0]["claims"] for e in claim["evidence"] if e["kind"] == "pdf_page"]
        assert evidence and all(e["rendition"] is False for e in evidence)  # a PDF of its own
        passage_id = evidence[0]["passage_id"]
        asset_id = client.get(f"/api/researches/{rid}/passages/{passage_id}").json()["asset_id"]
        assert client.get(f"/api/researches/{rid}/passages/{passage_id}").json()["rendition"] is False
        assert client.get(f"/api/researches/{rid}/assets/{asset_id}/text").json()["asset"]["rendition"] is False

        make_rendition(store_.conn, asset_id)
        view = client.get(f"/api/researches/{rid}").json()
        evidence = [e for claim in view["answers"][0]["claims"] for e in claim["evidence"] if e["kind"] == "pdf_page"]
        assert all(e["rendition"] is True for e in evidence)
        assert client.get(f"/api/researches/{rid}/passages/{passage_id}").json()["rendition"] is True
        assert client.get(f"/api/researches/{rid}/assets/{asset_id}/text").json()["asset"]["rendition"] is True

        # The drawing is replaced later: the old answer still names the page it cited as rendered.
        with db.transaction(store_.conn):
            store_.conn.execute("UPDATE source_assets SET removed_at = ?, removal_reason = 'replaced' WHERE id = ?",
                                (db.now(), asset_id))
        view = client.get(f"/api/researches/{rid}").json()
        evidence = [e for claim in view["answers"][0]["claims"] for e in claim["evidence"] if e["kind"] == "pdf_page"]
        assert evidence and all(e["rendition"] is True for e in evidence)
        assert client.get(f"/api/researches/{rid}/passages/{passage_id}").json()["rendition"] is True
    finally:
        client.__exit__(None, None, None)


def test_a_person_s_upload_is_never_a_rendition_whatever_its_name(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch, workflow="legacy")
    client = client_of(app)
    try:
        rid = research_with_pdf(client)
        view, run, _ = answer(client, rid)
        passage_id = next(e["passage_id"] for c in view["answers"][0]["claims"] for e in c["evidence"]
                          if e["kind"] == "pdf_page")
        asset_id = client.get(f"/api/researches/{rid}/passages/{passage_id}").json()["asset_id"]
        make_rendition(app.state.store.conn, asset_id, origin="user_upload")
        assert client.get(f"/api/researches/{rid}/passages/{passage_id}").json()["rendition"] is False
    finally:
        client.__exit__(None, None, None)


def test_queue_detail_parts_closest_text_cues_and_waiting_quotes_carry_the_flag(store):  # noqa: F811
    lib = Lib(store)
    first, second = lib.parts
    svid = lib.work()
    near = "SYNTHETIC the release model is a Poisson proces with a fixed rate per slot."
    asset = lib.text(svid, [lib.field["page"], lib.field["cue"]])
    decision = lib.read(svid, "include_quote_unverified", quotes={first: (near, near), second: (lib.field["page"],) * 2},
                        verified={first: (False, False), second: (True, True)}, shown=((1, 2), (1, 2)))

    def flags():
        detail = queue.row_detail(store, lib.rid, svid)["detail"]
        parts = [part for run in detail["runs"] for part in run["parts"]]
        closest = [part["closest"] for part in parts if part.get("closest")]
        cues = detail["cues"]["sentences"]
        quotes = person_reading._verified_quotes(store, svid, decision["step_id"])
        return detail["rendition"], parts, closest, cues, quotes

    rendition, parts, closest, cues, quotes = flags()
    assert parts and closest and quotes
    assert rendition is False and not any(p["rendition"] for p in parts)
    assert not any(c["rendition"] for c in closest + cues) and not any(q["rendition"] for q in quotes)

    make_rendition(store.conn, asset)
    rendition, parts, closest, cues, quotes = flags()
    assert rendition is True and all(p["rendition"] for p in parts)
    assert all(c["rendition"] for c in closest + cues) and all(q["rendition"] for q in quotes)
