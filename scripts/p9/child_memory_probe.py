"""H0c: process evidence for the in-child memory watchdog of the OCR, JATS render and arXiv source children (F09).

Runs the real child argv of each module (`python -m deixis.documents.<ocr|jats|arxiv_source>`) with a chosen memory
limit and its in-child `_watch_memory` thread, on a scaled input, and samples the child's resident size from outside
(`ps`). Records elapsed time, exit code, peak sampled RSS, the kernel's peak for that child (`wait4` rusage) and the stop
reason. `stop_reason` is `memory_watchdog_exit_3` only when the child itself exited with code 3.

Inputs (all synthetic, generated here, nothing leaves the machine, no model call):
  ocr    a one-page PDF whose MediaBox is --size-pt square; the child renders it at 300 dpi for Tesseract
  jats   a JATS XML under the 5 MB input cap whose body is --size-mb of text in one table cell or nested elements
  arxiv  a .tar.gz source with one numbered equation plus the huge-content-stream PDF of memory_probe (--decoded-mib)

Output is one JSON line per run on stdout and, with --out, appended to that file. Run from the repo root with
`PYTHONPATH=backend`."""

from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import platform
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from memory_probe import MIB, build_pdf, rss_bytes  # noqa: E402

BACKEND = Path(__file__).resolve().parents[2] / "backend"


def build_big_page_pdf(path: Path, size_pt: int) -> None:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>" % (size_pt, size_pt),
        b"<< /Length 36 >>\nstream\nBT /F1 24 Tf 72 72 Td (x) Tj ET\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))


