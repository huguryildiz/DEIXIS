r"""Acceptance of the installed DEIXIS on Windows (P10 W5), the NSIS installer as built by windows-desktop.yml.

    python scripts\p10\windows_acceptance.py --installer DEIXIS_0.1.0_x64-setup.exe [--evidence DIR] [--only ROW,...]
                                             [--fake-python PATH] [--keep-installed]

Standard library only (plus tests/support/helpers.make_pdf, which is too); run with any Windows Python as the user
who will own the install. The fake codex runs with --fake-python (default: this Python), which must import the repo's
`deixis` package (tests/support/fakes.py does). Rows, each PASS, FAIL, NOT_DONE (could not be checked here, the reason
is printed) or MANUAL (a person checks it), with its evidence as JSON; the exit code is 0 only when every row run is
PASS or MANUAL:

  install        `setup.exe /S` as this (non-elevated) user exits 0 with no consent.exe (UAC prompt) seen while it runs;
                 the app lands in %LOCALAPPDATA%\Programs\DEIXIS (deixis-desktop.exe, sidecar\deixis-backend\
                 deixis-backend.exe, uninstall.exe), registered under HKCU, outside the library folder; sizes, SHA-256
  open           deixis-desktop.exe started with a temp DEIXIS_DATA_DIR (a free port other than 8765 saved in it): the
                 top-level "DEIXIS" window is visible (user32 EnumWindows), health 200 with a start nonce on the port
                 read back from desktop-port.json within 60 s, the window's page is the backend's origin (the shell
                 goes there only after the nonce matched), the research screen's texts are in the page; screenshot of
                 the window (PrintWindow, PW_RENDERFULLCONTENT)
  csrf_save      inside the window the sidebar's theme button is clicked and the backend stores the new theme (the
                 page's session cookie + CSRF header); a PUT without the header is refused 403
  second_launch  deixis-desktop.exe again exits 0, the DEIXIS process set is unchanged, the window is visible
  close_keeps    WM_CLOSE to the window hides it; every process stays; health still 200; a further launch shows it again
  tray           the shell's notification icon found (Shell_NotifyIconGetRect; the overflow opened when it is there)
                 and its menu opened with a real click, its items read;
                 MANUAL when the menu does not open that way
  quit_plain     Quit under load (a hanging fake-codex answer and a PDF extraction child): the tray menu's Quit when
                 the tray row opened it, else the local page's Quit link (the same quit() in the shell); nothing left
  kill_shell     TerminateProcess on deixis-desktop.exe under the same load: nothing left within 15 s
  kill_backend   TerminateProcess on deixis-backend.exe under the same load: the window shows the "backend stopped"
                 page (screenshot), nothing of the old backend is left, its Restart starts a new backend; then Quit and
                 nothing left
  download       a finished research's report (Markdown) and its CSV, through the window's Export menu, land in the
                 user's Downloads folder (SHGetKnownFolderPath) with their content; moved into the evidence folder
  uninstall      `uninstall.exe /S` removes the install folder and its HKCU entry; every scenario's library folder and
                 the default library folder (when one exists) keep their files

Inside the window the page is driven over the Chrome DevTools Protocol of WebView2 (WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS
=--remote-debugging-port, the channel msedgedriver uses for WebView2), so no driver has to match the WebView2 version;
when that port does not answer, the in-window rows are NOT_DONE with the reason and csrf_save falls back to the page's
own CSRF flow over HTTP (marked so).

"Nothing left" is checked three ways: every process the watcher saw for the scenario (the shell, its descendants by
parent pid and creation time, anything run from the install folder; Toolhelp32 every 0.2 s) is gone within 15 s; the
Restart Manager (RmGetList) finds no process holding library.sqlite, its -wal/-shm, library.lock, desktop-port.json or
logs\backend.log; and a full process snapshot (Get-CimInstance Win32_Process: pid, parent, creation time, command
line) before the launch and 15 s after the trigger lists every new live process with why it is not DEIXIS, or the row
fails. Every record is SYNTHETIC. Passing shows these paths on this machine, not on a clean one.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import http.cookiejar
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from ctypes import wintypes
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "tests" / "support")]
from helpers import make_pdf  # noqa: E402  (pure Python, no package import)

HERE = Path(__file__).resolve().parent
OWNER_PORT = 8765
LEFT_LIMIT = 15.0
QUESTION = "How is molecule release scheduling optimized in SYNTHETIC diffusion channels?"
INSTALL = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "DEIXIS"
DEFAULT_LIBRARY = Path(os.environ["LOCALAPPDATA"]) / "DEIXIS"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\DEIXIS"
MANUAL = "manual"
# Programs DEIXIS or its stand-ins run: a new orphan running one of these is never "not related".
GENERIC = ("python", "pythonw", "node", "cmd", "deixis-backend", "deixis-desktop", "msedgewebview2", "codex", "tesseract")
LIBRARY_FILES = ("library.sqlite", "library.sqlite-wal", "library.sqlite-shm", "library.lock", "desktop-port.json",
                 str(Path("logs") / "backend.log"))
results: dict[str, dict] = {}

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32")
rstrtmgr = ctypes.WinDLL("rstrtmgr")
user32.SetProcessDPIAware()  # window rectangles in real pixels, as PowerShell's capture sees them


def row(name: str, ok: bool | None | str, **facts) -> None:
    results[name] = {"ok": ok, **facts}
    word = "MANUAL" if ok == MANUAL else "NOT_DONE" if ok is None else "PASS" if ok else "FAIL"
    print(f"{word} {name} {json.dumps(facts, default=str)}", flush=True)


def free_port() -> int:
    while True:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        if port != OWNER_PORT:
            return port


def wait_for(check, seconds: float, step: float = 0.2):
    ends = time.monotonic() + seconds
    while time.monotonic() < ends:
        if (value := check()):
            return value
        time.sleep(step)
    return None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def folder_size(path: Path) -> tuple[int, int]:
    files = [p for p in path.rglob("*") if p.is_file()]
    return len(files), sum(p.stat().st_size for p in files)


# ---------------------------------------------------------------------------------------------------- PowerShell ---

POWERSHELL_ERRORS: list[str] = []


def powershell(script: str, timeout: float = 120) -> str:
    """Its stdout; stderr (progress records, errors) is kept in POWERSHELL_ERRORS for the evidence."""
    prelude = "[Console]::OutputEncoding = [Text.Encoding]::UTF8\n$ProgressPreference = 'SilentlyContinue'\n"
    encoded = base64.b64encode((prelude + script).encode("utf-16-le")).decode()
    done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand",
                           encoded], capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)
    if done.stderr.strip() and "<Objs" not in done.stderr[:200]:
        POWERSHELL_ERRORS.append(done.stderr.strip()[-600:])
    return done.stdout.strip()


def last_json(text: str):
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith(("{", "[")):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return None


CIM = ("Get-CimInstance Win32_Process | ForEach-Object { [pscustomobject]@{ pid = $_.ProcessId; ppid = $_.ParentProcessId; "
       "t = $(if ($_.CreationDate) { [int64]($_.CreationDate.ToFileTimeUtc() / 10) } else { 0 }); name = $_.Name; "
       "cmd = $_.CommandLine } } | ConvertTo-Json -Compress")


def cim_table() -> dict[str, dict]:
    """Every process: "pid:creation-µs" -> pid, ppid, creation time (µs since 1601 UTC), name, command line."""
    found = last_json(powershell(CIM)) or []
    return {f"{p['pid']}:{p['t']}": {"pid": p["pid"], "ppid": p["ppid"], "t": p["t"], "name": p["name"] or "",
                                     "cmd": p["cmd"] or ""} for p in found}


def cim_command_lines(name: str) -> list[str]:
    found = last_json(powershell(f"@(Get-CimInstance Win32_Process -Filter \"Name='{name}'\" | "
                                 "ForEach-Object { [string]$_.CommandLine }) | ConvertTo-Json -Compress")) or []
    return [found] if isinstance(found, str) else found


# --------------------------------------------------------------------------------------------- Win32 (processes) ---

class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260)]


kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.OpenProcess.restype = wintypes.HANDLE
PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_TERMINATE, SYNCHRONIZE = 0x1000, 0x0001, 0x00100000
_info_cache: dict[int, tuple[int | None, str]] = {}


def process_info(pid: int) -> tuple[int | None, str]:
    """(creation time in µs since 1601 UTC, image path) of a live process; (None, "") when it cannot be opened."""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None, ""
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        ok = kernel32.GetProcessTimes(handle, *[ctypes.byref(t) for t in times])
        created = ((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime) // 10 if ok else None
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(1024)
        path = buffer.value if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)) else ""
        return created, path
    finally:
        kernel32.CloseHandle(handle)


ntdll = ctypes.WinDLL("ntdll")


def command_line(pid: int) -> str:
    """A live process's command line (NtQueryInformationProcess, ProcessCommandLineInformation): fast, unlike CIM."""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buffer = ctypes.create_string_buffer(1 << 16)
        size = wintypes.ULONG()
        if ntdll.NtQueryInformationProcess(wintypes.HANDLE(handle), 60, buffer, len(buffer), ctypes.byref(size)) != 0:
            return ""
        length = struct.unpack_from("<H", buffer.raw, 0)[0]
        address = struct.unpack_from("<Q", buffer.raw, 8)[0]
        return ctypes.wstring_at(address, length // 2)
    finally:
        kernel32.CloseHandle(handle)


def fast_table() -> dict[str, dict]:
    """Every process through Toolhelp32 (fast enough for a 0.2 s watch): "pid:creation-µs" -> pid, ppid, t, name, path."""
    snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    raw = []
    try:
        more = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while more:
            raw.append((entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile))
            more = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    found = {}
    live = {pid for pid, _, _ in raw}
    for gone in set(_info_cache) - live:
        _info_cache.pop(gone, None)
    for pid, ppid, name in raw:
        if pid not in _info_cache or _info_cache[pid][0] is None:
            _info_cache[pid] = process_info(pid)
        created, path = _info_cache[pid]
        found[f"{pid}:{created}"] = {"pid": pid, "ppid": ppid, "t": created, "name": name, "path": path}
    return found


def same_process(ident: str, table: dict[str, dict]) -> bool:
    """`ident` (pid:µs) is alive in `table`; creation times from CIM and GetProcessTimes may differ by a µs."""
    pid, _, created = ident.partition(":")
    if ident in table:
        return True
    if created in ("None", ""):
        return False
    return any(p["pid"] == int(pid) and p["t"] is not None and abs(p["t"] - int(created)) <= 2 for p in table.values())


def terminate(pid: int) -> bool:
    handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not handle:
        return False
    try:
        return bool(kernel32.TerminateProcess(handle, 1))
    finally:
        kernel32.CloseHandle(handle)


def elevated() -> bool:
    return bool(shell32.IsUserAnAdmin())


# ----------------------------------------------------------------------------------------------- Win32 (windows) ---

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
WM_CLOSE = 0x0010


def windows_of(pid: int) -> list[dict]:
    """Top-level windows titled DEIXIS owned by `pid`."""
    found = []

    def visit(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title, 256)
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            if title.value == "DEIXIS":
                rect = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                found.append({"hwnd": hwnd, "class": cls.value, "visible": bool(user32.IsWindowVisible(hwnd)),
                              "minimized": bool(user32.IsIconic(hwnd)),
                              "rect": [rect.left, rect.top, rect.right, rect.bottom],
                              "foreground": user32.GetForegroundWindow() == hwnd})
        return True

    user32.EnumWindows(WNDENUMPROC(visit), 0)
    found.sort(key=lambda w: (w["rect"][2] - w["rect"][0]) * (w["rect"][3] - w["rect"][1]), reverse=True)
    return found


def main_window(pid: int) -> dict | None:
    found = windows_of(pid)
    return found[0] if found else None


def screenshot(hwnd: int, out: Path) -> dict:
    """The window as drawn (PrintWindow with PW_RENDERFULLCONTENT, so WebView2 content is in it even when covered)."""
    script = rf"""
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System; using System.Runtime.InteropServices;
public static class Shot {{
  [StructLayout(LayoutKind.Sequential)] public struct RECT {{ public int Left, Top, Right, Bottom; }}
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
}}
'@
[Shot]::SetProcessDPIAware() | Out-Null
$h = [IntPtr]{hwnd}
$r = New-Object Shot+RECT
[Shot]::GetWindowRect($h, [ref]$r) | Out-Null
$w = $r.Right - $r.Left; $hh = $r.Bottom - $r.Top
$bmp = New-Object System.Drawing.Bitmap $w, $hh
$g = [System.Drawing.Graphics]::FromImage($bmp)
$dc = $g.GetHdc(); $ok = [Shot]::PrintWindow($h, $dc, 2); $g.ReleaseHdc($dc)
$bmp.Save('{out}', [System.Drawing.Imaging.ImageFormat]::Png)
@{{ ok = $ok; width = $w; height = $hh }} | ConvertTo-Json -Compress
"""
    said = powershell(script)
    return (last_json(said) or {"said": said[-300:]}) | {"file": out.name, "saved": out.exists()}


# ------------------------------------------------------------------------------------------------ other Win32 ---

class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


def downloads_folder() -> Path:
    raw = uuid.UUID("374DE290-123F-4565-9164-39C4925E467B").bytes_le
    guid = GUID.from_buffer_copy(raw)
    path = ctypes.c_wchar_p()
    if shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(path)) != 0:
        raise OSError("SHGetKnownFolderPath(Downloads) failed")
    try:
        return Path(path.value)
    finally:
        ole32.CoTaskMemFree(path)


