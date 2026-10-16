"""Figure regions found from captions on synthetic PDF pages (D58)."""

import pymupdf
from fastapi.testclient import TestClient

from deixis.documents import figures
from test_api_flow import app_for, create, session


def figure_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(72, 60, 540, 120), "SYNTHETIC body paragraph above the figure, set at the body size of the page,\n"
                        "long enough to span two lines of the column.", fontsize=10)
    page.draw_rect(pymupdf.Rect(100, 150, 400, 300), color=(0, 0, 1), fill=(0.8, 0.8, 1))  # the plot
    page.insert_text((230, 318), "Time (s)", fontsize=7)  # an axis label just below the plot
    page.insert_text((72, 340), "Fig. 1. SYNTHETIC response over time.", fontsize=8)
    page.insert_textbox(pymupdf.Rect(72, 360, 540, 420), "SYNTHETIC body text that follows the caption and must stay out of\n"
                        "the figure, as Fig. 1 shows.", fontsize=10)
    page.insert_text((72, 470), "Figure 2 shows nothing: this sentence is not a caption.", fontsize=10)
    return doc.tobytes()


def test_a_figure_is_the_graphics_above_its_caption_with_their_small_type(tmp_path):
    path = tmp_path / "fig.pdf"
    path.write_bytes(figure_pdf())
    found = figures.find_figures(path)
    assert [(f["page"], f["label"]) for f in found] == [(1, "1")]
    x0, y0, x1, y1 = found[0]["bbox"]
    assert x0 <= 100 and x1 >= 400 and y0 <= 150 and 318 <= y1 < 330  # the plot and its axis label, not the caption
    assert figures.render_figure(path, 1, found[0]["bbox"]).startswith(b"\x89PNG")


def test_figures_are_listed_and_rendered_through_the_api(tmp_path):
    with TestClient(app_for(tmp_path)) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        uploaded = client.post(f"/api/researches/{rid}/uploads", files={"file": ("fig.pdf", figure_pdf(), "application/pdf")})
        aid = uploaded.json()["sources"][0]["access"]["assets"][0]["id"]
        listed = client.get(f"/api/researches/{rid}/assets/{aid}/figures").json()["figures"]
        assert [(f["page"], f["label"]) for f in listed] == [(1, "1")]
        image = client.get(f"/api/researches/{rid}/assets/{aid}/figures/1.png")
        assert image.status_code == 200 and image.headers["content-type"] == "image/png"
        assert client.get(f"/api/researches/{rid}/assets/{aid}/figures/2.png").status_code == 404


def algorithm_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    for y in (100, 114, 200):  # the rule above the caption, the one under it and the bottom rule
        page.draw_line((72, y), (300, y), width=0.5)
    page.insert_text((72, 110), "Algorithm 2 SYNTHETIC Greedy Assignment", fontsize=9)
    page.insert_text((72, 130), "1: for all SYNTHETIC items do", fontsize=9)
    page.insert_text((72, 190), "2: end for", fontsize=9)
    page.insert_text((72, 260), "Algorithm 2 first sorts the SYNTHETIC items; no rules surround this sentence.", fontsize=10)
    page.insert_text((72, 300), "Algorithm 3 SYNTHETIC caption with no ruled box", fontsize=9)
    return doc.tobytes()


def test_an_algorithm_box_runs_from_the_rule_above_its_caption_to_the_bottom_rule(tmp_path):
    path = tmp_path / "alg.pdf"
    path.write_bytes(algorithm_pdf())
    found = figures.find_algorithms(path)
    assert [(f["page"], f["label"]) for f in found] == [(1, "algorithm-2")]
    x0, y0, x1, y1 = found[0]["bbox"]
    assert x0 <= 72 and x1 >= 300 and 99 <= y0 <= 100 and 200 <= y1 <= 201
    assert figures.render_figure(path, 1, found[0]["bbox"]).startswith(b"\x89PNG")


def test_algorithm_boxes_are_listed_with_their_kind(tmp_path):
    with TestClient(app_for(tmp_path)) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        uploaded = client.post(f"/api/researches/{rid}/uploads", files={"file": ("alg.pdf", algorithm_pdf(), "application/pdf")})
        aid = uploaded.json()["sources"][0]["access"]["assets"][0]["id"]
        listed = client.get(f"/api/researches/{rid}/assets/{aid}/figures").json()["figures"]
        assert [(f["label"], f["kind"]) for f in listed] == [("algorithm-2", "algorithm")]
        assert client.get(f"/api/researches/{rid}/assets/{aid}/figures/algorithm-2.png").status_code == 200


def huge_figure_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=5000, height=5000)
    page.draw_rect(pymupdf.Rect(100, 100, 4900, 4700), color=(0, 0, 1), fill=(0.8, 0.8, 1))
    page.insert_text((100, 4740), "Figure 1. SYNTHETIC box drawn across a 5000 pt page.", fontsize=10)
    return doc.tobytes()


def test_a_figure_on_a_huge_page_is_rendered_within_the_pixel_budget(tmp_path):
    path = tmp_path / "huge.pdf"
    path.write_bytes(huge_figure_pdf())
    found = figures.find_figures(path)
    assert [f["label"] for f in found] == ["1"]
    picture = pymupdf.Pixmap(figures.render_figure(path, 1, found[0]["bbox"]))
    assert picture.width * picture.height <= 4_000_000  # at 160 dpi it would be about 120 million pixels


def test_a_figure_read_stopped_at_its_memory_limit_answers_like_an_unreadable_pdf(tmp_path, monkeypatch):
    from deixis.documents import pdf_child

    with TestClient(app_for(tmp_path)) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        uploaded = client.post(f"/api/researches/{rid}/uploads", files={"file": ("fig.pdf", figure_pdf(), "application/pdf")})
        aid = uploaded.json()["sources"][0]["access"]["assets"][0]["id"]
        assert [f["label"] for f in client.get(f"/api/researches/{rid}/assets/{aid}/figures").json()["figures"]] == ["1"]
        monkeypatch.setattr(pdf_child, "MAX_MEMORY_BYTES", 1024 * 1024)  # far below what a Python child starts with
        assert client.get(f"/api/researches/{rid}/assets/{aid}/figures/1.png").status_code == 404
        uploaded = client.post(f"/api/researches/{rid}/uploads", files={"file": ("alg.pdf", algorithm_pdf(), "application/pdf")})
        other = next(a["id"] for s in uploaded.json()["sources"] for a in s["access"]["assets"] if a["id"] != aid)
        assert client.get(f"/api/researches/{rid}/assets/{other}/figures").json()["figures"] == []