def build_jats(shape: str, size_mb: float) -> bytes:
    n = int(size_mb * MIB)
    if shape == "text":
        body = "<p>" + ("word " * (n // 5)) + "</p>"
    elif shape == "cell":  # one huge unbreakable table cell
        body = "<table-wrap><table><tbody><tr><td>" + ("A" * n) + "</td></tr></tbody></table></table-wrap>"
    elif shape == "hyph":  # every token becomes a nowrap span
        body = "<p>" + ("a-b " * (n // 4)) + "</p>"
    elif shape == "word":  # one unbreakable word
        body = "<p>" + ("A" * n) + "</p>"
    elif shape == "paras":  # very many tiny paragraphs
        body = "<p>x</p>" * (n // 8)
    elif shape == "nest":  # deep nesting of sections
        depth = n // 20
        body = "<sec><title>t</title>" * depth + "<p>x</p>" + "</sec>" * depth
    elif shape == "cells":  # many table cells
        count = n // 30
        body = "<table-wrap><table><tbody>" + "<tr><td>a</td><td>b</td><td>c</td></tr>" * (count // 3) + "</tbody></table></table-wrap>"
    else:
        raise SystemExit(f"unknown shape {shape}")
    return (f'<article><front><article-meta><title-group><article-title>T</article-title></title-group></article-meta></front>'
            f'<body><sec><title>S</title>{body}</sec></body></article>').encode()


def build_source(path: Path) -> bytes:
    tex = (b"\\documentclass{article}\\begin{document}\nHello.\n\\begin{equation}\nE = m c^2 + \\alpha\\beta\n\\end{equation}\n"
           b"\\end{document}\n")
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        info = tarfile.TarInfo("main.tex")
        info.size = len(tex)
        tar.addfile(info, io.BytesIO(tex))
    return gzip.compress(buffer.getvalue())


def run(argv: list[str], stdin: bytes, limit: int, timeout: float, env: dict) -> dict:
    started = time.monotonic()
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err, tempfile.TemporaryFile() as inp:
        inp.write(stdin)
        inp.seek(0)
        proc = subprocess.Popen(argv, stdin=inp, stdout=out, stderr=err, env=env)
        peak, timed_out = 0, False
        while True:
            pid, status, usage = os.wait4(proc.pid, os.WNOHANG)
            if pid:
                break
            peak = max(peak, rss_bytes(proc.pid))
            if time.monotonic() - started > timeout:
                proc.kill()
                timed_out = True
                _, status, usage = os.wait4(proc.pid, 0)
                break
            time.sleep(0.02)
        elapsed = time.monotonic() - started
        err.seek(0), out.seek(0)
        stderr = err.read().decode(errors="replace").strip()[-300:]
        stdout_head = out.read(200).decode(errors="replace")
    code = os.waitstatus_to_exitcode(status)
    scale = 1 if sys.platform == "darwin" else 1024
    reason = ("timeout_killed_by_probe" if timed_out else "memory_watchdog_exit_3" if code == 3
              else "completed_without_stop" if code == 0 else f"exit_{code}")
    return {"elapsed_s": round(elapsed, 2), "exit_code": code, "stop_reason": reason, "limit_mib": round(limit / MIB),
            "peak_rss_sampled_mib": round(peak / MIB), "peak_rss_rusage_mib": round(usage.ru_maxrss * scale / MIB),
            "stderr_tail": stderr, "stdout_head": stdout_head}


def run_parent_watched(argv: list[str], stdin: bytes, limit: int, timeout: float, env: dict) -> dict:
    """arxiv after D158: the real `run_child` with the parent watcher. One process per run, so the kernel's
    RUSAGE_CHILDREN peak belongs to this run; `timeout` replaces the 60 s production clock so load cannot end the run."""
    import asyncio
    import resource

    from deixis.documents import arxiv_source

    started = time.monotonic()
    result = asyncio.run(arxiv_source.run_child(argv, stdin, timeout=timeout, env=env, max_memory=limit))
    scale = 1 if sys.platform == "darwin" else 1024
    return {"elapsed_s": round(time.monotonic() - started, 2), "failure": result.failure, "exit_code": result.returncode,
            "stop_reason": {"memory_limit": "parent_watcher_memory_limit"}.get(result.failure, result.failure or "completed_without_stop"),
            "limit_mib": round(limit / MIB), "peak_rss_rusage_mib": round(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * scale / MIB)}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--child", choices=("ocr", "jats", "arxiv"), required=True)
    p.add_argument("--limit-mib", type=int, default=1024)
    p.add_argument("--size-pt", type=int, default=7200, help="ocr: square page edge in points")
    p.add_argument("--shape", default="cell", help="jats: text, cell, nest, cells, hyph, word, paras")
    p.add_argument("--size-mb", type=float, default=4.9, help="jats: payload size in MiB")
    p.add_argument("--decoded-mib", type=int, default=200, help="arxiv: decoded content-stream size of the PDF")
    p.add_argument("--parent-watch", action="store_true", help="arxiv: run through run_child with the parent watcher (D158)")
    p.add_argument("--timeout", type=float, default=120.0)
    p.add_argument("--out", default=None)
    p.add_argument("--label", default="")
    a = p.parse_args()
    limit = a.limit_mib * MIB
    env = {"PYTHONPATH": str(BACKEND)} | {k: os.environ[k] for k in ("PATH", "TESSDATA_PREFIX") if k in os.environ}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        stdin, detail = b"", {}
        if a.child == "ocr":
            pdf_path = tmp / "page.pdf"
            build_big_page_pdf(pdf_path, a.size_pt)
            px = a.size_pt / 72 * 300
            detail = {"size_pt": a.size_pt, "pixels": round(px) ** 2, "rgb_mib_if_dense": round(px * px * 3 / MIB)}
            argv = [sys.executable, "-m", "deixis.documents.ocr", str(pdf_path), "1", "eng", str(limit)]
        elif a.child == "jats":
            src = tmp / "in.xml"
            data = build_jats(a.shape, a.size_mb)
            src.write_bytes(data)
            detail = {"shape": a.shape, "xml_bytes": len(data)}
            argv = [sys.executable, "-m", "deixis.documents.jats", str(src), str(tmp / "out.pdf"), str(limit), "200", str(30 * MIB)]
        else:
            pdf_path = tmp / "probe.pdf"
            build_pdf(pdf_path, a.decoded_mib * MIB)
            stdin = build_source(tmp)
            detail = {"decoded_mib": a.decoded_mib, "pdf_bytes": pdf_path.stat().st_size, "source_bytes": len(stdin)}
            argv = [sys.executable, "-m", "deixis.documents.arxiv_source", str(pdf_path), "[]", "placements", str(limit)]
        record = {"label": a.label, "child": a.child, "machine": platform.machine(), "platform": platform.platform(),
                  "load_avg": [round(x, 2) for x in os.getloadavg()], "at": time.strftime("%Y-%m-%dT%H:%M:%S")} | detail
        record |= (run_parent_watched if a.parent_watch and a.child == "arxiv" else run)(argv, stdin, limit, a.timeout, env)
    line = json.dumps(record)
    print(line, flush=True)
    if a.out:
        with open(a.out, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


if __name__ == "__main__":
    main()
