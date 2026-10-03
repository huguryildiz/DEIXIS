"""P9 H2 parent helper: starts one production class that owns a child process, prints one JSON line, then waits.

Not a test module. The test SIGKILLs this process and watches the child. Subcommands:
  codex <mode>        `models.codex_rpc.CodexAppServer` on `p9_stand_in_codex.py <mode>`; prints {"child_pid": ...}
  embedding <busy>    `documents.local_embedding.LocalEmbedder` on the fake runner (FAKE_RUNNER from the environment);
                      with `busy` one embed request is in flight; prints {"child_pid": ...}
  pdf <path>          `documents.pdf._run_watched` on the production extraction argv, 60 s parent clock; prints {"ready": true}
DEIXIS_DATA_DIR (embedding) is a temp directory made by the test.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "tests"), str(REPO / "backend")]


def say(**fields) -> None:
    print(json.dumps(fields), flush=True)


async def codex(mode: str) -> None:
    from deixis.models.codex_rpc import CodexAppServer

    stand_in = Path(__file__).with_name("p9_stand_in_codex.py")
    server = CodexAppServer(argv=[sys.executable, str(stand_in), mode], cwd=os.getcwd())
    await server.start()
    await server.initialize("p9-test", "0")
    say(child_pid=server.proc.pid)
    await asyncio.sleep(3600)


class Shim:
    @staticmethod
    def setattr(obj, name, value):
        setattr(obj, name, value)


async def embedding(busy: bool) -> None:
    import builtin_helpers
    from deixis.documents import local_embedding

    builtin_helpers.fake_manifest(Shim)  # otherwise the runner answers files_do_not_match
    paths = local_embedding.builtin_paths(Path(os.environ["DEIXIS_DATA_DIR"]))
    builtin_helpers.install_fake(paths)
    embedder = builtin_helpers.fake_embedder(paths)
    await embedder.start()
    task = asyncio.create_task(embedder.embed(["alpha beta"], "document")) if busy else None
    await asyncio.sleep(0.3)
    say(child_pid=embedder.process.pid)
    await asyncio.sleep(3600)
    del task


def extraction(path: str) -> None:
    from deixis.documents import pdf

    argv = [sys.executable, "-m", "deixis.documents.pdf", path, str(pdf.MAX_TEXT_CHARS), str(pdf.MAX_MEMORY_BYTES)]
    env = {"PYTHONPATH": str(Path(pdf.__file__).resolve().parents[2])}
    if os.environ.get("DEIXIS_CHILD_LIFETIME_SECONDS"):
        env["DEIXIS_CHILD_LIFETIME_SECONDS"] = os.environ["DEIXIS_CHILD_LIFETIME_SECONDS"]
    say(ready=True)
    pdf._run_watched(argv, env, 60, pdf.MAX_MEMORY_BYTES)


def gated_extraction(path: str, ready: str, gate: str) -> None:
    """One extraction child directly owned by _run_watched; no intermediary process.
    The gate holds work after _watch_memory readiness so the observer can register
    NOTE_EXIT before killing the actual watcher parent. All extraction is production code."""
    from deixis.documents import pdf
    limit = int(os.environ.get("DEIXIS_TEST_MEMORY_LIMIT", pdf.MAX_MEMORY_BYTES))
    code = ("from deixis.documents import pdf; from pathlib import Path; import os,json,time\n"
            f"pdf._watch_memory({limit})\n"
            f"Path({ready!r}).write_text(json.dumps({{'pid':os.getpid(),'parent':os.getppid(),'time':time.monotonic()}}))\n"
            f"while not Path({gate!r}).exists(): time.sleep(.01)\n"
            f"pdf._extract_in_process({path!r},pdf.MAX_TEXT_CHARS)\n")
    env = {"PYTHONPATH": str(Path(pdf.__file__).resolve().parents[2])}
    for key in ("DEIXIS_CHILD_LIFETIME_SECONDS", "DEIXIS_CHILD_GUARD_DISABLED", "DEIXIS_CHILD_GUARD_LOG"):
        if key in os.environ:
            env[key] = os.environ[key]
    done = pdf._run_watched([sys.executable, "-c", code], env, 90, limit)
    say(returncode=done.returncode)


if __name__ == "__main__":
    command = sys.argv[1]
    if command == "codex":
        asyncio.run(codex(sys.argv[2]))
    elif command == "embedding":
        asyncio.run(embedding(sys.argv[2] == "busy"))
    elif command == "pdf":
        extraction(sys.argv[2])
    elif command == "pdf-gated":
        gated_extraction(*sys.argv[2:5])
