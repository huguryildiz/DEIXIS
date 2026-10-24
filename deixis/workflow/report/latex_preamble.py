"""Fixed XeLaTeX export preamble; compatibility data is tied to its bytes."""

import hashlib

PREAMBLE: str = (
    "\\documentclass[journal]{IEEEtran}\n"
    "\\usepackage{fontspec}\n"
    "\\usepackage{amsmath}\n"
    "\\usepackage{amssymb}\n"
    "\\usepackage{bm}\n"
    "\\usepackage{xcolor}\n"
    "\\usepackage{cite}\n"
    "\\usepackage{url}\n"
    "\\usepackage{booktabs}\n"
    "\\usepackage{longtable}\n"
    "\\usepackage{array}\n"
)
PREAMBLE_SHA256: str = hashlib.sha256(PREAMBLE.encode("utf-8")).hexdigest()
