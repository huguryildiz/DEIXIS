"""SYNTHETIC builders for the Mathpix route's tests (D40), and a scripted Mathpix.

The PDFs are drawn with PyMuPDF: prose in Helvetica, equations in Times Italic with sub- and superscripts set smaller and
off the baseline, a fraction bar drawn as a line, and the number `(n)` at the right margin. Mathpix is an
`httpx.MockTransport` that answers from a script. Passing tests built on them shows the route's rules and wiring, not how
well Mathpix reads real papers.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pymupdf

PROSE = [
    "SYNTHETIC. We study a simple model of signal detection in which the receiver counts the",
    "particles that arrive within each interval and compares that count with a threshold that is",
    "chosen in advance. The quantities below are defined once and then used throughout the text.",
]
AFTER = "where the symbols are those of the model defined in the section above, as stated before."
PAIR = json.dumps({"app_id": "synthetic-app", "app_key": "synthetic-key-0001", "revision": "rev-1"})


def width(text: str, font: str = "tiit", size: float = 10) -> float:
    return pymupdf.get_text_length(text, fontname=font, fontsize=size)


def prose(page: pymupdf.Page, y: float, lines: list[str] | None = None, x: float = 72, size: float = 10) -> float:
    for line in lines or PROSE:
        page.insert_text((x, y), line, fontsize=size, fontname="helv")
        y += 13
    return y


def scripted(page: pymupdf.Page, x: float, y: float, parts: list[tuple[str, str]], size: float = 10) -> float:
    """Text pieces at a level: base, raised (7 pt, 3.5 pt up) or lowered (7 pt, 2.5 pt down)."""
    for text, level in parts:
        small = level != "base"
        shift = -3.5 if level == "raised" else 2.5 if level == "lowered" else 0
        font_size = size * 0.7 if small else size
        page.insert_text((x, y + shift), text, fontsize=font_size, fontname="tiit")
        x += width(text, "tiit", font_size)
    return x


def number(page: pymupdf.Page, y: float, n: str, x: float = 520) -> None:
    page.insert_text((x, y), f"({n})", fontsize=10, fontname="helv")


def fraction(page: pymupdf.Page, x: float, y: float, top: str, bottom: str, bar: bool = True) -> float:
    """A display fraction centred on the baseline y: `top` over a drawn bar over `bottom`."""
    span = max(width(top), width(bottom)) + 2
    page.insert_text((x + 1, y - 6), top, fontsize=10, fontname="tiit")
    if bar:
        page.draw_line((x, y - 3.5), (x + span, y - 3.5), width=0.4)
    page.insert_text((x + 1, y + 7), bottom, fontsize=10, fontname="tiit")
    return x + span


def two_equations(doc: pymupdf.Document | None = None) -> pymupdf.Document:
    """One page: prose, (1) `x = a² + b_i`, prose, (2) `y = c / d` with a drawn bar, prose."""
    doc = doc or pymupdf.open()
    page = doc.new_page(width=612, height=792)
    y = prose(page, 90)
    y += 20
    scripted(page, 250, y, [("x = a", "base"), ("2", "raised"), (" + b", "base"), ("i", "lowered")])
    number(page, y, "1")
    y = prose(page, y + 28, [AFTER, AFTER])
    y += 22
    x = scripted(page, 250, y, [("y = ", "base")])
    fraction(page, x, y, "c", "d")
    number(page, y, "2")
    prose(page, y + 30, [AFTER, AFTER, AFTER])
    return doc


def pdf_bytes(doc: pymupdf.Document) -> bytes:
    return doc.tobytes()


ANSWERS = {
    "1": {"latex_styled": "x=a^{2}+b_{i}", "confidence": 0.99, "confidence_rate": 0.99, "request_id": "req-1"},
    "2": {"latex_styled": "y=\\frac{c}{d}", "confidence": 0.98, "confidence_rate": 0.98, "request_id": "req-2"},
}


class FakeMathpix:
    """Answers `/v3/text` in order from `script` (a dict, an int status, an exception, or a callable), else from ANSWERS by
    the order of the crops (1, 2, ...). `/v3/ocr-usage` answers `usage`."""

    def __init__(self, script: list | None = None, usage: int = 200, before=None):
        self.script, self.usage, self.before = list(script or []), usage, before
        self.requests: list[httpx.Request] = []

    async def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v3/ocr-usage":
            self.requests.append(request)
            return httpx.Response(self.usage, json={"ocr_usage": []})
        self.requests.append(request)
        if self.before:
            result = self.before(len(self.text_requests()))
            if asyncio.iscoroutine(result):
                await result
        item = self.script.pop(0) if self.script else ANSWERS[str(len(self.text_requests()))]
        if callable(item):
            item = item(request)
            if asyncio.iscoroutine(item):
                item = await item
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, httpx.Response):
            return item
        if isinstance(item, int):
            return httpx.Response(item, json={"error": "SYNTHETIC", "error_info": {"id": "synthetic"}})
        return httpx.Response(200, json=item)

    def text_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == "/v3/text"]

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
