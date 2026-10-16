"""Where Ollama, LM Studio and Zotero are looked for on each OS, which install button a card gets, and what the inventory
says about the copy it chose (pre-P10 B1, E15).

The OS is a monkeypatched `sys.platform` with fake folders under tmp_path (fake Applications, Program Files, Flatpak and
home folders). Passing shows where DEIXIS looks and what it reports; it does not show that a real Windows or Linux
installer puts the app there: those places come from each project's installation documentation, named in `local_tools`.
"""

import asyncio
import dataclasses
import os
import sys

import httpx
import pytest

from deixis.tools import local_tools

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="the fake programs are shell scripts")


def script(path, body="echo fake 1.2.3"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)
    return path


def refuse(request):
    raise httpx.ConnectError("connection refused", request=request)


@pytest.fixture
def detect(tmp_path, monkeypatch):
    """`detect(tool_id)` → what the Settings card is built from, with the real `app_locations` and a fake home. The macOS
    app installs and the host's PATH are out of the picture; PATH holds only folders a test adds."""
    monkeypatch.setattr(local_tools, "app_locations", local_tools.app_locations.real)
    monkeypatch.setattr(local_tools, "OLLAMA_MAC", False)
    monkeypatch.setattr(local_tools, "LMSTUDIO_MAC", False)
    (tmp_path / "home").mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(local_tools, "SYSTEM_ROOT", tmp_path / "root")
    for variable in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        monkeypatch.delenv(variable, raising=False)
    tools = local_tools.LocalTools(httpx.AsyncClient(transport=httpx.MockTransport(refuse)))

    def run(tool_id):
        return asyncio.run(tools._detect(local_tools.TOOLS[tool_id]))
    run.tools = tools
    return run


# ---- where each OS puts the apps -----------------------------------------------------------------------------

