"""The environment of child processes that are not model CLIs, and installer output (pre-P10 A5, E4, E18).

Fake tools are shell scripts that write the environment they were given to a file. Passing shows what each child is
handed and that a long line or a broken read cannot leave a job "running"; it does not show a real brew, npm or uv."""

import asyncio
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from deixis.tools import child_env as env_module
from deixis.tools import local_tools, tool_paths
from deixis.tools.child_env import NODE_TLS, UV_TLS, child_env
from deixis.documents import tool_updates

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


def test_extra_and_kept_variables_are_added_by_the_caller_only():
    env = child_env({"PYTHONPATH": "/app/backend"}, keep=("TESSDATA_PREFIX", "ABSENT"), source=source(TESSDATA_PREFIX="/t"))
    assert env["PYTHONPATH"] == "/app/backend" and env["TESSDATA_PREFIX"] == "/t" and "ABSENT" not in env
    assert "TESSDATA_PREFIX" not in child_env(source=source(TESSDATA_PREFIX="/t"))


def test_the_proxy_settings_go_only_to_a_child_that_uses_the_network():
    env = child_env(network=True, source=source(SSL_CERT_FILE="/ca.pem"))
    assert env["HTTPS_PROXY"] == "http://proxy:3128" and env["no_proxy"] == "localhost" and env["SSL_CERT_FILE"] == "/ca.pem"
    assert not set(SECRETS) & set(env)


def test_keys_loaded_into_this_process_never_reach_a_real_child(monkeypatch):
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    done = subprocess.run([sys.executable, "-c", "import os, json; print(json.dumps(sorted(os.environ)))"],
                          env=child_env({"PYTHONPATH": "x"}), capture_output=True, text=True, check=True)
    seen = set(__import__("json").loads(done.stdout))
    assert not set(SECRETS) & seen and {"PATH", "PYTHONPATH"} <= seen


def test_the_tools_folder_and_nodes_folder_are_put_on_path(tmp_path, monkeypatch):
    node, codex = tmp_path / "nvm" / "node", tmp_path / "npm" / "codex"
    for p in (node, codex):
        p.parent.mkdir(parents=True)
        p.write_text("#!/bin/sh\n")
        p.chmod(0o755)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")  # no node of this computer on it
    monkeypatch.setattr(tool_paths, "known_places", lambda: [str(node.parent)])
    path = child_env(tool=str(codex), source={"PATH": "/usr/bin"})["PATH"].split(os.pathsep)
    assert path[:2] == [str(codex.parent), str(node.parent)] and path[-1] == "/usr/bin"


# ---- frozen mode ----------------------------------------------------------------------------------

LIBRARIES = {"LD_LIBRARY_PATH": "/bundle/lib:/orig/lib", "LD_LIBRARY_PATH_ORIG": "/orig/lib", "DYLD_LIBRARY_PATH": "/bundle/lib",
             "_PYI_APPLICATION_HOME_DIR": "/bundle", "_MEIPASS2": "/bundle"}


def test_an_outside_program_gets_the_library_path_from_before_the_bundle_started(monkeypatch):
    monkeypatch.setattr(env_module, "is_frozen", lambda: True)
    env = child_env(network=True, source=source(**LIBRARIES))
    assert env["LD_LIBRARY_PATH"] == "/orig/lib"  # restored, as PyInstaller's documentation asks
    assert "DYLD_LIBRARY_PATH" not in env  # there was none before the bundle: none is set
    assert "LD_LIBRARY_PATH_ORIG" not in env and not [k for k in env if k.startswith(("_PYI_", "_MEIPASS"))]