class RM_UNIQUE_PROCESS(ctypes.Structure):
    _fields_ = [("dwProcessId", wintypes.DWORD), ("ProcessStartTime", wintypes.FILETIME)]


class RM_PROCESS_INFO(ctypes.Structure):
    _fields_ = [("Process", RM_UNIQUE_PROCESS), ("strAppName", wintypes.WCHAR * 256),
                ("strServiceShortName", wintypes.WCHAR * 64), ("ApplicationType", ctypes.c_int),
                ("AppStatus", wintypes.ULONG), ("TSSessionId", wintypes.DWORD), ("bRestartable", wintypes.BOOL)]


def holders(files: list[Path]) -> dict:
    """Processes holding any of `files` open, by the Restart Manager (RmGetList); CIM shows no handles."""
    files = [str(f) for f in files if f.exists()]
    if not files:
        return {"files": 0, "holders": []}
    session = wintypes.DWORD()
    key = ctypes.create_unicode_buffer(64)
    err = rstrtmgr.RmStartSession(ctypes.byref(session), 0, key)
    if err:
        return {"error": f"RmStartSession {err}"}
    try:
        names = (ctypes.c_wchar_p * len(files))(*files)
        err = rstrtmgr.RmRegisterResources(session, len(files), names, 0, None, 0, None)
        if err:
            return {"error": f"RmRegisterResources {err}"}
        needed, count, reasons = wintypes.UINT(0), wintypes.UINT(0), wintypes.DWORD()
        err = rstrtmgr.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), None, ctypes.byref(reasons))
        found = []
        if err == 234 and needed.value:  # ERROR_MORE_DATA
            infos = (RM_PROCESS_INFO * needed.value)()
            count = wintypes.UINT(needed.value)
            err = rstrtmgr.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), infos, ctypes.byref(reasons))
            found = [{"pid": i.Process.dwProcessId, "app": i.strAppName} for i in infos[:count.value]]
        return {"files": len(files), "holders": found} | ({"error": f"RmGetList {err}"} if err else {})
    finally:
        rstrtmgr.RmEndSession(session)


