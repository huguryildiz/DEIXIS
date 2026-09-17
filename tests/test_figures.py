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
