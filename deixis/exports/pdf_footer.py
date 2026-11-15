"""The footer of a report PDF the macOS app saved itself: WebKit draws no @page footer boxes, so the mark, the name and
the page number are stamped onto each page afterwards, where the print stylesheet's footer would be."""

from __future__ import annotations

from pathlib import Path

import pymupdf

# The sidebar wordmark as drawn in the app (mark, then DEIXIS in Source Serif 4 semibold, #2e4877), 6x size.
WORDMARK = Path(__file__).with_name("deixis-wordmark.png")
MM = 72 / 25.4  # points per millimetre


def stamp(path: Path) -> int:
    """Add the DEIXIS wordmark at the bottom left and the page number at the bottom right of every page; returns
    the page count. The positions follow print.css: 22 mm side margins, the footer line 12 mm above the bottom edge."""
    doc = pymupdf.open(path)
    wordmark = WORDMARK.read_bytes()
    tall = 10  # points: the wordmark's height on paper
    wide = tall * 507 / 110  # its width, from the image's 507 x 110 px
    for number, page in enumerate(doc, 1):
        width, height = page.rect.width, page.rect.height
        base = height - 12 * MM  # the footer's text baseline
        # The wordmark sits centred on the footer line at the left text edge.
        page.insert_image(pymupdf.Rect(22 * MM, base - 3 - tall / 2, 22 * MM + wide, base - 3 + tall / 2), stream=wordmark)
        # The page number in a serif face, right-aligned to the text block.
        label = str(number)
        page.insert_text((width - 22 * MM - pymupdf.get_text_length(label, "tiro", 8.5), base), label, fontname="tiro",
                         fontsize=8.5, color=(0.07, 0.07, 0.07))
    pages = doc.page_count
    # Written over the same file in place, compressed as before.
    doc.saveIncr()
    doc.close()
    return pages