# ------------------------------------------------------------------------------------------------------- HTTP ---

class Http:
    """The backend's API as the page uses it: the session cookie and the CSRF header; never through a proxy."""

    def __init__(self, port: int):
        self.base = f"http://127.0.0.1:{port}"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                  urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.headers: dict[str, str] = {}

    def call(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None,
             timeout: float = 60) -> tuple[int, bytes]:
        request = urllib.request.Request(self.base + path, data=body, method=method,
                                         headers=self.headers | (headers or {}))
        try:
            with self.opener.open(request, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()
        except OSError as error:
            return 0, str(error).encode()

    def json(self, method: str, path: str, payload=None, **kw) -> tuple[int, dict]:
        body = None if payload is None else json.dumps(payload).encode()
        status, raw = self.call(method, path, body, {"Content-Type": "application/json"} if body else None, **kw)
        try:
            return status, json.loads(raw or b"null")
        except ValueError:
            return status, {"raw": raw[:300].decode(errors="replace")}

    def login(self) -> None:
        _, session = self.json("GET", "/api/session")
        self.headers["x-deixis-csrf"] = session["csrf_token"]

    def upload(self, path: str, name: str, data: bytes, timeout: float = 120) -> tuple[int, dict]:
        boundary = "SYNTHETIC" + os.urandom(8).hex()
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
                "Content-Type: application/pdf\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
        status, raw = self.call("POST", path, body, {"Content-Type": f"multipart/form-data; boundary={boundary}"},
                                timeout=timeout)
        try:
            return status, json.loads(raw)
        except ValueError:
            return status, {}


def health(port: int, timeout: float = 2) -> dict | None:
    status, body = Http(port).json("GET", "/api/health", timeout=timeout)
    return body if status == 200 else None


# ------------------------------------------------------------------------------- WebView2 DevTools protocol ---

class Cdp:
    """A minimal DevTools client over WebSocket (RFC 6455) to the window's page target."""

    def __init__(self, port: int):
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                f"http://127.0.0.1:{port}/json/list", timeout=5) as response:
            targets = json.loads(response.read())
        pages = [t for t in targets if t.get("type") == "page"]
        if not pages:
            raise OSError(f"no page target among {len(targets)}")
        self.target = pages[0]
        url = self.target["webSocketDebuggerUrl"]
        host_port, _, path = url.removeprefix("ws://").partition("/")
        host, _, wport = host_port.partition(":")
        self.sock = socket.create_connection((host, int(wport)), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET /{path} HTTP/1.1\r\nHost: {host_port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(1)
            if not chunk:
                raise OSError("DevTools closed the handshake")
            head += chunk
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise OSError(f"DevTools handshake: {head[:80]!r}")
        self.next_id = 0

    def _exact(self, size: int) -> bytes:
        out = b""
        while len(out) < size:
            chunk = self.sock.recv(size - len(out))
            if not chunk:
                raise OSError("DevTools connection closed")
            out += chunk
        return out

    def _send(self, text: str, opcode: int = 0x1) -> None:
        data = text.encode()
        mask = os.urandom(4)
        size = len(data)
        head = bytes([0x80 | opcode]) + (bytes([0x80 | size]) if size < 126 else
                                         bytes([0x80 | 126]) + struct.pack(">H", size) if size < 65536 else
                                         bytes([0x80 | 127]) + struct.pack(">Q", size))
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _message(self) -> str:
        parts = b""
        while True:
            first, second = self._exact(2)
            size = second & 0x7F
            if size == 126:
                size = struct.unpack(">H", self._exact(2))[0]
            elif size == 127:
                size = struct.unpack(">Q", self._exact(8))[0]
            payload = self._exact(size)
            opcode = first & 0x0F
            if opcode == 0x9:
                self._send(payload.decode(errors="replace"), 0xA)
                continue
            if opcode == 0x8:
                raise OSError("DevTools closed the connection")
            parts += payload
            if first & 0x80:
                return parts.decode(errors="replace")

    def call(self, method: str, **params):
        self.next_id += 1
        mine = self.next_id
        self._send(json.dumps({"id": mine, "method": method, "params": params}))
        while True:
            message = json.loads(self._message())
            if message.get("id") == mine:
                if "error" in message:
                    raise OSError(f"{method}: {message['error']}")
                return message.get("result", {})

    def eval(self, expression: str):
        result = self.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        return result.get("result", {}).get("value")

    def url(self) -> str:
        return self.eval("location.href") or ""

    def text(self) -> str:
        return self.eval("document.body ? document.body.innerText : ''") or ""

    FIND = """((want, exact) => {
      const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
      const seen = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
      const hit = e => { const a = norm(e.getAttribute('aria-label')), x = norm(e.innerText);
        return exact ? (a === want || x === want) : (a.includes(want) || x.includes(want)); };
      const all = [...document.querySelectorAll('button,a,[role=button],[role=menuitem],[role=option],[role=tab],[role=link],[role=row],li,[tabindex]')];
      const found = all.filter(e => seen(e) && hit(e) && !e.disabled)
        .sort((a, b) => norm(a.innerText).length - norm(b.innerText).length)[0];
      if (!found) return null;
      found.scrollIntoView({block: 'center'});
      const r = found.getBoundingClientRect();
      return {x: r.left + r.width / 2, y: r.top + r.height / 2, tag: found.tagName, text: norm(found.innerText).slice(0, 80),
              label: found.getAttribute('aria-label')};
    })(%s, %s)"""

    def click(self, want: str, exact: bool = False) -> dict | None:
        """A real mouse click (pointer, mouse and click events) at the centre of the element showing `want`."""
        found = self.eval(self.FIND % (json.dumps(want), "true" if exact else "false"))
        if not found:
            return None
        for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
            self.call("Input.dispatchMouseEvent", type=kind, x=found["x"], y=found["y"], button="left",
                      clickCount=0 if kind == "mouseMoved" else 1)
        return found

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def cdp_connect(port: int, seconds: float = 30) -> tuple[Cdp | None, str]:
    error = ""
    ends = time.monotonic() + seconds
    while time.monotonic() < ends:
        try:
            return Cdp(port), ""
        except (OSError, ValueError, KeyError) as exc:
            error = str(exc)
            time.sleep(0.5)
    return None, error or "no answer"


# ------------------------------------------------------------------------------------------- UI Automation ---

class NOTIFYICONIDENTIFIER(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT), ("guidItem", GUID)]


user32.FindWindowExW.restype = wintypes.HWND
user32.FindWindowExW.argtypes = (wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR)
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.GetMenuItemRect.argtypes = (wintypes.HWND, wintypes.HMENU, wintypes.UINT, ctypes.POINTER(wintypes.RECT))
user32.GetMenuStringW.argtypes = (wintypes.HMENU, wintypes.UINT, wintypes.LPWSTR, ctypes.c_int, wintypes.UINT)
shell32.Shell_NotifyIconGetRect.argtypes = (ctypes.POINTER(NOTIFYICONIDENTIFIER), ctypes.POINTER(wintypes.RECT))
HWND_MESSAGE, MN_GETHMENU, MF_BYPOSITION = wintypes.HWND(-3), 0x01E1, 0x400


def click_at(x: int, y: int) -> None:
    """A real left click (the cursor moves there): the shell sends the icon its mouse messages."""
    user32.SetCursorPos(x, y)
    time.sleep(0.1)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


def icon_rect(pid: int) -> tuple[list[int], int, int] | None:
    """The notification icon of `pid` (Shell_NotifyIconGetRect over its windows, message-only ones included, and
    the first icon ids); UI Automation does not list the Windows 11 overflow's icons."""
    owned = []
    for parent in (HWND_MESSAGE, None):
        child = None
        while (child := user32.FindWindowExW(parent, child, None, None)):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(child, ctypes.byref(owner))
            if owner.value == pid:
                owned.append(child)
    for hwnd in owned:
        for uid in range(0, 16):
            nid = NOTIFYICONIDENTIFIER(cbSize=ctypes.sizeof(NOTIFYICONIDENTIFIER), hWnd=hwnd, uID=uid)
            rect = wintypes.RECT()
            if shell32.Shell_NotifyIconGetRect(ctypes.byref(nid), ctypes.byref(rect)) == 0:
                return [rect.left, rect.top, rect.right, rect.bottom], hwnd, uid
    return None


def window_rect(hwnd) -> list[int]:
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return [rect.left, rect.top, rect.right, rect.bottom]


def tray(pid: int, quit_now: bool) -> dict:
    """Open the tray icon's menu with a real click (from the overflow when the icon is hidden there), read its items
    and either choose Quit DEIXIS or close the menu with Escape."""
    out: dict = {"icon": None, "where": None, "menu": [], "quit": False}
    found = icon_rect(pid)
    if not found:
        return out | {"reason": "no notification icon of the shell found"}
    rect, _hwnd, uid = found
    taskbar = user32.FindWindowExW(None, None, "Shell_TrayWnd", None)
    bar = window_rect(taskbar) if taskbar else [0, 0, 0, 0]
    inside = bar[1] <= (rect[1] + rect[3]) // 2 <= bar[3] and bar[0] <= (rect[0] + rect[2]) // 2 <= bar[2]
    overflow = user32.FindWindowExW(None, None, "NotifyIconOverflowWindow", None)
    if not inside and not (overflow and user32.IsWindowVisible(overflow)):
        notify = user32.FindWindowExW(taskbar, None, "TrayNotifyWnd", None)
        chevron = user32.FindWindowExW(notify, None, "Button", None) if notify else None
        if chevron:
            c = window_rect(chevron)
            click_at((c[0] + c[2]) // 2, (c[1] + c[3]) // 2)
            time.sleep(1.0)
            rect, _hwnd, uid = icon_rect(pid) or (rect, None, uid)
    out |= {"icon": rect, "uid": uid, "where": "taskbar" if inside else "overflow"}
    click_at((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)
    menu_window = wait_for(lambda: user32.FindWindowExW(None, None, "#32768", None), 5, 0.1)
    if not menu_window:
        return out | {"reason": "no popup menu after the click"}
    hmenu = user32.SendMessageW(menu_window, MN_GETHMENU, 0, 0)
    for index in range(user32.GetMenuItemCount(wintypes.HMENU(hmenu))):
        text = ctypes.create_unicode_buffer(128)
        user32.GetMenuStringW(wintypes.HMENU(hmenu), index, text, 128, MF_BYPOSITION)
        out["menu"].append(text.value)
    if quit_now and "Quit DEIXIS" in out["menu"]:
        item = wintypes.RECT()
        user32.GetMenuItemRect(None, wintypes.HMENU(hmenu), out["menu"].index("Quit DEIXIS"), ctypes.byref(item))
        click_at((item.left + item.right) // 2, (item.top + item.bottom) // 2)
        out["quit"] = True
    else:
        user32.keybd_event(0x1B, 0, 0, 0)
        user32.keybd_event(0x1B, 0, 2, 0)
    return out


# --------------------------------------------------------------------------------------------------- scenario ---

class Watcher:
    """Samples the process table every 0.2 s for the whole scenario and keeps every DEIXIS process it sees."""

    def __init__(self, marks: list[str]):
        self.marks = [m.lower() for m in marks]
        self.roots: set[int] = set()
        self.seen: dict[str, dict] = {}
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def sample(self) -> None:
        procs = fast_table()
        changed = True
        while changed:
            changed = False
            parents = {p["pid"]: p["t"] for i, p in self.seen.items() if i in procs}
            for ident, proc in procs.items():
                if ident in self.seen or proc["pid"] == os.getpid():
                    continue
                child = proc["ppid"] in parents and (proc["t"] or 0) >= (parents[proc["ppid"]] or 0)
                if proc["pid"] in self.roots or child or any(m in proc["path"].lower() for m in self.marks):
                    self.seen[ident] = proc
                    changed = True

    def run(self) -> None:
        while not self.stop.is_set():
            self.sample()
            self.stop.wait(0.2)

    def alive(self) -> list[dict]:
        now = fast_table()
        return [self.seen[i] | {"ident": i} for i in self.seen if i in now]

    def close(self) -> None:
        self.stop.set()
        if self.thread.is_alive():
            self.thread.join(2)


class Scenario:
    """One launch of the installed app with its own data folder."""

    def __init__(self, work: Path, env: dict[str, str], name: str):
        self.name, self.work = name, work
        self.data = work / f"data-{name}"
        self.data.mkdir()
        self.saved_port = free_port()
        (self.data / "desktop-port.json").write_text(json.dumps({"port": self.saved_port}))
        self.cdp_port = free_port()
        self.env = env | {"DEIXIS_DATA_DIR": str(self.data), "DEIXIS_PORT": str(free_port()),
                          "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": f"--remote-debugging-port={self.cdp_port}"}
        self.before = cim_table()
        self.watch = Watcher([str(INSTALL), str(work / "bin")])
        self.proc: subprocess.Popen | None = None
        self.started = 0.0
        self.port: int | None = None
        self.api: Http | None = None
        self.cdp: Cdp | None = None
        self.cdp_error = ""

    @property
    def exe(self) -> Path:
        return INSTALL / "deixis-desktop.exe"

    def launch(self) -> None:
        self.started = time.monotonic()
        self.proc = subprocess.Popen([str(self.exe)], env=self.env, cwd=str(self.work), stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL,
                                     stderr=open(self.work / f"shell-{self.name}.err", "wb"),
                                     creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        self.watch.roots.add(self.proc.pid)
        self.watch.thread.start()

    def read_port(self) -> int | None:
        try:
            return json.loads((self.data / "desktop-port.json").read_text(encoding="utf-8")).get("port")
        except (OSError, ValueError):
            return None

    def wait_health(self, seconds: float = 60, since: float | None = None) -> tuple[float | None, dict | None]:
        ends = (self.started if since is None else since) + seconds
        while time.monotonic() < ends:
            port = self.read_port()
            if port and (body := health(port)) is not None:
                self.port = port
                self.api = Http(port)
                return time.monotonic() - (self.started if since is None else since), body
            time.sleep(0.1)
        return None, None

    def session(self) -> Http:
        if not self.api.headers:
            self.api.login()
        return self.api

    def connect(self) -> Cdp | None:
        if self.cdp is None:
            self.cdp, self.cdp_error = cdp_connect(self.cdp_port)
        return self.cdp

    def backend_pids(self) -> list[int]:
        """The serving backend: deixis-backend.exe started by the shell (its own children are deixis-backend.exe too)."""
        return [p["pid"] for p in fast_table().values() if p["name"].lower() == "deixis-backend.exe"
                and p["ppid"] == self.proc.pid and p["path"].lower().startswith(str(INSTALL).lower())]

    def family(self) -> list[int]:
        return sorted(p["pid"] for p in self.watch.alive())

    def check_left(self, trigger: float) -> dict:
        """Within 15 s of `trigger` nothing of this scenario may be alive; then the handle and snapshot checks."""
        while time.monotonic() < trigger + LEFT_LIMIT and self.watch.alive():
            time.sleep(0.2)
        gone_s = time.monotonic() - trigger
        left = self.watch.alive()
        self.watch.close()
        time.sleep(max(0.0, trigger + LEFT_LIMIT - time.monotonic()))
        held = holders([self.data / f for f in LIBRARY_FILES])
        after = cim_table()
        mine = os.getpid()
        seen_pids = {p["pid"] for p in self.watch.seen.values()}
        explained, unexplained = [], []
        for ident, proc in after.items():
            if same_process(ident, self.before):
                continue
            cmd = proc["cmd"].lower()
            exe = Path(proc["name"]).stem.lower()
            parent_alive = any(p["pid"] == proc["ppid"] and p["t"] <= proc["t"] for p in after.values())
            if any(same_process(i, {ident: proc}) for i in self.watch.seen):
                unexplained.append(proc | {"why": "seen as DEIXIS of this scenario"})
            elif proc["pid"] == mine or proc["ppid"] == mine:
                explained.append(f"{proc['pid']} this acceptance script's own child: {proc['cmd'][:80]}")
            elif str(self.data).lower() in cmd or str(INSTALL).lower() in cmd or str(self.work / "bin").lower() in cmd:
                unexplained.append(proc | {"why": "names this scenario's folders or the install folder"})
            elif proc["ppid"] in seen_pids:
                unexplained.append(proc | {"why": "its parent pid was a DEIXIS process of this scenario"})
            elif not parent_alive and exe in GENERIC:
                unexplained.append(proc | {"why": "an orphan running a program DEIXIS runs"})
            else:
                parent = next((p["name"] for p in after.values() if p["pid"] == proc["ppid"]), "gone")
                explained.append(f"{proc['pid']} {proc['name']} (parent {proc['ppid']} {parent}) not related (no "
                                 f"ancestry or folder): {proc['cmd'][:90]}")
        return {"ok": not left and not held.get("holders") and not held.get("error") and not unexplained,
                "all_gone_s": round(gone_s, 2), "seen": len(self.watch.seen),
                "seen_names": sorted({p["name"] for p in self.watch.seen.values()}),
                "left": [f"{p['pid']} {p['name']}" for p in left], "open_handles": held,
                "unexplained": unexplained[:5], "new_processes_explained": explained[:15]}

    def kill_all(self) -> None:
        """Cleanup after a failure: only what this scenario started."""
        for proc in self.watch.alive():
            terminate(proc["pid"])
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
        self.watch.close()
        if self.cdp:
            self.cdp.close()


# ----------------------------------------------------------------------------------------------------- load ---

def fake_codex(bin_dir: Path, python: str) -> None:
    """The fake codex laid out as an npm global install (`tool_paths._windows_command` runs node on the entry script
    its `codex.cmd` names); the Node script runs fake_codex.py with `python`, stdio passed through. A turn hangs
    unless `no-hang` exists next to it (the download row needs a finished answer)."""
    entry = bin_dir / "node_modules" / "@fake" / "codex" / "bin" / "codex.js"
    entry.parent.mkdir(parents=True)
    (bin_dir / "codex.cmd").write_text(
        '@ECHO off\r\nSETLOCAL\r\nSET dp0=%~dp0\r\nSET "_prog=node"\r\n'
        'endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  "%dp0%\\node_modules\\@fake\\codex\\bin\\codex.js" %*\r\n')
    script = REPO / "scripts" / "p10" / "fake_codex.py"
    # fake_codex.py records os.getpgrp() in its hang marker; Windows has no process groups of that kind.
    runner = ("import os, runpy, sys; os.getpgrp = getattr(os, 'getpgrp', lambda: 0); "
              f"sys.argv = [{str(script)!r}] + sys.argv[1:]; runpy.run_path({str(script)!r}, run_name='__main__')")
    entry.write_text(
        "const fs = require('fs');\nconst { spawnSync } = require('child_process');\n"
        f"const env = {{ ...process.env, _FAKE_CODEX_DIR: {json.dumps(str(bin_dir))} }};\n"
        f"if (!fs.existsSync({json.dumps(str(bin_dir / 'no-hang'))})) env._FAKE_CODEX_HANG = '1';\n"
        f"const done = spawnSync({json.dumps(python)}, ['-c', {json.dumps(runner)}, ...process.argv.slice(2)],\n"
        "  { stdio: 'inherit', env });\n"
        "process.exit(done.status === null ? 1 : done.status);\n")


def new_research(api: Http, tag: str) -> str | None:
    status, made = api.json("POST", "/api/researches", {
        "question": f"{QUESTION} ({tag})", "source_scope": "attached", "effort": "quick", "model_connection": "codex",
        "requested_model": "gpt-fake", "reasoning_effort": "medium"})
    return made["research"]["id"] if status == 201 else None


def start_load(sc: Scenario, bin_dir: Path) -> dict:
    """A hanging fake-codex answer, then a long PDF upload whose extraction child is running."""
    for marker in bin_dir.glob("*.json"):
        marker.unlink()
    api = sc.session()
    facts: dict = {}
    rid = new_research(api, f"{sc.name} answer")
    if rid:
        api.upload(f"/api/researches/{rid}/uploads", "synthetic.pdf",
                   make_pdf([f"SYNTHETIC page: a bounded molecule release schedule ({sc.name})."]))
        facts["answer_run"] = api.json("POST", f"/api/researches/{rid}/runs", {"kind": "answer"})[0]
    facts["codex_hanging"] = bool(wait_for(lambda: (bin_dir / "codex-hang.json").exists(), 120, 0.5))
    pid_rid = new_research(api, f"{sc.name} pdf")
    pages = [f"SYNTHETIC page {i}: " + "a bounded molecule release schedule minimizes error. " * 40 for i in range(4000)]
    pdf = make_pdf(pages)
    facts["pdf_mb"] = round(len(pdf) / 1e6, 1)
    serve = set(sc.backend_pids())
    threading.Thread(target=lambda: sc_upload(sc, pid_rid, pdf), daemon=True).start()
    # The extraction child, seen by the fast table (parent = the serving backend) and named by its command line, so
    # the trigger comes while it runs.
    asked: dict[int, str] = {}

    def extraction():
        for proc in fast_table().values():
            if proc["name"].lower() == "deixis-backend.exe" and proc["ppid"] in serve:
                asked.setdefault(proc["pid"], command_line(proc["pid"]))
                if "deixis.documents.pdf" in asked[proc["pid"]]:
                    return proc["pid"]
        return None
    child = wait_for(extraction, 120, 0.05)
    facts["pdf_child_running"] = bool(child)
    facts["pdf_child"] = asked.get(child, "").split(".exe", 1)[-1].strip()[:80] if child else None
    facts["other_backend_children"] = [c.split(".exe", 1)[-1].strip()[:60] for pid, c in asked.items() if pid != child]
    facts["hanging"] = facts["codex_hanging"] and facts["pdf_child_running"]
    facts["load_processes"] = sorted(p["name"] for p in sc.watch.alive())
    return facts


def sc_upload(sc: Scenario, rid: str | None, pdf: bytes) -> None:
    if rid:
        api = Http(sc.port)
        api.login()
        api.upload(f"/api/researches/{rid}/uploads", "synthetic-long.pdf", pdf, timeout=600)


def quit_app(sc: Scenario, use_tray: bool) -> dict:
    """The shell's quit(): the tray menu's Quit when it opened in the tray row, else the local page's Quit link."""
    said = None
    if use_tray:
        said = tray(sc.proc.pid, quit_now=True)
        if said.get("quit"):
            return {"quit_via": "tray menu Quit DEIXIS (real clicks on the icon and the item)", "tray": said}
    cdp = sc.connect()
    if said is not None:
        print(f"     tray quit not reached, local page instead: {json.dumps(said)}", flush=True)
    if cdp is None:
        return {"quit_via": None, "error": f"no DevTools: {sc.cdp_error}"}
    try:
        cdp.call("Page.navigate", url="http://tauri.localhost/index.html?state=stopped")
        shown = wait_for(lambda: cdp.url().startswith("http://tauri.localhost/index.html") and cdp.click("Quit", True), 15, 0.5)
        return {"quit_via": "local page Quit link (/action/quit -> quit())", "clicked": bool(shown)}
    except OSError as error:
        return {"quit_via": "local page Quit link", "error": str(error)}


# ------------------------------------------------------------------------------------------------------ main ---

def install_row(installer: Path, evidence: Path) -> bool:
    if INSTALL.exists():
        row("install", False, reason=f"{INSTALL} exists before the install: uninstall it first")
        return False
    consent: list[str] = []
    stop = threading.Event()

    def watch_consent():
        while not stop.is_set():
            consent.extend(p["name"] for p in fast_table().values() if p["name"].lower() == "consent.exe")
            stop.wait(0.2)
    threading.Thread(target=watch_consent, daemon=True).start()
    started = time.monotonic()
    done = subprocess.run([str(installer), "/S"], capture_output=True, timeout=300)
    seconds = time.monotonic() - started
    stop.set()
    need = [INSTALL / "deixis-desktop.exe", INSTALL / "sidecar" / "deixis-backend" / "deixis-backend.exe",
            INSTALL / "uninstall.exe"]
    files, size = folder_size(INSTALL) if INSTALL.exists() else (0, 0)
    registered = powershell(f"(Get-ItemProperty 'HKCU:\\{UNINSTALL_KEY}' -ErrorAction SilentlyContinue).InstallLocation")
    machine = powershell(f"Test-Path 'HKLM:\\{UNINSTALL_KEY}'")
    inside_library = INSTALL.resolve().is_relative_to(DEFAULT_LIBRARY.resolve())
    ok = (done.returncode == 0 and not consent and all(p.is_file() for p in need) and not inside_library
          and str(INSTALL).lower() in registered.lower() and machine.strip().lower() == "false")
    row("install", ok, installer=installer.name, installer_mb=round(installer.stat().st_size / 1e6, 1),
        installer_sha256=sha256(installer), exit=done.returncode, seconds=round(seconds, 1), elevated=elevated(),
        consent_seen=sorted(set(consent)), install_dir=str(INSTALL), files=files, installed_mb=round(size / 1e6, 1),
        missing=[str(p) for p in need if not p.is_file()], hkcu_install_location=registered.strip(),
        hklm_entry=machine.strip(), inside_library_folder=inside_library,
        desktop_sha256=sha256(need[0]) if need[0].is_file() else None)
    (evidence / "installed-files.txt").write_text("\n".join(
        f"{p.relative_to(INSTALL)}\t{p.stat().st_size}" for p in sorted(INSTALL.rglob("*")) if p.is_file()),
        encoding="utf-8") if INSTALL.exists() else None
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, default=None)
    parser.add_argument("--only", default="", help="comma-separated rows to run (install and uninstall always run)")
    parser.add_argument("--fake-python", default=sys.executable)
    parser.add_argument("--keep-installed", action="store_true")
    args = parser.parse_args()
    only = {r for r in args.only.split(",") if r}
    wanted = lambda name: not only or name in only  # noqa: E731
    work = Path(tempfile.mkdtemp(prefix="deixis-win-acceptance-"))
    evidence = (args.evidence or work / "evidence").resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    scenarios: list[Scenario] = []
    print(json.dumps({"work": str(work), "evidence": str(evidence), "python": sys.version.split()[0],
                      "machine": os.environ.get("PROCESSOR_ARCHITECTURE"), "native": os.environ.get("PROCESSOR_ARCHITEW6432"),
                      "elevated": elevated()}), flush=True)
    try:
        if not install_row(args.installer, evidence):
            return 1
        bin_dir = work / "bin"
        bin_dir.mkdir()
        fake_codex(bin_dir, args.fake_python)
        (work / "tmp").mkdir()
        node = shutil.which("node")
        system = os.environ.get("SYSTEMROOT", r"C:\Windows")
        keep = ("SYSTEMROOT", "WINDIR", "PATHEXT", "COMSPEC", "ProgramFiles", "PROGRAMFILES", "ProgramFiles(x86)",
                "ProgramData", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "LOCALAPPDATA", "APPDATA", "USERNAME",
                "USERDOMAIN", "COMPUTERNAME", "PROCESSOR_ARCHITECTURE", "PROCESSOR_ARCHITEW6432", "NUMBER_OF_PROCESSORS",
                "OS", "PUBLIC", "SystemDrive", "ALLUSERSPROFILE")
        env = {k: os.environ[k] for k in keep if k in os.environ} | {
            "PATH": os.pathsep.join([str(bin_dir)] + ([str(Path(node).parent)] if node else [])
                                    + [f"{system}\\System32", system, f"{system}\\System32\\WindowsPowerShell\\v1.0"]),
            "TEMP": str(work / "tmp"), "TMP": str(work / "tmp"),
            "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
            "DEIXIS_DESKTOP_NO_DIALOG": "1",  # a failed start prints its message and exits; no modal on the screen
            "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9", "NO_PROXY": "127.0.0.1,localhost"}
        tray_opens = False

        def launched(name: str) -> Scenario | None:
            sc = Scenario(work, env, name)
            scenarios.append(sc)
            sc.launch()
            if sc.wait_health()[0] is None:
                row(name, False, reason="no health within 60 s", shell_exit=sc.proc.poll(),
                    shell_err=(work / f"shell-{name}.err").read_text(encoding="utf-8", errors="replace")[-600:])
                return None
            return sc

        if wanted("open"):
            sc = Scenario(work, env, "open")
            scenarios.append(sc)
            sc.launch()
            window = wait_for(lambda: (w := main_window(sc.proc.pid)) and w["visible"] and w, 60, 0.1)
            window_s = time.monotonic() - sc.started if window else None
            health_s, body = sc.wait_health()
            cdp = sc.connect() if health_s else None
            page = wait_for(lambda: cdp and cdp.url().startswith(f"http://127.0.0.1:{sc.port}/") and cdp.url(), 30, 0.5) \
                if cdp else None
            texts = wait_for(lambda: (t := cdp.text()) and all(w in t for w in ("New research", "Library", "Settings"))
                             and t, 20, 0.5) if page else None
            time.sleep(1)
            shot = screenshot(window["hwnd"], evidence / "open-window.png") if window else None
            row("open", bool(window and body and body.get("nonce") and health_s <= 60 and page and texts
                             and shot and shot.get("saved")),
                launch_to_window_s=round(window_s, 2) if window_s else None,
                launch_to_health_s=round(health_s, 2) if health_s else None, port=sc.port, saved_port=sc.saved_port,
                port_is_saved=sc.port == sc.saved_port, health_has_nonce=bool(body and body.get("nonce")),
                window={k: v for k, v in (window or {}).items() if k != "hwnd"}, page_url=page,
                research_texts=bool(texts), devtools=None if cdp else sc.cdp_error, screenshot=shot)

            if sc.api is None:
                row("csrf_save", False, reason="no backend")
            else:
                api = sc.session()
                time.sleep(2)  # the page's first-load preference fill
                before = api.json("GET", "/api/settings/preferences")[1].get("theme")
                refused = Http(sc.port).json("PUT", "/api/settings/preferences", {"theme": "dark"})[0]
                if cdp:
                    pressed = cdp.click("Switch to dark mode", True) or cdp.click("Switch to light mode", True)
                    stored = wait_for(lambda: (t := api.json("GET", "/api/settings/preferences")[1].get("theme"))
                                      not in (None, before) and t, 10, 0.5)
                    log = (sc.data / "logs" / "backend.log").read_text(encoding="utf-8", errors="replace")
                    row("csrf_save", bool(pressed and stored and refused == 403), via="click in the window (DevTools)",
                        pressed=pressed, theme_before=before, theme_stored=stored, put_without_csrf=refused,
                        put_logged='"PUT /api/settings/preferences HTTP/1.1" 200' in log)
                else:
                    want = "dark" if before != "dark" else "light"
                    saved = api.json("PUT", "/api/settings/preferences", {"theme": want})
                    row("csrf_save", None, reason=f"in-window part not done: DevTools did not answer ({sc.cdp_error})",
                        http_fallback={"put_with_csrf": saved[0], "stored": saved[1].get("theme"),
                                       "put_without_csrf": refused})

            count_before = sc.family()
            second = subprocess.run([str(sc.exe)], env=sc.env, timeout=60, capture_output=True)
            time.sleep(3)
            count_after = sc.family()
            back = main_window(sc.proc.pid)
            row("second_launch", second.returncode == 0 and count_after == count_before and bool(back and back["visible"]),
                second_exit=second.returncode, processes_before=len(count_before), processes_after=len(count_after),
                window_visible=bool(back and back["visible"]), window_foreground=bool(back and back["foreground"]))

            if back:
                user32.PostMessageW(back["hwnd"], WM_CLOSE, 0, 0)
            time.sleep(2)
            hidden = main_window(sc.proc.pid)
            healthy = sc.wait_health(5, time.monotonic())[0] is not None
            after_close = sc.family()
            subprocess.run([str(sc.exe)], env=sc.env, timeout=60, capture_output=True)  # shows the hidden window again
            reshown = wait_for(lambda: (w := main_window(sc.proc.pid)) and w["visible"], 10)
            row("close_keeps", bool(back and hidden and not hidden["visible"] and after_close == count_before and healthy),
                closed_with="WM_CLOSE", window_visible_after_close=bool(hidden and hidden["visible"]),
                processes=len(after_close), same_processes=after_close == count_before, health=healthy,
                shown_again_by_launch=bool(reshown))

            said = tray(sc.proc.pid, quit_now=False)
            tray_opens = "Quit DEIXIS" in (said.get("menu") or [])
            row("tray", True if tray_opens else MANUAL, **said,
                **({"note": "opened with a real click on the icon (Shell_NotifyIconGetRect); Quit is used by quit_plain"}
                   if tray_opens else {"note": "the tray menu did not open with a click on the icon; a person checks "
                                                "Open, the running count and Quit"}))

            facts = start_load(sc, bin_dir)
            trigger = time.monotonic()
            how = quit_app(sc, tray_opens)
            left = sc.check_left(trigger)
            row("quit_plain", left.pop("ok") and facts["hanging"] and bool(how.get("quit_via")), **how, **facts, **left,
                shell_exit=sc.proc.poll())

        if wanted("kill_shell") and (sc := launched("kill_shell")):
            facts = start_load(sc, bin_dir)
            trigger = time.monotonic()
            killed = terminate(sc.proc.pid)
            left = sc.check_left(trigger)
            row("kill_shell", left.pop("ok") and facts["hanging"] and killed, terminated=killed, **facts, **left)

        if wanted("kill_backend") and (sc := launched("kill_backend")):
            facts = start_load(sc, bin_dir)
            cdp = sc.connect()
            backend = sc.backend_pids()
            old_family = {i: p for i, p in sc.watch.seen.items()}
            trigger = time.monotonic()
            killed = len(backend) == 1 and terminate(backend[0])
            stopped_page = wait_for(lambda: cdp and "/index.html" in cdp.url() and "Restart" in cdp.text() and cdp.text(),
                                    20, 0.5) if cdp else None
            time.sleep(2)
            shell_alive = sc.proc.poll() is None
            now = fast_table()
            old_left = [f"{p['pid']} {p['name']}" for i, p in old_family.items() if i in now and p["pid"] != sc.proc.pid
                        and p["name"].lower() != "msedgewebview2.exe"]
            window = main_window(sc.proc.pid)
            shot = screenshot(window["hwnd"], evidence / "backend-stopped.png") if window else None
            pressed = cdp.click("Restart", True) if cdp and stopped_page else None
            restarted_s, _ = sc.wait_health(40, time.monotonic()) if pressed else (None, None)
            new_backend = sc.backend_pids()
            how = quit_app(sc, tray_opens)
            left = sc.check_left(time.monotonic())
            ok = bool(killed and shell_alive and stopped_page and not old_left and pressed and restarted_s
                      and new_backend and new_backend != backend and how.get("quit_via"))
            row("kill_backend", (ok and left.pop("ok") and facts["hanging"]) if cdp else None,
                **({} if cdp else {"reason": f"the stopped page and Restart need DevTools ({sc.cdp_error})"}),
                backend_killed=killed, shell_alive_after_kill=shell_alive,
                stopped_page=(stopped_page or "")[:200], old_backend_family_left=old_left, screenshot=shot,
                restart_pressed=bool(pressed), restarted_s=round(restarted_s, 2) if restarted_s else None,
                old_backend=backend, new_backend=new_backend, then_quit=how, **facts, after_quit=left)

        if wanted("download") and (sc := launched("download")):
            for marker in bin_dir.glob("*.json"):
                marker.unlink()
            (bin_dir / "no-hang").write_text("")
            downloads = downloads_folder()
            before = {p.name for p in downloads.glob("*")} if downloads.exists() else set()
            api = sc.session()
            rid = new_research(api, "download")
            api.upload(f"/api/researches/{rid}/uploads", "synthetic.pdf", make_pdf(
                ["SYNTHETIC page: a bounded molecule release schedule minimizes the decoding error."]))
            status, run = api.json("POST", f"/api/researches/{rid}/runs", {"kind": "answer"})
            finished = None
            ends = time.monotonic() + 240
            while time.monotonic() < ends:
                view = api.json("GET", f"/api/researches/{rid}")[1]
                finished = next((r for r in view.get("runs", []) if r["id"] == run.get("id")), None)
                if finished and finished["status"] in ("completed", "failed", "paused", "cancelled"):
                    break
                time.sleep(1)
            title = view["research"]["title"]
            cdp = sc.connect()
            steps: list = []
            md = csv = []
            if cdp:
                cdp.call("Page.reload")
                time.sleep(4)

                def press(text: str, exact: bool = False):
                    done = cdp.click(text, exact)
                    steps.append({"want": text, "got": done})
                    return done
                cdp.eval(f"location.hash = '#/research/{rid}'")  # the research's own route, as a link to it opens
                opened = wait_for(lambda: title[:40] in cdp.text(), 30, 1)
                time.sleep(2)
                exported = wait_for(lambda: press("Export", True), 20, 1)
                markdown = wait_for(lambda: press("Markdown"), 10, 0.5)
                fresh = lambda suffix: sorted(p for p in downloads.glob(f"*{suffix}") if p.name not in before)  # noqa: E731
                md = wait_for(lambda: fresh(".md"), 20) or []
                shell_err = work / "shell-download.err"
                said = lambda name: [ln for ln in shell_err.read_text(encoding="utf-8", errors="replace").splitlines()  # noqa: E731
                                     if ln.startswith("DEIXIS: Download") and name in ln]
                # The shell's own word on each file (WebView2's Finished event) before anything touches the file.
                wait_for(lambda: md and said(md[0].name), 20, 0.5)
                again = wait_for(lambda: press("Export", True), 10, 0.5)
                csv_pressed = wait_for(lambda: press("Comma-separated values"), 10, 0.5)
                csv = wait_for(lambda: fresh(".csv"), 20) or []
                wait_for(lambda: csv and said(csv[0].name), 20, 0.5)
                shell_says = (said(md[0].name) if md else []) + (said(csv[0].name) if csv else [])
                md_text = md[0].read_text(encoding="utf-8") if md else ""
                csv_text = csv[0].read_text(encoding="utf-8-sig") if csv else ""
                kept = []
                for path in md[:1] + csv[:1]:
                    shutil.move(str(path), evidence / f"download-{path.name}")
                    kept.append(f"download-{path.name}")
                saved_both = len(shell_says) == 2 and all("Download saved" in ln for ln in shell_says)
                row("download", bool(md and title in md_text and csv and "synthetic" in csv_text.lower() and saved_both),
                    run=(finished or {}).get("status"), title=title, opened=bool(opened), export=bool(exported),
                    markdown=bool(markdown), export_again=bool(again), csv_pressed=bool(csv_pressed),
                    downloads_folder=str(downloads), report_bytes=len(md_text), csv_lines=len(csv_text.splitlines()),
                    moved_to_evidence=kept, shell_says=shell_says, shell_saved_both=saved_both,
                    steps=steps[-4:], **({} if md and csv else {"buttons": cdp.eval(
                        "[...document.querySelectorAll('button,[role=menuitem]')].map(e => (e.getAttribute('aria-label')"
                        " || e.innerText || '').trim().slice(0, 40)).filter(Boolean).slice(0, 60)")}))
            else:
                row("download", None, reason=f"in-window export needs DevTools ({sc.cdp_error})",
                    run=(finished or {}).get("status"))
            (bin_dir / "no-hang").unlink(missing_ok=True)
            how = quit_app(sc, tray_opens)
            left = sc.check_left(time.monotonic())
            results["download"]["quit"] = how.get("quit_via")
            results["download"]["left_ok"] = left["ok"]
            if not left["ok"] and results["download"]["ok"]:
                results["download"]["ok"] = False
                print(f"     download left={json.dumps(left, default=str)}", flush=True)
    finally:
        for sc in scenarios:
            sc.kill_all()
        if INSTALL.exists() and not args.keep_installed:
            uninstall_row(work, scenarios)
        passed = sum(1 for r in results.values() if r["ok"] is True)
        summary = {"passed": passed, "failed": [n for n, r in results.items() if r["ok"] is False],
                   "not_done": [n for n, r in results.items() if r["ok"] is None],
                   "manual": [n for n, r in results.items() if r["ok"] == MANUAL]}
        print(json.dumps(summary), flush=True)
        (evidence / "results.json").write_text(json.dumps({"summary": summary, "rows": results,
                                                           "powershell_errors": POWERSHELL_ERRORS[-20:]}, indent=1, default=str),
                                               encoding="utf-8")
        for err in work.glob("shell-*.err"):
            shutil.copy(err, evidence / err.name)
        for sc in scenarios:
            log = sc.data / "logs" / "backend.log"
            if log.exists():
                shutil.copy(log, evidence / f"backend-{sc.name}.log")
        shutil.rmtree(work, ignore_errors=True)
    return 0 if results and all(r["ok"] is True or r["ok"] == MANUAL for r in results.values()) else 1


def uninstall_row(work: Path, scenarios: list[Scenario]) -> None:
    def listing(folder: Path) -> dict[str, int]:
        return {str(p.relative_to(folder)): p.stat().st_size for p in folder.rglob("*")
                if p.is_file() and p.suffix not in (".log", ".lock") and "-wal" not in p.name and "-shm" not in p.name}
    libraries = {sc.data: listing(sc.data) for sc in scenarios if sc.data.exists()}
    default_before = listing(DEFAULT_LIBRARY) if DEFAULT_LIBRARY.exists() else None
    done = subprocess.run([str(INSTALL / "uninstall.exe"), "/S"], capture_output=True, timeout=120)
    gone = wait_for(lambda: not INSTALL.exists() or not any(INSTALL.iterdir()), 60, 0.5)
    registered = powershell(f"Test-Path 'HKCU:\\{UNINSTALL_KEY}'")
    kept = {str(d.name): (d / "library.sqlite").is_file() and listing(d) == before for d, before in libraries.items()}
    default_after = listing(DEFAULT_LIBRARY) if DEFAULT_LIBRARY.exists() else None
    row("uninstall", bool(done.returncode == 0 and gone and registered.strip().lower() == "false" and all(kept.values())
                          and default_after == default_before),
        exit=done.returncode, install_folder_gone=bool(gone), install_folder_exists=INSTALL.exists(),
        hkcu_entry=registered.strip(), scenario_libraries_kept=kept,
        default_library=None if default_before is None else {"files": len(default_before),
                                                              "unchanged": default_after == default_before})


if __name__ == "__main__":
    raise SystemExit(main())
