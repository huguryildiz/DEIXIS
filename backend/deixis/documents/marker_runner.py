"""Marker page reader. Runs inside the separate Marker environment, never in DEIXIS's own (D52).

It imports nothing from DEIXIS except `inline_math`, which imports nothing. It loads Marker's models once, then reads one
JSON request per line from stdin, `{"id": ..., "path": ..., "pages": [0-based indices], "image_pages": [...],
"math_boxes": {"<index>": [[x0, y0, x1, y1], ...]}}`, and writes one JSON reply per line to the original stdout,
`{"id": ..., "pages": {"<index>": "<markdown>"}, "equations": {"<index>": [{"bbox": [x0, y0, x1, y1], "latex": ...}]},
"seconds": ...}` or `{"id": ..., "error": "..."}`. Equation boxes let the LaTeX be checked against the text layer
inside the box. Everything Marker and its libraries print goes to stderr, so stdout carries only replies. The first line is
`{"ready": true, "marker_version": ...}`.

Pages with a text layer keep it: Marker's OCR of whole lines is switched off, and only lines that carry math (a math font,
a sub- or superscript, a math symbol, or a character inside `math_boxes`, the math-font characters DEIXIS found with
PyMuPDF) are read again from the page image and checked by `inline_math` (D52). On 11 pages of 4 papers this took 448 s
against 852 s for Marker's default and got 69% of 138 hand-transcribed inline expressions right against 72%. `image_pages`,
pages without a text layer, are read with Marker's default settings.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback

PAGE_SEPARATOR = re.compile(r"\n*\{(\d+)\}-{48}\n*")


def split_pages(markdown: str) -> dict[str, str]:
    """Marker's paginated output: `{index}` followed by 48 dashes before each page's text."""
    parts = PAGE_SEPARATOR.split(markdown)
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}


def equation_boxes(document, block_types) -> dict[str, list[dict]]:
    """Each page's display equations with their LaTeX and box (Marker's page coordinates, PDF points)."""
    found: dict[str, list[dict]] = {}
    for page in document.pages:
        for block in page.contained_blocks(document, (block_types.Equation,)):
            match = re.search(r"<math[^>]*>([\s\S]*?)</math>", block.html or "")
            if match:
                found.setdefault(str(page.page_id), []).append({"bbox": list(block.polygon.bbox), "latex": match.group(1),
                                                                "page_bbox": list(page.polygon.bbox)})
    return found


def inline_math_builder(models):
    """Marker's OCR builder replaced by one that reads only the lines carrying math, in math mode, and keeps a segment
    only when it matches the text layer."""
    import inline_math  # next to this file, which is on sys.path when it runs as a script
    from marker.builders.ocr import OcrBuilder
    from marker.schema import BlockTypes
    from marker.schema.polygon import PolygonBox

    text_blocks = (BlockTypes.Text, BlockTypes.TextInlineMath, BlockTypes.ListItem, BlockTypes.Caption, BlockTypes.Footnote)

    class InlineMathBuilder(OcrBuilder):
        math_boxes: dict[str, list[list[float]]] = {}

        def __call__(self, document, provider):
            for page in document.pages:
                lowres, highres = page.get_image(highres=False), page.get_image(highres=True)
                page_size = provider.get_page_bbox(page.page_id).size
                boxes = [PolygonBox(polygon=b.polygon).rescale(lowres.size, page_size).bbox
                         for b in models["detection_model"]([lowres])[0].bboxes]
                # Each detected visual line collects the text-layer lines whose middle is closest to it.
                owners: dict[int, list] = {}
                for block in page.structure_blocks(document):
                    if block.block_type not in text_blocks:
                        continue
                    for line in block.contained_blocks(document, [BlockTypes.Line]):
                        lb = line.polygon.bbox
                        middle = (lb[1] + lb[3]) / 2
                        near = [(abs(middle - (bb[1] + bb[3]) / 2), i) for i, bb in enumerate(boxes)
                                if min(lb[2], bb[2]) > max(lb[0], bb[0]) and min(lb[3], bb[3]) - max(lb[1], bb[1]) > -1]
                        if near:
                            owners.setdefault(min(near)[1], []).append((block, line))
                marks = self.math_boxes.get(str(page.page_id), [])
                units = []
                for i, members in owners.items():
                    spans = [s for _, line in members for s in line.contained_blocks(document, [BlockTypes.Span])]
                    ub = boxes[i]
                    marked = any(ub[0] <= (c[0] + c[2]) / 2 <= ub[2] and ub[1] <= (c[1] + c[3]) / 2 <= ub[3] for c in marks)
                    if not (marked or any(inline_math.is_mathy(s.text, s.font, s.has_superscript or s.has_subscript) for s in spans)):
                        continue
                    box = [min(ub[0], *(l.polygon.bbox[0] for _, l in members)), min(ub[1], *(l.polygon.bbox[1] for _, l in members)),
                           max(ub[2], *(l.polygon.bbox[2] for _, l in members)), max(ub[3], *(l.polygon.bbox[3] for _, l in members))]
                    polygon = PolygonBox.from_bbox(box).rescale(page_size, highres.size).fit_to_bounds((0, 0, *highres.size)).polygon
                    units.append((members, spans, [[int(x) for x in point] for point in polygon]))
                if not units:
                    continue
                # max_tokens stops a runaway reading (thousands of characters and minutes for one line were seen).
                results = self.recognition_model(images=[highres], task_names=[self.ocr_task_name], polygons=[[u[2] for u in units]],
                                                 input_text=[[""] * len(units)], recognition_batch_size=int(self.get_recognition_batch_size()),
                                                 sort_lines=False, math_mode=True, drop_repeated_text=False, max_sliding_window=2148,
                                                 max_tokens=256)
                for (members, spans, _), reading in zip(units, results[0].text_lines):
                    self.apply(document, page, members, spans, reading.text)

        def apply(self, document, page, members, spans, reading):
            # The line's spans left to right; stacked scripts (same x) either way round.
            orderings = [[(s.text, s.font) for s in sorted(spans, key=lambda s: (round(s.polygon.bbox[0]), sign * s.polygon.bbox[1]))]
                         for sign in (1, -1)]
            found = inline_math.rewrite(reading, orderings)
            if found is None or not found[1]:
                return
            first_line = members[0][1]
            template = first_line.contained_blocks(document, [BlockTypes.Span])[0]
            plain = {"has_superscript": False, "has_subscript": False, "html": None, "url": None}
            pieces = found[0][:-1] + [("text", found[0][-1][1] + "\n")]
            new_spans = [template.model_copy(update={**plain, "text": value, "formats": ["math" if kind == "math" else "plain"]})
                         for kind, value in pieces if value]
            self.replace_line_spans(document, page, first_line, new_spans)
            for block, line in members[1:]:
                line.removed = True
                if block.structure and line.id in block.structure:
                    block.structure.remove(line.id)

    return InlineMathBuilder


def main() -> None:
    replies = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())  # library output must not reach the reply stream
    from importlib.metadata import version

    from marker.config.parser import ConfigParser
    from marker.converters import pdf as pdf_converter
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    from marker.schema import BlockTypes

    models = create_model_dict()
    default_ocr, inline_ocr = pdf_converter.OcrBuilder, inline_math_builder(models)

    def convert(path: str, pages: list[int], with_text_layer: bool) -> tuple[dict, dict]:
        options = {"output_format": "markdown", "paginate_output": True, "disable_image_extraction": True,
                   "page_range": ",".join(str(p) for p in pages)}
        if with_text_layer:  # class-scoped, so DocumentBuilder still runs the (replaced) OCR builder
            options |= {"LineBuilder_disable_ocr": True, "TableProcessor_disable_ocr": True}
        pdf_converter.OcrBuilder = inline_ocr if with_text_layer else default_ocr
        config = ConfigParser(options)
        converter = PdfConverter(config=config.generate_config_dict(), artifact_dict=models,
                                 processor_list=config.get_processors(), renderer=config.get_renderer())
        document = converter.build_document(path)
        markdown = converter.resolve_dependencies(converter.renderer)(document).markdown
        return split_pages(markdown), equation_boxes(document, BlockTypes)

    replies.write(json.dumps({"ready": True, "marker_version": version("marker-pdf")}) + "\n")
    for line in sys.stdin:
        request = json.loads(line)
        started = time.monotonic()
        try:
            inline_ocr.math_boxes = request.get("math_boxes", {})
            image_pages = set(request.get("image_pages", []))
            pages, equations = {}, {}
            for selected, with_text_layer in (([p for p in request["pages"] if p not in image_pages], True),
                                              ([p for p in request["pages"] if p in image_pages], False)):
                if selected:
                    read, found = convert(request["path"], selected, with_text_layer)
                    pages |= read
                    equations |= found
            reply = {"id": request["id"], "pages": pages, "equations": equations, "seconds": round(time.monotonic() - started, 1)}
        except Exception as exc:  # noqa: BLE001 - one failed file must not stop the reader
            traceback.print_exc()
            reply = {"id": request["id"], "error": f"{type(exc).__name__}: {exc}"[:400]}
        replies.write(json.dumps(reply) + "\n")


if __name__ == "__main__":
    main()
