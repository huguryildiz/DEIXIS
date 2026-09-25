"""Shared pieces of the built-in embedding tests (slice 21): small SYNTHETIC model files standing in for the five of
the manifest, an installed environment made of them, and a LocalEmbedder that runs the fake runner."""

import hashlib
import json
import os
import sys
from pathlib import Path

from deixis.documents import local_embedding

FAKE_RUNNER = Path(__file__).with_name("fake_embedding_runner.py")
FILE_BODIES = {f.name: f"SYNTHETIC {f.name} ".encode() * (3 + i) for i, f in enumerate(local_embedding.MODEL_FILES)}


def fake_manifest(monkeypatch):
    """Replace the manifest with the SYNTHETIC files' sizes and digests; returns {name: bytes}."""
    files = tuple(local_embedding.ModelFile(name, len(body), hashlib.sha256(body).hexdigest())
                  for name, body in FILE_BODIES.items())
    monkeypatch.setattr(local_embedding, "MODEL_FILES", files)
    return dict(FILE_BODIES)


def install_fake(paths: local_embedding.BuiltinPaths, bodies=None) -> None:
    """An environment as an install leaves it: the model files, a python and `installed.json` last."""
    paths.models.mkdir(parents=True, exist_ok=True)
    for name, body in (bodies or FILE_BODIES).items():
        (paths.models / name).write_bytes(body)
    paths.python.parent.mkdir(parents=True, exist_ok=True)
    if not paths.python.exists():
        os.symlink(sys.executable, paths.python)
    paths.installed_marker.write_text(json.dumps({"model": local_embedding.MODEL_ID}))


def fake_embedder(paths, idle_seconds=300, integrity=None):
    return local_embedding.LocalEmbedder(paths, integrity, idle_seconds=idle_seconds, runner=FAKE_RUNNER,
                                         python=sys.executable)


# A stand-in for uv: records its arguments and the environment it was given, makes `venv` a folder whose python is
# this interpreter, and fails or waits when FAKE_UV_FAIL / FAKE_UV_SLEEP say so.
FAKE_UV = """#!{python}
import json, os, sys, time
record = os.environ["FAKE_UV_RECORD"]
with open(record, "a") as handle:
    handle.write(json.dumps({{"argv": sys.argv[1:], "env": {{k: os.environ.get(k) for k in
        ("UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR", "UV_PYTHON_PREFERENCE", "HF_HOME")}}}}) + "\\n")
step = sys.argv[1]
time.sleep(float(os.environ.get("FAKE_UV_SLEEP", "0")))
if os.environ.get("FAKE_UV_FAIL") == step:
    print("SYNTHETIC uv failure in " + step, flush=True)
    sys.exit(2)
if step == "venv":
    env = sys.argv[-1]
    os.makedirs(os.path.join(env, "bin"), exist_ok=True)
    target = os.path.join(env, "bin", "python")
    if not os.path.exists(target):
        os.symlink({python!r}, target)
    print("SYNTHETIC environment created", flush=True)
else:
    print("SYNTHETIC fastembed installed", flush=True)
"""


def write_fake_uv(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    uv = folder / "uv"
    uv.write_text(FAKE_UV.format(python=sys.executable))
    uv.chmod(0o755)
    return uv
