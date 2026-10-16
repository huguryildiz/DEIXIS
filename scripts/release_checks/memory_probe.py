"""H0b: process evidence for the PDF extraction memory watchdog (F09).

Builds a small PDF whose Flate content stream decodes to a chosen size, runs the real extraction child
(`python -m deixis.documents.pdf`) with a chosen memory limit, samples the child's resident size from outside, and
records elapsed time, exit code, peak sampled RSS, the child's own peak (`wait4` rusage) and the stop reason.
`--mode extract` runs `extract_pdf` instead and records its status and error text.

Output is one JSON line per run on stdout and, with `--out`, appended to that file. Nothing here reads the
owner's library, calls a model or touches the network. Run from the repo root with `PYTHONPATH=backend`."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

MIB = 1024 * 1024


def build_pdf(path: Path, decoded_bytes: int) -> None:
    """A one-page PDF with one Flate content stream: a single text string of `decoded_bytes` letters. Streams the
    compression so the builder itself never holds the decoded data."""
    head, tail = b"BT /F1 11 Tf 72 720 Td (", b") Tj ET"
    compressor, parts = zlib.compressobj(9), []
    parts.append(compressor.compress(head))
    block, left = b"A" * MIB, decoded_bytes
    while left > 0:
        step = min(left, MIB)
        parts.append(compressor.compress(block[:step]))
        left -= step
    parts.append(compressor.compress(tail))
    parts.append(compressor.flush())
    stream = b"".join(parts)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(stream) + stream + b"\nendstream",
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


def rss_bytes(pid: int) -> int:
    try:
        text = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        return int(text) * 1024 if text else 0
    except (ValueError, OSError):
        return 0


def run_child(path: Path, limit: int, max_chars: int = 3_000_000, timeout: float = 90.0) -> dict:
    """The production argv of `extract_pdf`, watched from outside."""
    backend = Path(__file__).resolve().parents[2] / "backend"
    argv = [sys.executable, "-m", "deixis.documents.pdf", str(path), str(max_chars), str(limit)]
    started = time.monotonic()
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(argv, stdout=out, stderr=err, env={"PYTHONPATH": str(backend)})
        peak_sampled, status, timed_out = 0, None, False
        try:
            while True:
                pid, status, usage = os.wait4(proc.pid, os.WNOHANG)
                if pid:
                    break
                peak_sampled = max(peak_sampled, rss_bytes(proc.pid))
                if time.monotonic() - started > timeout:
                    proc.kill()
                    timed_out = True
                    _, status, usage = os.wait4(proc.pid, 0)
                    break
                time.sleep(0.02)
        except BaseException:
            proc.kill()
            proc.wait()
            raise
        elapsed = time.monotonic() - started
        err.seek(0)
        stderr = err.read().decode(errors="replace").strip()[-200:]
    code = os.waitstatus_to_exitcode(status)
    scale = 1 if sys.platform == "darwin" else 1024
    if timed_out:
        reason = "timeout_killed_by_probe"
    elif code == 3:
        reason = "memory_watchdog_exit_3"
    elif code == 0:
        reason = "completed_without_stop"
    else:
        reason = f"exit_{code}"
    return {"elapsed_s": round(elapsed, 2), "exit_code": code, "stop_reason": reason, "peak_rss_sampled_mib": round(peak_sampled / MIB),
            "peak_rss_rusage_mib": round(usage.ru_maxrss * scale / MIB), "limit_mib": round(limit / MIB), "stderr_tail": stderr}


def _extraction_children(parent: int) -> list[tuple[int, int]]:
    """(pid, resident KiB) of this process's children that run the extraction module, not the sampler's own `ps`."""
    rows = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,rss=,command="], capture_output=True, text=True).stdout.split("\n")
    found = []
    for row in rows:
        parts = row.split(None, 3)
        if len(parts) == 4 and parts[1] == str(parent) and "deixis.documents.pdf" in parts[3]:
            found.append((int(parts[0]), int(parts[2])))
    return found


def run_extract(path: Path, limit: int) -> dict:
    """`extract_pdf` itself. The extraction child's resident size is sampled from this process by pid (KiB, via `ps`),
    and the kernel-recorded peak is read afterwards from `RUSAGE_CHILDREN`. That field is the largest child peak over this
    process's whole life, so it belongs to this run only with `--repeat 1` (one process per run); the sampled peak is a
    lower bound of the true peak."""
    import resource
    import threading

    from deixis.documents import pdf

    stop, seen = threading.Event(), {"peak_kib": 0, "pid": None, "at_limit": None}
    started = time.monotonic()

    def sample() -> None:
        while not stop.is_set():
            for pid, kib in _extraction_children(os.getpid()):
                seen["pid"] = pid
                seen["peak_kib"] = max(seen["peak_kib"], kib)
                if kib * 1024 >= limit and seen["at_limit"] is None:
                    seen["at_limit"] = round(time.monotonic() - started, 2)
            time.sleep(0.02)

    thread = threading.Thread(target=sample, daemon=True)
    thread.start()
    try:
        result = pdf.extract_pdf(path, max_memory=limit)
        elapsed = time.monotonic() - started
    finally:
        stop.set()
        thread.join()
    scale = 1 if sys.platform == "darwin" else 1024
    return {"elapsed_s": round(elapsed, 2), "status": result.status, "error": result.error, "limit_mib": round(limit / MIB),
            "child_pid": seen["pid"], "peak_rss_sampled_kib": seen["peak_kib"], "first_sample_at_limit_s": seen["at_limit"],
            "peak_rss_children_rusage_lifetime_max_bytes": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * scale}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decoded-mib", type=int, required=True, help="decoded size of the content stream in MiB")
    parser.add_argument("--limit-mib", type=int, default=1024, help="memory limit handed to the child (production: 1024)")
    parser.add_argument("--mode", choices=("child", "extract"), default="child")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--workdir", default=None, help="where to put the generated PDF (default: a temp dir, removed after)")
    parser.add_argument("--out", default=None, help="append JSON lines here")
    parser.add_argument("--label", default="")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(dir=args.workdir) as tmp:
        path = Path(tmp) / "probe.pdf"
        build_pdf(path, args.decoded_mib * MIB)
        for index in range(args.repeat):
            record = {"label": args.label, "mode": args.mode, "run": index + 1, "decoded_mib": args.decoded_mib, "pdf_bytes": path.stat().st_size,
                      "machine": platform.machine(), "platform": platform.platform(), "load_avg": [round(x, 2) for x in os.getloadavg()],
                      "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            record |= run_child(path, args.limit_mib * MIB) if args.mode == "child" else run_extract(path, args.limit_mib * MIB)
            line = json.dumps(record)
            print(line, flush=True)
            if args.out:
                with open(args.out, "a", encoding="utf-8") as handle:
                    handle.write(line + "\n")


if __name__ == "__main__":
    main()