def test_a_child_that_is_part_of_the_bundle_keeps_the_bundles_library_path(monkeypatch):
    monkeypatch.setattr(env_module, "is_frozen", lambda: True)
    env = child_env(bundled=True, source=source(**LIBRARIES))
    assert env["LD_LIBRARY_PATH"] == "/bundle/lib:/orig/lib" and env["DYLD_LIBRARY_PATH"] == "/bundle/lib"
    assert env["LD_LIBRARY_PATH_ORIG"] == "/orig/lib" and env["_PYI_APPLICATION_HOME_DIR"] == "/bundle"
    assert not set(SECRETS) & set(env)


def test_outside_a_bundle_the_persons_own_library_path_is_kept(monkeypatch):
    monkeypatch.setattr(env_module, "is_frozen", lambda: False)
    assert child_env(source=source(LD_LIBRARY_PATH="/mine"))["LD_LIBRARY_PATH"] == "/mine"


# ---- every non-model child is built from it --------------------------------------------------------

def test_no_child_process_is_started_with_the_whole_environment():
    """A grep over the sources: `os.environ` is never copied whole into a child's env (the model CLIs use their own lists)."""
    root = Path(env_module.__file__).parents[1]
    offenders = [f"{p.relative_to(root)}:{n}" for p in root.rglob("*.py")
                 for n, line in enumerate(p.read_text().splitlines(), 1)
                 if "**os.environ" in line and p.name not in {"claude.py", "gemini.py"}]  # --version probes of the CLIs
    assert offenders == []


@posix_only
def test_the_sources_of_pdf_jats_ocr_arxiv_and_the_guard_use_it():
    root = Path(env_module.__file__).parents[1] / "documents"
    for name in ("pdf.py", "jats.py", "ocr.py", "arxiv_source.py", "child_guard.py"):
        assert "child_env(" in (root / name).read_text(), name


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
def test_the_homebrew_tesseract_installer_never_sees_a_key(tmp_path, secrets):
    seen = tmp_path / "env"
    brew = dump_env(seen, "brew", tmp_path / "bin")
    job = {"status": "running", "phase": "preparing", "started_at": "t", "finished_at": None, "output": ""}
    asyncio.run(tool_updates.TesseractInstaller()._run(job, [str(brew), "install", "tesseract"]))
    assert job["status"] == "succeeded"
    env = seen_by(seen)
    assert_clean(env)
    assert env["UV_NATIVE_TLS"] == "1" and env["HOMEBREW_NO_AUTO_UPDATE"] == "1" and env["PATH"].startswith(str(brew.parent))


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


def test_the_model_clis_get_the_node_system_certificate_switch(tmp_path):
    from deixis.models import copilot_cli, gemini_cli

    assert gemini_cli.cli_environment(tmp_path, tmp_path / "c.json", {"PATH": "/usr/bin"})["NODE_USE_SYSTEM_CA"] == "1"
    assert copilot_cli.copilot_environment(tmp_path, {"PATH": "/usr/bin"})["NODE_USE_SYSTEM_CA"] == "1"
    assert NODE_TLS == {"NODE_USE_SYSTEM_CA": "1"} and UV_TLS == {"UV_NATIVE_TLS": "1"}


# ---- installer output (E18) ------------------------------------------------------------------------

def tesseract_run(program, tmp_path):
    job = {"status": "running", "phase": "preparing", "started_at": "t", "finished_at": None, "output": ""}
    return job, tool_updates.TesseractInstaller()._run(job, [str(program)])


def tools_run(program, tmp_path):
    job = {"status": "running", "command": "x", "started_at": "t", "finished_at": None, "output": ""}
    return job, local_tools.LocalTools(None)._run("ollama", job, [str(program)])


RUNNERS = [tesseract_run, tools_run]


def fake(tmp_path, body):
    program = tmp_path / "bin" / "installer"
    program.parent.mkdir(exist_ok=True)
    program.write_text("#!/bin/sh\n" + body)
    program.chmod(0o755)
    return program


