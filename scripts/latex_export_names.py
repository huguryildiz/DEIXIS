"""Generate export compatibility evidence with XeLaTeX; never used at runtime.

Run at the repository root:
PATH=/Library/TeX/texbin:$PATH PYTHONPATH=backend:. uv run --no-sync python scripts/latex_export_names.py
"""

import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

from deixis.documents.arxiv_source import katex_known
from deixis.workflow.report.latex_preamble import PREAMBLE, PREAMBLE_SHA256

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "backend/deixis/workflow/report/latex_names.json"
VOCABULARY = ROOT / "backend/deixis/documents/katex_commands.json"
PREAMBLE_FILES = {"IEEEtran.cls", "fontspec.sty", "amsmath.sty", "amssymb.sty", "bm.sty",
                  "xcolor.sty", "cite.sty", "url.sty", "booktabs.sty", "longtable.sty", "array.sty"}


def main() -> None:
    known = katex_known()
    engine = subprocess.run(["xelatex", "--version"], check=True, capture_output=True,
                            text=True).stdout.splitlines()[0]
    tests = [f"\\ifdefined\\{name}\\else\\immediate\\write\\deixis@o{{C:{name}}}\\fi"
             for name in sorted(known["commands"])]
    for name in sorted(known["environments"]):
        undefined = r"\immediate\write\deixis@o{E:" + name + "}"
        tests.append(r"\@ifundefined{" + name + "}{" + undefined + "}{"
                     + r"\@ifundefined{end" + name + "}{" + undefined + "}{}" + "}")
    document = (PREAMBLE + "\\listfiles\n\\makeatletter\n\\newwrite\\deixis@o\n\\begin{document}\n"
                "\\immediate\\openout\\deixis@o=names.txt\n" + "\n".join(tests)
                + "\n\\immediate\\write\\deixis@o{:complete}\n"
                "\\immediate\\closeout\\deixis@o\n\\end{document}\n")
    with tempfile.TemporaryDirectory(prefix="deixis-export-names-") as tmp:
        directory = Path(tmp)
        (directory / "probe.tex").write_text(document, encoding="utf-8")
        subprocess.run(["xelatex", "-interaction=nonstopmode", "-no-shell-escape", "probe.tex"],
                       cwd=tmp, check=True, capture_output=True, text=True)
        result = directory / "names.txt"
        lines = result.read_text(encoding="utf-8").splitlines() if result.exists() else []
        if lines[-1:] != [":complete"]:
            raise SystemExit("XeLaTeX stopped before :complete; latex_names.json was not written")
        log = (directory / "probe.log").read_text(encoding="utf-8", errors="replace")
        file_list = re.search(r"\*File List\*(.*?)\*{3,}", log, re.DOTALL)
        if file_list is None:
            raise SystemExit("No *File List* in XeLaTeX log; latex_names.json was not written")
        files = [line.strip() for line in file_list.group(1).splitlines()
                 if line.strip() and line.split()[0] in PREAMBLE_FILES]
        if {line.split()[0] for line in files} != PREAMBLE_FILES:
            raise SystemExit("Incomplete preamble package list; latex_names.json was not written")
    data = {
        "preamble_sha256": PREAMBLE_SHA256,
        "katex_commands_sha256": hashlib.sha256(VOCABULARY.read_bytes()).hexdigest(),
        "katex_version": next(iter(known["version"])),
        "engine": engine,
        "files": sorted(files),
        "undefined_commands": sorted({line[2:] for line in lines[:-1] if line.startswith("C:")}),
        "undefined_environments": sorted({line[2:] for line in lines[:-1] if line.startswith("E:")}),
    }
    OUT.write_text(json.dumps(data, sort_keys=True, indent=0) + "\n", encoding="utf-8")
    print(engine)
    print(f"{OUT}: {len(data['undefined_commands'])} undefined commands, "
          f"{len(data['undefined_environments'])} undefined environments")


if __name__ == "__main__":
    main()
