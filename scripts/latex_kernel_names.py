"""Writes backend/deixis/documents/latex_kernel_names.json: the control words that are defined inside the document
body of `\\documentclass{article}\\usepackage{amsmath,amssymb}` under pdfLaTeX (D104). An archive definition of any of
them is never trusted, since the paper may use the name where that definition is not in force.

Candidates are every control word in the kernel's source files (latex.ltx and the files it inputs), article.cls and the
AMS packages, plus LuaTeX's primitives; a candidate is kept when `\\ifdefined` is true for it after
`\\begin{document}`. Needs a TeX Live installation (kpsewhich, luatex, pdflatex).
Run from the repository root: PYTHONPATH=backend:. uv run --no-sync python scripts/latex_kernel_names.py
"""

import json
import re
import subprocess
import tempfile
from pathlib import Path

FILES = ["latex.ltx", "texsys.cfg", "fonttext.ltx", "fontmath.ltx", "preload.ltx", "utf8.def", "latex209.def",
         "article.cls", "size10.clo", "amsmath.sty", "amsopn.sty", "amstext.sty", "amsbsy.sty", "amssymb.sty",
         "amsfonts.sty"]
OUT = Path(__file__).resolve().parents[1] / "backend" / "deixis" / "documents" / "latex_kernel_names.json"


def main() -> None:
    names: set[str] = set()
    read = []
    for name in FILES:
        path = subprocess.run(["kpsewhich", name], capture_output=True, text=True).stdout.strip()
        if not path:
            continue
        read.append(name)
        text = re.sub(r"(?<!\\)%.*", "", Path(path).read_text(encoding="latin-1"))
        names.update(re.findall(r"\\([A-Za-z@]+)", text))
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "p.tex").write_text("\\catcode`\\{=1 \\catcode`\\}=2\n\\directlua{local f=io.open(\"prims.txt\",\"w\") "
                                         "for _,p in ipairs(tex.primitives()) do f:write(p, string.char(10)) end f:close()}\n\\end\n")
        subprocess.run(["luatex", "-ini", "-interaction=nonstopmode", "p.tex"], cwd=tmp, capture_output=True)
        primitives = [p for p in (Path(tmp) / "prims.txt").read_text().split() if re.fullmatch(r"[A-Za-z@]+", p)]
    candidates = sorted(names | set(primitives))
    with tempfile.TemporaryDirectory() as tmp:
        tests = "\n".join(f"\\deixis@t\\{name}" for name in candidates)
        (Path(tmp) / "d.tex").write_text(
            "\\documentclass{article}\\usepackage{amsmath,amssymb}\\makeatletter\\newwrite\\deixis@o\\begin{document}\n"
            "\\immediate\\openout\\deixis@o=defined.txt\n"
            "\\def\\deixis@t#1{\\ifdefined#1\\immediate\\write\\deixis@o{\\expandafter\\@gobble\\string#1}\\fi}\n"
            f"{tests}\n\\immediate\\write\\deixis@o{{:complete}}\\immediate\\closeout\\deixis@o\n\\end{{document}}\n")
        subprocess.run(["pdflatex", "-interaction=batchmode", "d.tex"], cwd=tmp, capture_output=True)
        lines = (Path(tmp) / "defined.txt").read_text().split()
        if lines[-1:] != [":complete"]:
            raise SystemExit("pdflatex stopped before the last candidate")
        names = set(lines[:-1])
    version = subprocess.run(["tex", "--version"], capture_output=True, text=True).stdout.splitlines()[0]
    OUT.write_text(json.dumps({"tex": version, "files": read, "candidates": len(candidates), "names": sorted(names)},
                              indent=0) + "\n", encoding="utf-8")
    print(OUT, len(names), "of", len(candidates), "candidates defined")


if __name__ == "__main__":
    main()
