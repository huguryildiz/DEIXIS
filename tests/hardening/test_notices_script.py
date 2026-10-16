"""The third-party notices script (pre-P10 F2): a licence it cannot name stops the build, a known one is written out.

Passing shows the scan's rules (name normalisation, the unknown-licence exit, platform markers) and that the committed
THIRD_PARTY_NOTICES lists every production dependency of the lock files at the time of the test. It does not show that
a licence field is true.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.licenses import build_notices as notices

REPO = Path(__file__).resolve().parents[2]


def test_known_licences_are_named_and_unknown_ones_are_listed():
    assert notices.normalize("MIT License") == ("MIT", [])
    assert notices.normalize("Apache-2.0 OR BSD-3-Clause") == ("Apache-2.0 OR BSD-3-Clause", [])
    assert notices.normalize("(MIT AND Zlib)") == ("(MIT AND Zlib)", [])
    assert notices.normalize("Dual Licensed - GNU AFFERO GPL 3.0 or Artifex")[1] != []
    assert notices.normalize("")[1] == ["(none)"]
    assert notices.normalize("SEE LICENSE IN LICENSE.txt")[1] != []


def test_platform_markers_keep_a_package_one_target_needs():
    marker = notices._condition_true
    assert marker("sys_platform == 'win32'", "win32") and not marker("sys_platform == 'win32'", "linux")
    assert marker("platform_python_implementation != 'PyPy'", "darwin")
    assert not marker("sys_platform == 'emscripten'", "darwin")
    with pytest.raises(ValueError):
        marker("python_version < '3.9'", "darwin")


def fake_web(tmp_path: Path, license_value) -> Path:
    web = tmp_path / "web"
    (web / "node_modules" / "left-pad").mkdir(parents=True)
    (web / "node_modules" / "left-pad" / "package.json").write_text(json.dumps({"name": "left-pad", "version": "1.0.0", **license_value}))
    (web / "node_modules" / "left-pad" / "LICENSE").write_text("Copyright left-pad authors")
    (web / "package-lock.json").write_text(json.dumps({"packages": {
        "": {}, "node_modules/left-pad": {"version": "1.0.0", "license": "MIT"},
        "node_modules/dev-only": {"version": "1.0.0", "license": "GPL-3.0", "dev": True}}}))
    return web


def test_an_npm_package_with_an_unknown_licence_is_reported_and_the_dev_only_one_is_not(tmp_path):
    entries = notices.npm_entries(fake_web(tmp_path, {"license": "WTFPL-ish"}))
    assert [e["name"] for e in entries] == ["left-pad"]
    problems = notices.resolve(entries)
    assert len(problems) == 1 and "left-pad 1.0.0" in problems[0] and "WTFPL-ish" in problems[0]


def test_an_npm_package_with_a_known_licence_carries_its_licence_file(tmp_path):
    entries = notices.npm_entries(fake_web(tmp_path, {"license": "MIT"}))
    assert notices.resolve(entries) == [] and entries[0]["license"] == "MIT"
    assert entries[0]["texts"] == [("LICENSE", "Copyright left-pad authors")]
    assert "left-pad 1.0.0 (npm) - MIT" in notices.render(entries, "NATIVE PART")


def test_the_script_exits_non_zero_and_lists_the_packages_when_a_licence_is_unknown(tmp_path, monkeypatch, capsys):
    (tmp_path / "apps" / "web" / "node_modules").mkdir(parents=True)
    monkeypatch.setattr(notices, "REPO", tmp_path)
    web = fake_web(tmp_path, {"license": "WTFPL-ish"})
    monkeypatch.setattr(notices, "build", lambda: _build(web))
    out = tmp_path / "NOTICES"
    assert notices.main(["--out", str(out)]) == 1
    assert "left-pad 1.0.0" in capsys.readouterr().err and not out.exists()


def _build(web: Path):
    entries = notices.python_entries([]) + notices.npm_entries(web)
    problems = notices.resolve(entries)
    return notices.render(entries, "NATIVE"), problems


def test_a_python_package_not_installed_here_needs_an_override():
    entries = notices.python_entries([("no-such-distribution-xyz", "1.0")])
    assert notices.resolve(entries) and "no override" in entries[0]["note"]
    entries = notices.python_entries([("pywin32", "312")])  # Windows only, so never installed on a Mac or Linux build machine
    assert notices.resolve(entries) == [] and entries[0]["license"] == "PSF-2.0"


def test_the_committed_notices_file_covers_every_production_dependency():
    text = (REPO / "THIRD_PARTY_NOTICES").read_text(encoding="utf-8")
    assert "MuPDF" in text and "Tesseract" in text and "Tauri" in text and "marker-pdf 1.10.2" in text
    for name, version in notices.python_requirements():
        assert f"python {name} {version}" in text
    lock = json.loads((REPO / "apps/web/package-lock.json").read_text(encoding="utf-8"))
    for key, info in lock["packages"].items():
        if key and not info.get("dev"):
            assert f"npm    {key.rsplit('node_modules/', 1)[-1]} {info['version']}" in text