@posix_only
@pytest.mark.parametrize("runner", RUNNERS, ids=lambda r: r.__name__)
def test_a_single_endless_line_of_installer_output_neither_hangs_nor_leaves_the_job_running(tmp_path, runner):
    program = fake(tmp_path, "head -c 3000000 /dev/zero | tr '\\0' 'x'\nexit 0\n")  # 3 MB and no newline at all
    job, coroutine = runner(program, tmp_path)
    asyncio.run(asyncio.wait_for(coroutine, 60))
    assert job["status"] == "succeeded" and job["finished_at"]
    assert 0 < len(job["output"]) <= 4000


@posix_only
@pytest.mark.parametrize("runner", RUNNERS, ids=lambda r: r.__name__)
def test_a_failing_installer_ends_the_job_failed_with_the_tail_of_its_output(tmp_path, runner):
    program = fake(tmp_path, "echo first; head -c 9000 /dev/zero | tr '\\0' 'y'; echo; echo the-last-line; exit 3\n")
    job, coroutine = runner(program, tmp_path)
    asyncio.run(asyncio.wait_for(coroutine, 60))
    assert job["status"] == "failed" and job["finished_at"]
    assert job["output"].rstrip().endswith("the-last-line") and "first" not in job["output"]


class BrokenPipe:
    returncode = None
    killed = False

    def __init__(self):
        self.stdout = types.SimpleNamespace(read=self.read)

    async def read(self, size):
        raise OSError("the pipe broke")

    def kill(self):
        self.killed = True

    async def wait(self):
        return 0


@pytest.mark.parametrize("runner", RUNNERS, ids=lambda r: r.__name__)
def test_a_read_that_fails_ends_the_job_failed_and_stops_the_process(tmp_path, monkeypatch, runner):
    proc = BrokenPipe()

    async def start(*args, **kwargs):
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", start)
    job, coroutine = runner(tmp_path / "bin" / "installer", tmp_path)
    asyncio.run(coroutine)
    assert job["status"] == "failed" and job["output"].endswith("[could_not_run]") and job["finished_at"]
    assert "the pipe broke" not in job["output"] and "BrokenPipe" not in job["output"]  # the exception goes to the log (B3)
    assert proc.killed


@posix_only
@pytest.mark.parametrize("runner", [tesseract_run, tools_run], ids=lambda r: r.__name__)
def test_a_job_cancelled_while_it_runs_is_not_left_running(tmp_path, runner):
    program = fake(tmp_path, "echo started; sleep 30\n")

    async def scenario():
        job, coroutine = runner(program, tmp_path)
        task = asyncio.create_task(coroutine)
        while "started" not in job["output"]:
            await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return job
    job = asyncio.run(asyncio.wait_for(scenario(), 30))
    assert job["status"] == "failed" and job["finished_at"]


# ---- cancellation while the process is being started ------------------------------------------------

@pytest.mark.parametrize("runner", RUNNERS, ids=lambda r: r.__name__)
def test_a_job_cancelled_while_its_process_is_being_created_is_not_left_running(tmp_path, monkeypatch, runner):
    async def never(*args, **kwargs):
        await asyncio.sleep(3600)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", never)

    async def scenario():
        job, coroutine = runner(tmp_path / "bin" / "installer", tmp_path)
        task = asyncio.create_task(coroutine)
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return job
    job = asyncio.run(asyncio.wait_for(scenario(), 30))
    assert job["status"] == "failed" and job["finished_at"]


def test_the_production_allowlist_has_no_test_prefix():
    """tests/conftest.py widens it with FAKE_ for the fake tools; a fresh interpreter shows what ships."""
    done = subprocess.run([sys.executable, "-c", "from deixis.tools import child_env; print(child_env.OS_PREFIXES)"],
                          env={"PYTHONPATH": str(Path(env_module.__file__).parents[2]), "PATH": "/usr/bin:/bin"},
                          capture_output=True, text=True, check=True)
    assert done.stdout.strip() == "('LC_',)"
    assert "FAKE_" not in Path(env_module.__file__).read_text()
