"""The environment of child processes that are not model CLIs, and installer output (pre-P10 A5, E4, E18).

Fake tools are shell scripts that write the environment they were given to a file. Passing shows what each child is
handed and that a long line or a broken read cannot leave a job "running"; it does not show a real brew, npm or uv."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

from deixis.tools import child_env as env_module
from deixis.tools import local_tools
from deixis.tools.child_env import child_env

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="the fake tools are shell scripts")

SECRETS = {"OPENAI_API_KEY": "sk-secret-1", "GITHUB_TOKEN": "ghp_secret-2", "MATHPIX_CREDENTIALS": '{"app_key": "k"}',
           "MATHPIX_APP_KEY": "secret-3", "AWS_SECRET_ACCESS_KEY": "secret-4", "FOO": "bar"}


def source(**extra):
    return {"PATH": "/usr/bin:/bin", "HOME": "/Users/a", "TMPDIR": "/tmp/x", "LANG": "tr_TR.UTF-8", "LC_ALL": "tr_TR.UTF-8",
            "SYSTEMROOT": r"C:\Windows", "WINDIR": r"C:\Windows", "TEMP": r"C:\t", "TMP": r"C:\t", "PATHEXT": ".EXE",
            "COMSPEC": r"C:\Windows\cmd.exe", "USERPROFILE": r"C:\Users\a", "LOCALAPPDATA": r"C:\l", "APPDATA": r"C:\r",
            "HTTPS_PROXY": "http://proxy:3128", "no_proxy": "localhost", **SECRETS, **extra}


# ---- the allowlist ---------------------------------------------------------------------------------

def test_a_child_gets_what_the_system_needs_and_path_and_nothing_else():
    env = child_env(source=source())
    assert {"HOME", "TMPDIR", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT", "COMSPEC", "USERPROFILE",
            "LOCALAPPDATA", "APPDATA", "PATH"} <= set(env)
    assert not set(SECRETS) & set(env)
    assert not {"HTTPS_PROXY", "no_proxy"} & set(env)  # a child that does not use the network gets no proxy settings


def test_keys_loaded_into_this_process_never_reach_a_real_child(monkeypatch):
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    done = subprocess.run([sys.executable, "-c", "import os, json; print(json.dumps(sorted(os.environ)))"],
                          env=child_env({"PYTHONPATH": "x"}), capture_output=True, text=True, check=True)
    seen = set(__import__("json").loads(done.stdout))
    assert not set(SECRETS) & seen and {"PATH", "PYTHONPATH"} <= seen


# ---- frozen mode ----------------------------------------------------------------------------------


# ---- every non-model child is built from it --------------------------------------------------------

def test_no_child_process_is_started_with_the_whole_environment():
    """A grep over the sources: `os.environ` is never copied whole into a child's env (the model CLIs use their own lists)."""
    root = Path(env_module.__file__).parents[1]
    offenders = [f"{p.relative_to(root)}:{n}" for p in root.rglob("*.py")
                 for n, line in enumerate(p.read_text().splitlines(), 1)
                 if "**os.environ" in line and p.name not in {"claude.py", "gemini.py"}]  # --version probes of the CLIs
    assert offenders == []


def dump_env(path: Path, name: str, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    program = folder / name
    program.write_text(f"#!/bin/sh\nenv > {path}\nexit 0\n")
    program.chmod(0o755)
    return program


def seen_by(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)


def assert_clean(seen: dict[str, str]):
    assert not set(SECRETS) & set(seen)
    assert seen["PATH"]


@pytest.fixture
def secrets(monkeypatch):
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)


@posix_only
def test_the_tool_installer_never_sees_a_key_and_gives_npm_and_uv_the_system_certificates(tmp_path, secrets):
    seen = tmp_path / "env"
    npm = dump_env(seen, "npm", tmp_path / "bin")
    tools = local_tools.LocalTools(None)
    job = {"status": "running", "command": "npm", "started_at": "t", "finished_at": None, "output": ""}
    asyncio.run(tools._run("ollama", job, [str(npm), "install"]))
    assert job["status"] == "succeeded"
    env = seen_by(seen)
    assert_clean(env)
    assert (env["UV_NATIVE_TLS"], env["NODE_USE_SYSTEM_CA"]) == ("1", "1")


@posix_only
def test_the_built_in_model_server_never_sees_a_key_or_a_network_setting(tmp_path, secrets, monkeypatch):
    from deixis.documents import builtin_catalog, local_embedding
    from builtin_helpers import install_runtime

    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:1")
    paths = local_embedding.builtin_paths(tmp_path / "data")
    install_runtime(paths)
    seen = {}

    async def capture(*argv, **kwargs):
        seen.update(kwargs["env"])
        raise OSError("SYNTHETIC: not started")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture)
    server = local_embedding.LlamaServer(paths, builtin_catalog.get("qwen3-embedding-0.6b"), None)
    with pytest.raises(local_embedding.LocalEmbeddingError):
        asyncio.run(server.start())
    assert_clean(seen)
    assert "HTTPS_PROXY" not in seen  # loopback only: no network settings at all


# ---- installer output (E18) ------------------------------------------------------------------------


def fake(tmp_path, body):
    program = tmp_path / "bin" / "installer"
    program.parent.mkdir(exist_ok=True)
    program.write_text("#!/bin/sh\n" + body)
    program.chmod(0o755)
    return program


# ---- cancellation while the process is being started ------------------------------------------------

def test_the_production_allowlist_has_no_test_prefix():
    """tests/conftest.py widens it with FAKE_ for the fake tools; a fresh interpreter shows what ships."""
    done = subprocess.run([sys.executable, "-c", "from deixis.tools import child_env; print(child_env.OS_PREFIXES)"],
                          env={"PYTHONPATH": str(Path(env_module.__file__).parents[2]), "PATH": "/usr/bin:/bin"},
                          capture_output=True, text=True, check=True)
    assert done.stdout.strip() == "('LC_',)"
    assert "FAKE_" not in Path(env_module.__file__).read_text()
