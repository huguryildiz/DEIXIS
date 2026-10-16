"""Finding command-line tools when the app was started from the desktop (pre-P10 A3).

Fake tools are small shell scripts; fake login shells are scripts named `zsh`. Passing shows where `find_tool` looks and
how it reads the shell's PATH, not that a real Finder-started app finds a real Homebrew or nvm install."""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from deixis.tools import tool_paths

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="the fake tools and shells are shell scripts")


def tool(folder: Path, name: str = "codex") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text("#!/bin/sh\necho fake\n")
    path.chmod(0o755)
    return path


def shell(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


@pytest.fixture
def short_path(monkeypatch):
    """What a Finder-started app sees: no tool folders on PATH, no shell asked, no known folders (the autouse fixture)."""
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(tool_paths, "_shell_path", None)
    monkeypatch.setattr(tool_paths, "SHELL_TIMEOUT", 20.0)  # a busy test machine starts a script slowly; the timeout tests set their own
    monkeypatch.delenv("SHELL", raising=False)


@posix_only
def test_a_tool_on_the_process_path_is_found_first(tmp_path, monkeypatch, short_path):
    on_path, known = tool(tmp_path / "path"), tool(tmp_path / "known")
    monkeypatch.setenv("PATH", f"{on_path.parent}:/usr/bin:/bin")
    monkeypatch.setattr(tool_paths, "known_places", lambda: [str(known.parent)])
    assert tool_paths.find_tool("codex") == str(on_path)


@posix_only
def test_with_an_empty_path_a_tool_is_found_in_a_known_place(tmp_path, monkeypatch, short_path):
    monkeypatch.setenv("PATH", "")
    fake = tool(tmp_path / "opt" / "bin")
    monkeypatch.setattr(tool_paths, "known_places", lambda: [str(tmp_path / "missing"), str(fake.parent)])
    assert tool_paths.find_tool("codex") == str(fake)
    assert tool_paths.find_tool("no-such-tool") is None


@posix_only
def test_the_known_places_cover_homebrew_npm_uv_and_the_node_managers(tmp_path, monkeypatch):
    home = tmp_path / "home"
    for version in ("v18.20.0", "v22.4.1", "v22.19.0"):
        (home / ".nvm" / "versions" / "node" / version / "bin").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("NVM_DIR", raising=False)
    monkeypatch.delenv("FNM_DIR", raising=False)
    places = tool_paths.known_places.real()
    for expected in (home / ".local" / "bin", home / ".npm-global" / "bin", home / ".volta" / "bin"):
        assert str(expected) in places
    assert {"/opt/homebrew/bin", "/usr/local/bin"} <= set(places)
    nvm = [p for p in places if "/.nvm/" in p]
    assert [Path(p).parent.name for p in nvm] == ["v22.19.0", "v22.4.1", "v18.20.0"]  # the newest Node first


@posix_only
def test_the_bundles_own_bin_folder_comes_before_everything_when_frozen(tmp_path, monkeypatch, short_path):
    bundled, other = tool(tmp_path / "bundle" / "bin", "uv"), tool(tmp_path / "path", "uv")
    monkeypatch.setenv("PATH", f"{other.parent}:/usr/bin:/bin")
    monkeypatch.setattr(tool_paths, "is_frozen", lambda: True)
    monkeypatch.setattr(tool_paths, "resource_root", lambda: tmp_path / "bundle")
    assert tool_paths.find_tool("uv") == str(bundled)
    monkeypatch.setattr(tool_paths, "is_frozen", lambda: False)
    assert tool_paths.find_tool("uv") == str(other)


# ---- the login shell ------------------------------------------------------------------------------

@posix_only
def test_the_login_shells_path_is_the_last_place_looked_and_the_answer_is_kept(tmp_path, monkeypatch, short_path):
    fake = tool(tmp_path / "nvm" / "bin")
    count = tmp_path / "count"
    login = shell(tmp_path / "bin" / "zsh", f"echo x >> {count}\nprintf '__DEIXIS_PATH__%s__END__' '/usr/bin:{fake.parent}'\n")
    monkeypatch.setenv("SHELL", str(login))
    assert tool_paths.find_tool("codex") == str(fake)
    assert tool_paths.find_tool("codex") == str(fake) and tool_paths.find_tool("other") is None
    assert count.read_text().count("x") == 1  # read once per process


@posix_only
def test_a_known_place_wins_so_the_shell_is_not_asked_at_all(tmp_path, monkeypatch, short_path):
    known = tool(tmp_path / "known")
    asked = tmp_path / "asked"
    monkeypatch.setenv("SHELL", str(shell(tmp_path / "zsh", f"touch {asked}\n")))
    monkeypatch.setattr(tool_paths, "known_places", lambda: [str(known.parent)])
    assert tool_paths.find_tool("codex") == str(known)
    assert not asked.exists()


@posix_only
def test_a_greeting_and_other_noise_around_the_path_are_ignored(tmp_path, monkeypatch, short_path):
    fake = tool(tmp_path / "volta" / "bin")
    login = shell(tmp_path / "zsh", "echo 'Welcome back!'\necho '__DEIXIS_PATH__ not the path, no end marker'\n"
                                    f"printf '__DEIXIS_PATH__%s__END__' '/bin:relative/dir:{fake.parent}'\n"
                                    "echo '\\033[1mfortune: a long day'\n")
    monkeypatch.setenv("SHELL", str(login))
    assert tool_paths.login_shell_path() == ["/bin", str(fake.parent)]  # the relative folder is dropped
    assert tool_paths.find_tool("codex") == str(fake)


@posix_only
def test_a_shell_that_does_not_answer_in_time_is_killed_and_detection_goes_on(tmp_path, monkeypatch, short_path):
    pid_file = tmp_path / "pid"
    login = shell(tmp_path / "zsh", f"echo $$ > {pid_file}\nexec sleep 60\n")
    monkeypatch.setenv("SHELL", str(login))
    monkeypatch.setattr(tool_paths, "SHELL_TIMEOUT", 1.5)
    started = time.monotonic()
    assert tool_paths.find_tool("codex") is None
    assert time.monotonic() - started < 6
    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("the shell that did not answer was left running")
    assert tool_paths.login_shell_path() == []  # the failure is kept too: it is not tried again


@posix_only
def test_endless_output_without_the_markers_is_cut_off(tmp_path, monkeypatch, short_path):
    login = shell(tmp_path / "zsh", "yes 'a line of noise that never ends and never names a path'\n")
    monkeypatch.setenv("SHELL", str(login))
    started = time.monotonic()
    assert tool_paths.login_shell_path() == []
    assert time.monotonic() - started < 15  # the output cap, not the 20 s timeout, ends it


@posix_only
@pytest.mark.parametrize("name", ["fish", "nu", "tcsh", "evil"])
def test_only_bash_zsh_and_sh_are_ever_asked(tmp_path, monkeypatch, short_path, name):
    asked = tmp_path / "asked"
    monkeypatch.setenv("SHELL", str(shell(tmp_path / name, f"touch {asked}\nprintf '__DEIXIS_PATH__/bin__END__'\n")))
    assert tool_paths.login_shell_path() == [] and not asked.exists()


@posix_only
def test_a_relative_or_missing_shell_is_not_started(monkeypatch, short_path):
    for value in ("zsh", "/no/such/dir/zsh", ""):
        monkeypatch.setattr(tool_paths, "_shell_path", None)
        monkeypatch.setenv("SHELL", value)
        assert tool_paths.login_shell_path() == []


@posix_only
def test_the_shell_runs_a_fixed_command_with_no_input(tmp_path, monkeypatch, short_path):
    record = tmp_path / "argv"
    login = shell(tmp_path / "zsh", f"printf '%s\\n' \"$@\" > {record}\nread line && echo stdin-was-open > {tmp_path / 'stdin'}\n")
    monkeypatch.setenv("SHELL", str(login))
    assert tool_paths.login_shell_path() == []
    assert record.read_text().splitlines() == ["-i", "-l", "-c", tool_paths.SHELL_COMMAND]
    assert not (tmp_path / "stdin").exists()


# ---- what the shell is handed, and the event loop -------------------------------------------------

@posix_only
def test_the_login_shell_gets_a_minimal_environment_and_no_key_or_proxy(tmp_path, monkeypatch, short_path):
    seen = tmp_path / "env"
    login = shell(tmp_path / "zsh", f"env > {seen}\nprintf '__DEIXIS_PATH__%s__END__' \"$PATH\"\n")
    for name, value in {"OPENAI_API_KEY": "sk-shell-secret", "GITHUB_TOKEN": "ghp_shell-secret", "MATHPIX_CREDENTIALS": "m-secret",
                        "HTTPS_PROXY": "http://user:pw@proxy:3128", "no_proxy": "x", "FOO": "bar"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("SHELL", str(login))
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("PATH", "/usr/bin:/bin:/process/path")
    tool_paths.login_shell_path()
    given = dict(line.split("=", 1) for line in seen.read_text().splitlines() if "=" in line)
    assert not {"OPENAI_API_KEY", "GITHUB_TOKEN", "MATHPIX_CREDENTIALS", "HTTPS_PROXY", "no_proxy", "FOO"} & set(given)
    assert "secret" not in seen.read_text() and "proxy" not in seen.read_text().lower()
    assert given["PATH"].startswith("/usr/bin:/bin:/process/path") and given["LC_ALL"] == "C" and given["SHELL"] == str(login)
    assert {"HOME"} <= set(given)


@posix_only
def test_the_shells_environment_is_built_without_looking_for_tools(tmp_path, monkeypatch, short_path):
    """Asking for node here would come back into find_tool and its lock."""
    monkeypatch.setattr(tool_paths, "find_tool", lambda name: pytest.fail("find_tool was called for the shell's PATH"))
    env = tool_paths._shell_env()
    assert env["PATH"] == os.environ["PATH"]


@posix_only
def test_on_the_event_loop_the_first_shell_read_is_not_waited_for(tmp_path, monkeypatch, short_path):
    fake = tool(tmp_path / "nvm" / "bin")
    login = shell(tmp_path / "zsh", f"sleep 1.5\nprintf '__DEIXIS_PATH__%s__END__' '/bin:{fake.parent}'\n")
    monkeypatch.setenv("SHELL", str(login))
    monkeypatch.setattr(tool_paths, "_warming", False)

    async def scenario():
        started = time.monotonic()
        first = tool_paths.find_tool("codex")  # called straight on the loop
        waited = time.monotonic() - started
        found = await asyncio.to_thread(tool_paths.find_tool, "codex")  # the way async code asks: the worker waits
        return first, waited, found, tool_paths.find_tool("codex")
    first, waited, found, later = asyncio.run(scenario())
    assert first is None and waited < 0.5
    assert found == str(fake) and later == str(fake)


@posix_only
def test_an_async_health_check_does_not_hold_up_the_loop_while_the_shell_is_read(tmp_path, monkeypatch, short_path):
    from deixis.models import claude

    login = shell(tmp_path / "zsh", "sleep 1.5\nprintf '__DEIXIS_PATH__/bin__END__'\n")
    monkeypatch.setenv("SHELL", str(login))

    async def scenario():
        gaps, running = [], True

        async def beat():
            last = time.monotonic()
            while running:
                await asyncio.sleep(0.05)
                now = time.monotonic()
                gaps.append(now - last)
                last = now
        task = asyncio.create_task(beat())
        status = await claude.ClaudeCodeAdapter(tmp_path).health(refresh=True)
        running = False
        await task
        return status, max(gaps)
    status, longest = asyncio.run(scenario())
    assert status["installed"] is False and longest < 0.5


# ---- the PATH a tool's children get ---------------------------------------------------------------

@posix_only
def test_a_tools_children_get_its_folder_and_nodes_folder_on_path(tmp_path, monkeypatch, short_path):
    codex, node = tool(tmp_path / "npm" / "bin", "codex"), tool(tmp_path / "nvm" / "bin", "node")
    monkeypatch.setattr(tool_paths, "known_places", lambda: [str(node.parent)])
    path = tool_paths.child_path(str(codex))
    assert path.split(os.pathsep) == [str(codex.parent), str(node.parent), "/usr/bin", "/bin"]
    assert tool_paths.child_path(None, "/a:/a:/b").split(os.pathsep) == [str(node.parent), "/a", "/b"]


def test_a_tool_is_found_by_the_name_a_person_would_type(tmp_path, monkeypatch, short_path):
    """On Windows shutil.which adds PATHEXT (codex.cmd, uv.exe); here the same call is shown with an extension list."""
    if sys.platform != "win32":
        pytest.skip("PATHEXT is only read on Windows")
    folder = tmp_path / "npm"
    folder.mkdir()
    (folder / "codex.cmd").write_text("@echo off\n")
    monkeypatch.setenv("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    monkeypatch.setattr(tool_paths, "known_places", lambda: [str(folder)])
    assert Path(tool_paths.find_tool("codex")).name.lower() == "codex.cmd"


def test_no_module_looks_for_a_tool_with_shutil_which_any_more():
    root = Path(tool_paths.__file__).parents[1]
    offenders = [str(p.relative_to(root)) for p in root.rglob("*.py")
                 if p.name != "tool_paths.py" and "shutil.which" in p.read_text()]
    assert offenders == []


# ---- every copy, and the one that comes with the app (B1, E15) --------------------------------------------

@posix_only
def test_every_copy_of_a_tool_is_listed_in_search_order_and_a_link_to_the_same_file_is_one_copy(tmp_path, monkeypatch, short_path):
    first, second = tool(tmp_path / "npm" / "bin"), tool(tmp_path / "brew" / "bin")
    (tmp_path / "local").mkdir()
    (tmp_path / "local" / "codex").symlink_to(first)  # the same file as the first copy, under another path
    monkeypatch.setenv("PATH", os.pathsep.join([str(first.parent), str(tmp_path / "local"), str(second.parent), "/usr/bin"]))
    assert tool_paths.find_tools("codex") == [str(first), str(second)]
    assert tool_paths.find_tool("codex") == str(first)  # the first of them is the one that is used
    assert tool_paths.find_tools("no-such-tool") == []


@posix_only
def test_copies_in_known_places_follow_the_ones_on_path_and_the_shell_is_asked_only_when_nothing_else_has_the_tool(tmp_path, monkeypatch, short_path):
    on_path, known, in_shell = tool(tmp_path / "path"), tool(tmp_path / "known"), tool(tmp_path / "shell")
    count = tmp_path / "count"
    login = shell(tmp_path / "bin" / "zsh", f"echo x >> {count}\nprintf '__DEIXIS_PATH__%s__END__' '{in_shell.parent}'\n")
    monkeypatch.setenv("SHELL", str(login))
    monkeypatch.setenv("PATH", f"{on_path.parent}:/usr/bin")
    monkeypatch.setattr(tool_paths, "known_places", lambda: [str(known.parent)])
    assert tool_paths.find_tools("codex") == [str(on_path), str(known)]
    assert not count.exists()  # found without the shell
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setattr(tool_paths, "known_places", lambda: [])
    assert tool_paths.find_tools("codex") == [str(in_shell)] and count.read_text().count("x") == 1


@posix_only
def test_a_tool_is_bundled_only_in_a_packaged_app_and_only_from_its_own_bin_folder(tmp_path, monkeypatch, short_path):
    inside, outside = tool(tmp_path / "bundle" / "bin", "tesseract"), tool(tmp_path / "other", "tesseract")
    monkeypatch.setattr(tool_paths, "resource_root", lambda: tmp_path / "bundle")
    monkeypatch.setattr(tool_paths, "is_frozen", lambda: False)
    assert not tool_paths.is_bundled(str(inside))  # a run from the repository has no bundle, whatever is in that folder
    monkeypatch.setattr(tool_paths, "is_frozen", lambda: True)
    assert tool_paths.is_bundled(str(inside)) and not tool_paths.is_bundled(str(outside))
    assert not tool_paths.is_bundled(None)
