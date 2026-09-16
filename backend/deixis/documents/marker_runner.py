"""Marker page reader. Runs inside the separate Marker environment, never in DEIXIS's own (D52).

It imports nothing from DEIXIS. It loads Marker's models once, then reads one JSON request per line from stdin,
`{"id": ..., "path": ..., "pages": [0-based indices]}`, and writes one JSON reply per line to the original stdout,
`{"id": ..., "pages": {"<index>": "<markdown>"}, "equations": {"<index>": [{"bbox": [x0, y0, x1, y1], "latex": ...}]},
"seconds": ...}` or `{"id": ..., "error": "..."}`. Equation boxes let the LaTeX be checked against the text layer
inside the box. Everything Marker and its libraries print goes to stderr, so stdout carries only replies. The first line is
`{"ready": true, "marker_version": ...}`.
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


def main() -> None:
    replies = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())  # library output must not reach the reply stream
    from importlib.metadata import version

    from marker.config.parser import ConfigParser
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    from marker.schema import BlockTypes

    models = create_model_dict()
    replies.write(json.dumps({"ready": True, "marker_version": version("marker-pdf")}) + "\n")
    for line in sys.stdin:
        request = json.loads(line)
        started = time.monotonic()
        try:
            config = ConfigParser({"output_format": "markdown", "paginate_output": True, "disable_image_extraction": True,
                                   "page_range": ",".join(str(p) for p in request["pages"])})
            converter = PdfConverter(config=config.generate_config_dict(), artifact_dict=models,
                                     processor_list=config.get_processors(), renderer=config.get_renderer())
            document = converter.build_document(request["path"])
            markdown = converter.resolve_dependencies(converter.renderer)(document).markdown
            reply = {"id": request["id"], "pages": split_pages(markdown), "equations": equation_boxes(document, BlockTypes),
                     "seconds": round(time.monotonic() - started, 1)}
        except Exception as exc:  # noqa: BLE001 - one failed file must not stop the reader
            traceback.print_exc()
            reply = {"id": request["id"], "error": f"{type(exc).__name__}: {exc}"[:400]}
        replies.write(json.dumps(reply) + "\n")


if __name__ == "__main__":
    main()