@posix_only
def test_on_windows_the_per_user_and_program_files_folders_are_searched(detect, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    local, files = tmp_path / "AppData" / "Local", tmp_path / "Program Files"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("ProgramFiles", str(files))
    assert [detect(t)["installed"] for t in ("ollama", "lm_studio", "zotero")] == [False] * 3
    ollama = script(local / "Programs" / "Ollama" / "ollama.exe", "echo ollama version is 0.5.1")
    lm_studio = script(local / "Programs" / "LM Studio" / "LM Studio.exe")
    zotero = script(files / "Zotero" / "zotero.exe")
    found = {t: detect(t) for t in ("ollama", "lm_studio", "zotero")}
    assert [(f["installed"], f["path"]) for f in found.values()] == [(True, str(ollama)), (True, str(lm_studio)), (True, str(zotero))]
    assert found["ollama"]["version"] == "ollama version is 0.5.1"  # a command is asked for its version where it was found
    assert found["lm_studio"]["version"] is None and found["lm_studio"]["runnable"] is None  # an app window is never started to ask


@posix_only
def test_on_windows_a_system_wide_ollama_in_program_files_counts_too(detect, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    exe = script(tmp_path / "pf" / "Ollama" / "ollama.exe")
    assert (detect("ollama")["installed"], detect("ollama")["path"]) == (True, str(exe))


@posix_only
def test_on_linux_the_usual_binary_folders_the_appimage_folder_and_both_flatpak_exports_are_searched(detect, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    root, home = tmp_path / "root", tmp_path / "home"
    assert [detect(t)["installed"] for t in ("ollama", "lm_studio", "zotero")] == [False] * 3
    ollama = script(root / "usr" / "local" / "bin" / "ollama")
    appimage = home / "Applications" / "LM-Studio-0.3.9-x64.AppImage"
    appimage.parent.mkdir(parents=True)
    appimage.write_bytes(b"\x7fELF")
    assert (detect("ollama")["path"], detect("lm_studio")["path"]) == (str(ollama), str(appimage))
    assert detect("lm_studio")["installed"] and detect("lm_studio")["version"] is None

    user_flatpak = script(home / ".local" / "share" / "flatpak" / "exports" / "bin" / "org.zotero.Zotero")
    assert (detect("zotero")["installed"], detect("zotero")["path"]) == (True, str(user_flatpak))
    user_flatpak.unlink()
    system_flatpak = script(root / "var" / "lib" / "flatpak" / "exports" / "bin" / "org.zotero.Zotero")
    assert detect("zotero")["path"] == str(system_flatpak)
    system_flatpak.unlink()
    unpacked = script(root / "opt" / "zotero" / "zotero")
    assert detect("zotero")["path"] == str(unpacked)


@posix_only
@pytest.mark.parametrize("where, tool_id", [(("usr", "bin", "ollama"), "ollama"), (("snap", "bin", "ollama"), "ollama"),
                                            (("usr", "bin", "zotero"), "zotero")])
def test_on_linux_a_distribution_package_or_snap_is_found_in_its_own_folder(detect, tmp_path, monkeypatch, where, tool_id):
    monkeypatch.setattr(sys, "platform", "linux")
    exe = script(tmp_path.joinpath("root", *where))
    assert detect(tool_id)["path"] == str(exe)


@posix_only
def test_on_linux_a_command_in_the_home_local_bin_counts(detect, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    exe = script(tmp_path / "home" / ".local" / "bin" / "zotero")
    assert detect("zotero")["path"] == str(exe)


@posix_only
def test_the_lms_command_lm_studio_sets_up_is_found_on_every_os(detect, tmp_path, monkeypatch):
    lms = script(tmp_path / "home" / ".lmstudio" / "bin" / "lms", "echo lms 0.3.9")
    for platform in ("darwin", "linux"):
        monkeypatch.setattr(sys, "platform", platform)
        found = detect("lm_studio")
        assert (found["installed"], found["path"], found["version"]) == (True, str(lms), "lms 0.3.9")


@posix_only
def test_on_macos_an_app_in_the_users_own_applications_folder_counts_and_other_oses_folders_are_not_read(detect, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    tool = dataclasses.replace(local_tools.TOOLS["zotero"], app=str(tmp_path / "Applications" / "Zotero.app"))
    monkeypatch.setitem(local_tools.TOOLS, "zotero", tool)
    mine = tmp_path / "home" / "Applications" / "Zotero.app"
    mine.mkdir(parents=True)
    script(tmp_path / "root" / "usr" / "bin" / "zotero")  # a Linux place; macOS does not look there
    found = detect("zotero")
    assert (found["installed"], found["path"]) == (True, str(mine))
    mine.rmdir()
    assert detect("zotero")["installed"] is False


@posix_only
def test_a_windows_folder_is_not_read_on_linux_and_the_other_way_round(detect, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    script(tmp_path / "Local" / "Programs" / "Ollama" / "ollama.exe")
    monkeypatch.setattr(sys, "platform", "linux")
    assert detect("ollama")["installed"] is False
    script(tmp_path / "root" / "usr" / "bin" / "ollama")
    monkeypatch.setattr(sys, "platform", "win32")
    assert detect("ollama")["path"].endswith("ollama.exe")


# ---- an install button runs a command only where its package manager is -------------------------------------

def card(detect, tool_id, tmp_path, monkeypatch, platform, present=()):
    """The install part of a tool's card on `platform`, with the named programs present. A lookup by file name stands in for
    `find_tool`: `shutil.which` cannot be run as Windows on another OS."""
    monkeypatch.setattr(sys, "platform", platform)
    folder = tmp_path / "managers"
    for name in present:
        script(folder / name, "exit 0")
    monkeypatch.setattr(local_tools, "find_tool", lambda name: str(folder / name) if name in present else None)
    monkeypatch.setattr(local_tools, "find_tools", lambda name: [])
    return detect(tool_id)["install"]


@posix_only
@pytest.mark.parametrize("tool_id", ["ollama", "lm_studio", "zotero", "goose"])
def test_on_windows_a_tool_whose_command_is_homebrew_links_to_its_download_page_even_if_a_brew_is_on_path(detect, tmp_path, monkeypatch, tool_id):
    install = card(detect, tool_id, tmp_path, monkeypatch, "win32", present=("brew",))
    assert (install["available"], install["unavailable_reason"], install["command"], install["manager"]) == (False, "download_page", None, None)
    assert install["url"] == local_tools.TOOLS[tool_id].url


@posix_only
def test_on_linux_a_homebrew_cask_is_never_offered_and_a_formula_only_when_brew_is_found(detect, tmp_path, monkeypatch):
    for tool_id in ("lm_studio", "zotero"):
        install = card(detect, tool_id, tmp_path, monkeypatch, "linux", present=("brew",))
        assert (install["available"], install["unavailable_reason"], install["command"]) == (False, "download_page", None), tool_id
    with_brew = card(detect, "ollama", tmp_path, monkeypatch, "linux", present=("brew",))
    assert (with_brew["available"], with_brew["command"], with_brew["manager"]) == (True, "brew install ollama", "brew")
    without = card(detect, "ollama", tmp_path, monkeypatch, "linux")
    assert (without["available"], without["unavailable_reason"]) == (False, "download_page")  # Homebrew is no Linux default


@posix_only
def test_on_macos_homebrew_is_the_manager_and_its_absence_is_named(detect, tmp_path, monkeypatch):
    present = card(detect, "zotero", tmp_path, monkeypatch, "darwin", present=("brew",))
    assert (present["available"], present["command"]) == (True, "brew install --cask zotero")
    missing = card(detect, "zotero", tmp_path, monkeypatch, "darwin")
    assert (missing["available"], missing["unavailable_reason"], missing["manager"]) == (False, "manager_missing", "brew")


@posix_only
@pytest.mark.parametrize("platform", ["darwin", "linux", "win32"])
def test_npm_and_uv_installs_follow_whether_npm_and_uv_are_found_on_any_os(detect, tmp_path, monkeypatch, platform):
    assert card(detect, "codex", tmp_path, monkeypatch, platform, present=("npm",))["available"] is True
    no_npm = card(detect, "codex", tmp_path, monkeypatch, platform)
    assert (no_npm["available"], no_npm["unavailable_reason"], no_npm["manager"]) == (False, "manager_missing", "npm")
    assert card(detect, "kimi_cli", tmp_path, monkeypatch, platform, present=("uv",))["available"] is True
    assert card(detect, "kimi_cli", tmp_path, monkeypatch, platform)["unavailable_reason"] == "uv_missing"


@posix_only
def test_asking_for_an_install_with_no_command_here_is_refused_with_the_download_page_code(detect, tmp_path, monkeypatch):
    monkeypatch.setattr(local_tools, "find_tool", lambda name: None)
    monkeypatch.setattr(local_tools, "find_tools", lambda name: [])
    monkeypatch.setattr(sys, "platform", "win32")

    async def ask(tool_id):
        return await detect.tools.install(tool_id)
    with pytest.raises(local_tools.ToolError) as refused:
        asyncio.run(ask("zotero"))
    assert (refused.value.status, refused.value.code) == (422, "download_page")
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(local_tools.ToolError) as no_brew:
        asyncio.run(ask("ollama"))
    assert (no_brew.value.status, no_brew.value.code) == (422, "download_page")


# ---- the copy chosen, whether it ran, and the others (E15) --------------------------------------------------

@posix_only
def test_a_broken_copy_is_found_and_chosen_but_reported_as_not_run(detect, tmp_path, monkeypatch):
    broken = script(tmp_path / "a" / "qwen", "echo 'dyld: Library not loaded' >&2\nexit 1")
    monkeypatch.setenv("PATH", str(broken.parent))
    found = detect("qwen_code")
    assert (found["installed"], found["path"], found["runnable"], found["version"]) == (True, str(broken), False, None)
    assert found["reason_code"] == "not_runnable" and found["other_copies"] == []


@posix_only
def test_an_old_copy_that_runs_is_reported_as_it_is_because_nothing_in_deixis_needs_a_minimum_version(detect, tmp_path, monkeypatch):
    old = script(tmp_path / "a" / "qwen", "echo 0.0.1")
    monkeypatch.setenv("PATH", str(old.parent))
    found = detect("qwen_code")
    assert (found["runnable"], found["version"], found["reason_code"]) == (True, "0.0.1", None)


@posix_only
def test_two_installs_report_the_first_as_chosen_and_the_other_as_present(detect, tmp_path, monkeypatch):
    first, second = script(tmp_path / "npm" / "qwen", "echo 1.0.0"), script(tmp_path / "brew" / "qwen", "echo 2.0.0")
    (tmp_path / "links").mkdir()
    (tmp_path / "links" / "qwen").symlink_to(first)  # the same file again is not a second install
    monkeypatch.setenv("PATH", os.pathsep.join([str(first.parent), str(tmp_path / "links"), str(second.parent)]))
    found = detect("qwen_code")
    assert (found["path"], found["version"], found["other_copies"]) == (str(first), "1.0.0", [str(second)])


@posix_only
def test_a_broken_first_copy_does_not_hide_that_a_working_second_one_exists(detect, tmp_path, monkeypatch):
    broken, working = script(tmp_path / "a" / "qwen", "exit 3"), script(tmp_path / "b" / "qwen", "echo 3.1.4")
    monkeypatch.setenv("PATH", os.pathsep.join([str(broken.parent), str(working.parent)]))
    found = detect("qwen_code")
    assert (found["path"], found["runnable"], found["other_copies"]) == (str(broken), False, [str(working)])


@posix_only
def test_a_tool_that_is_not_there_has_no_copy_and_nothing_was_run(detect):
    found = detect("qwen_code")
    assert (found["installed"], found["path"], found["runnable"], found["other_copies"], found["reason_code"]) == (False, None, None, [], None)


# ---- review fixes -------------------------------------------------------------------------------------------

@posix_only
def test_on_windows_a_cmd_launcher_is_probed_through_node_like_the_adapters_start_it(detect, tmp_path, monkeypatch):
    folder = tmp_path / "npm"
    (folder / "node_modules" / "qwen").mkdir(parents=True)
    script(folder / "node_modules" / "qwen" / "cli.js", "echo not run directly")  # only started as an argument of node
    node = script(folder / "node.exe", 'case "$1" in *cli.js) echo "qwen 1.4.0";; *) exit 9;; esac')
    launcher = folder / "qwen.cmd"
    launcher.write_text('@ECHO off\r\n"%_prog%"  "%dp0%\\node_modules\\qwen\\cli.js" %*\r\n')
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(local_tools, "find_tool", lambda name: str(launcher) if name == "qwen" else None)
    monkeypatch.setattr(local_tools, "find_tools", lambda name: [])
    found = detect("qwen_code")
    assert (found["path"], found["runnable"], found["version"], found["reason_code"]) == (str(launcher), True, "qwen 1.4.0", None)
    assert node.exists()


@posix_only
def test_on_windows_a_launcher_that_cannot_be_started_safely_is_reported_as_an_unsupported_install(detect, tmp_path, monkeypatch):
    launcher = tmp_path / "npm" / "qwen.cmd"
    launcher.parent.mkdir()
    launcher.write_text("@ECHO off\r\nsomething else\r\n")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(local_tools, "find_tool", lambda name: str(launcher) if name == "qwen" else None)
    monkeypatch.setattr(local_tools, "find_tools", lambda name: [])
    found = detect("qwen_code")
    assert (found["installed"], found["runnable"], found["reason_code"]) == (True, False, "unsupported_install")


@posix_only
def test_a_second_install_found_through_the_app_locations_is_an_other_copy(detect, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    user = script(tmp_path / "Local" / "Programs" / "Ollama" / "ollama.exe", "echo ollama version is 0.5.1")
    system = script(tmp_path / "pf" / "Ollama" / "ollama.exe", "echo ollama version is 0.4.0")
    found = detect("ollama")
    assert (found["path"], found["other_copies"]) == (str(user), [str(system)])
    monkeypatch.setattr(local_tools, "find_tool", lambda name: str(user) if name == "ollama" else None)  # also on PATH: still one other copy
    monkeypatch.setattr(local_tools, "find_tools", lambda name: [str(user), str(system)] if name == "ollama" else [])
    assert detect("ollama")["other_copies"] == [str(system)]


@posix_only
def test_a_folder_or_a_file_that_cannot_run_is_not_an_installed_app(detect, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    (tmp_path / "Local" / "Programs" / "Ollama" / "ollama.exe").mkdir(parents=True)  # a folder with the program's name
    found = detect("ollama")
    assert (found["installed"], found["path"]) == (False, None)
    monkeypatch.setattr(sys, "platform", "linux")
    plain = tmp_path / "root" / "usr" / "bin" / "ollama"
    plain.parent.mkdir(parents=True)
    plain.write_text("not executable")
    assert detect("ollama")["installed"] is False  # no executable bit
    plain.chmod(0o755)
    assert detect("ollama")["installed"] is True
    monkeypatch.setattr(sys, "platform", "darwin")
    tool = dataclasses.replace(local_tools.TOOLS["zotero"], app=str(tmp_path / "Zotero.app"))
    monkeypatch.setitem(local_tools.TOOLS, "zotero", tool)
    (tmp_path / "Zotero.app").write_text("a file, not a bundle")
    assert detect("zotero")["installed"] is False
