//! The DEIXIS desktop shell (P10 M2 macOS, W4 Windows): one window, a tray item and the backend's lifetime.
//!
//! The backend ships inside the app (`sidecar/deixis-backend/` in the resource folder). On macOS the shell starts it
//! through its watchdog (`deixis-backend -m deixis.desktop_reaper`, which starts `serve --desktop`); on Windows it
//! starts `deixis-backend.exe serve --desktop` directly, created inside a kill-on-close Job Object (`win_job.rs`), so the
//! job, not a watchdog, ends the backend and its descendants when the shell goes. Either way the shell writes a fresh
//! control token as the first stdin line and keeps stdin open: EOF on that pipe tells the backend the shell is gone. The
//! first JSON line on stdout decides the start: `listening` (port, pid, nonce, data folder) or `startup_failed`; an
//! exit without a line or 30 s without one is a failed start too. Health must answer 200 with the same nonce before the
//! window leaves the local launch page for `http://127.0.0.1:<port>/`.
//!
//! Every start has a generation. The backend record, its exit watcher, the health wait and every cleanup carry it and
//! act only while it is the current one, so a stale watcher or start can never stop a newer backend after a Restart.
//!
//! No IPC: the app registers no command and grants no capability, so neither the local pages nor the backend's page
//! can call into Rust. The local pages ask for "restart" and "quit" by navigating to `/action/...`, which the
//! navigation handler below cancels and acts on, only while the window shows the local page. Links to other sites open
//! in the default browser. Downloads (the CSV and report exports, blob: links) go to the Downloads folder under a name
//! not yet taken; a failed one is said in a message.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

#[cfg(windows)]
mod win_job;

use std::collections::{HashMap, VecDeque};
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{self, Sender};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::webview::{DownloadEvent, NewWindowResponse};
use tauri::{AppHandle, Manager, RunEvent, Url, WebviewUrl, WebviewWindowBuilder, WindowEvent, Wry};
use tauri_plugin_dialog::{DialogExt, MessageDialogKind};

use platform::Sidecar;

const LISTEN_TIMEOUT: Duration = Duration::from_secs(30);
const HEALTH_TIMEOUT: Duration = Duration::from_secs(30);
const SHUTDOWN_WAIT: Duration = Duration::from_secs(8);
const STATUS_EVERY: Duration = Duration::from_secs(5);
const STDERR_LINES: usize = 40;
const MAIN: &str = "main";

struct Backend {
    generation: u64,
    sidecar: Sidecar,
    stdin: Option<Box<dyn Write + Send>>,
    token: String,
    port: Option<u16>,
    /// Health passed and the window was sent to the backend's page; an exit from now on shows "backend stopped".
    running: bool,
    /// The process ended while the start was still waiting; the start reports it.
    exited: bool,
}

struct Shell {
    backend: Mutex<Option<Backend>>,
    quitting: AtomicBool,
    generation: AtomicU64,
    data_dir: Mutex<Option<String>>,
    stderr_tail: Arc<Mutex<VecDeque<String>>>,
    status_item: Mutex<Option<MenuItem<Wry>>>,
    restarting: AtomicBool,
    page: Mutex<String>,
    downloads: Mutex<HashMap<String, PathBuf>>,
}

impl Shell {
    fn current(&self, generation: u64) -> bool {
        is_current(self.generation.load(Ordering::SeqCst), self.quitting.load(Ordering::SeqCst), generation)
    }
}

enum Line {
    Event(serde_json::Value),
    Eof,
    Exited,
}

/// The pieces a platform's spawn hands back: the process (or the watchdog on macOS) and its three pipes.
struct Started {
    sidecar: Sidecar,
    stdin: Box<dyn Write + Send>,
    stdout: Box<dyn Read + Send>,
    stderr: Box<dyn Read + Send>,
}

fn is_current(current: u64, quitting: bool, generation: u64) -> bool {
    !quitting && current == generation
}

/// Take the record out of its slot when it belongs to `only` (any generation when None); a stale caller gets nothing.
fn take_generation<T>(slot: &mut Option<T>, generation_of: impl Fn(&T) -> u64, only: Option<u64>) -> Option<T> {
    if slot.as_ref().is_some_and(|record| only.is_none_or(|g| generation_of(record) == g)) {
        slot.take()
    } else {
        None
    }
}

#[derive(Debug, PartialEq)]
enum OnExit {
    /// Another generation (or nobody) owns the slot: do nothing.
    Stale,
    /// The start of this generation is still waiting: tell it, it cleans up and says so.
    Starting,
    /// This generation was running: clean up and show "backend stopped".
    Running,
}

fn exit_action(slot: Option<(u64, bool)>, generation: u64) -> OnExit {
    match slot {
        Some((owner, running)) if owner == generation => {
            if running {
                OnExit::Running
            } else {
                OnExit::Starting
            }
        }
        _ => OnExit::Stale,
    }
}

/// Where the shell's own page is served: `tauri://localhost` on macOS, `http://tauri.localhost` on Windows (WebView2
/// cannot register a custom scheme as an origin, so Tauri maps it there).
#[derive(Clone, Copy)]
struct LocalOrigin {
    scheme: &'static str,
    host: &'static str,
}

const MACOS_LOCAL: LocalOrigin = LocalOrigin { scheme: "tauri", host: "localhost" };
const WINDOWS_LOCAL: LocalOrigin = LocalOrigin { scheme: "http", host: "tauri.localhost" };

fn local_origin() -> LocalOrigin {
    if cfg!(windows) {
        WINDOWS_LOCAL
    } else {
        MACOS_LOCAL
    }
}

impl LocalOrigin {
    fn page(&self, query: &str) -> String {
        format!("{}://{}/index.html?{query}", self.scheme, self.host)
    }

    fn owns(&self, url: &Url) -> bool {
        url.scheme() == self.scheme
            && url.host_str() == Some(self.host)
            && url.port().is_none()
            && url.username().is_empty()
            && url.password().is_none()
    }

    fn is_page(&self, url: &Url) -> bool {
        self.owns(url) && url.path() == "/index.html"
    }
}

fn backend_origin(url: &Url, port: Option<u16>) -> bool {
    port.is_some() && url.scheme() == "http" && url.host_str() == Some("127.0.0.1") && url.port() == port
}

#[derive(Debug, PartialEq)]
enum Nav {
    Allow,
    Restart,
    Quit,
    Outside,
    Deny,
}

/// What the window may show: the shell's own page and the backend's origin. The local page's Restart and Quit links
/// act only while that page is the one shown; every other URL is cancelled, and a web or mail link opens outside.
fn navigation(local: LocalOrigin, url: &Url, shown: Option<&Url>, port: Option<u16>) -> Nav {
    if local.owns(url) {
        let on_local_page = shown.is_some_and(|s| local.is_page(s));
        return match url.path() {
            "/index.html" => Nav::Allow,
            "/action/restart" if on_local_page => Nav::Restart,
            "/action/quit" if on_local_page => Nav::Quit,
            _ => Nav::Deny,
        };
    }
    if backend_origin(url, port) {
        return Nav::Allow;
    }
    if matches!(url.scheme(), "https" | "http" | "mailto") {
        Nav::Outside
    } else {
        Nav::Deny
    }
}

/// `destination` is a file directly inside `folder` (compared without regard to case on Windows).
/// Linux: the data folder from `XDG_DATA_HOME` (only when absolute) and `HOME`.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
fn linux_data_dir(xdg_data_home: Option<PathBuf>, home: Option<PathBuf>) -> PathBuf {
    match xdg_data_home {
        Some(folder) if folder.is_absolute() => folder.join("deixis"),
        _ => home.unwrap_or_else(|| PathBuf::from("/")).join(".local").join("share").join("deixis"),
    }
}

/// The environment for a program this shell starts (the watchdog, xdg-open). Inside an AppImage, `AppRun` and Tauri's
/// GTK hook point variables into `$APPDIR` for the shell's own WebKitGTK (GTK_*, GDK_*, GIO_*, GI_TYPELIB_PATH,
/// GSETTINGS_SCHEMA_DIR, XDG_DATA_DIRS, PATH, sometimes LD_LIBRARY_PATH): an outside program must not load those. One
/// rule, whatever the names: in every variable, the `:`-separated entries inside `$APPDIR` are dropped (the variable
/// too when nothing is left), and APPDIR, APPIMAGE, ARGV0 and OWD go. Outside an AppImage nothing changes.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
fn outside_env(vars: impl Iterator<Item = (String, String)>) -> Vec<(String, String)> {
    let vars: Vec<(String, String)> = vars.collect();
    let appdir = vars.iter().find(|(k, _)| k == "APPDIR").map(|(_, v)| v.trim_end_matches('/').to_string());
    let Some(appdir) = appdir.filter(|a| a.starts_with('/') && a.len() > 1) else {
        return vars;
    };
    let inside = |entry: &str| entry == appdir || entry.starts_with(&format!("{appdir}/"));
    vars.into_iter()
        .filter(|(k, _)| !matches!(k.as_str(), "APPDIR" | "APPIMAGE" | "ARGV0" | "OWD"))
        .filter_map(|(k, v)| {
            if !v.split(':').any(inside) {
                return Some((k, v));
            }
            let kept: Vec<&str> = v.split(':').filter(|e| !e.is_empty() && !inside(e)).collect();
            (!kept.is_empty()).then(|| (k, kept.join(":")))
        })
        .collect()
}

/// Linux: `name` in `folder`, or `name (1)`, `name (2)` ... before the extension when it is taken.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
fn free_destination(folder: &Path, name: &std::ffi::OsStr) -> PathBuf {
    let first = folder.join(name);
    if !first.exists() {
        return first;
    }
    let path = Path::new(name);
    let stem = path.file_stem().unwrap_or(name).to_string_lossy().to_string();
    let ext = path.extension().map(|e| format!(".{}", e.to_string_lossy())).unwrap_or_default();
    (1..10_000).map(|n| folder.join(format!("{stem} ({n}){ext}"))).find(|p| !p.exists()).unwrap_or(first)
}

fn directly_in(folder: &Path, destination: &Path, fold_case: bool) -> bool {
    let fold = |p: &Path| if fold_case { PathBuf::from(p.to_string_lossy().to_lowercase()) } else { p.to_path_buf() };
    destination.file_name().is_some() && destination.parent().is_some_and(|parent| fold(parent) == fold(folder))
}

fn token() -> String {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).expect("no randomness");
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// A minimal HTTP/1.1 request to the backend on loopback: no proxy, no redirect. (status, body)
fn http(port: u16, method: &str, path: &str, token: Option<&str>, timeout: Duration) -> Option<(u16, String)> {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let mut stream = TcpStream::connect_timeout(&addr, timeout).ok()?;
    stream.set_read_timeout(Some(timeout)).ok()?;
    stream.set_write_timeout(Some(timeout)).ok()?;
    let control = token.map(|t| format!("X-Deixis-Control: {t}\r\n")).unwrap_or_default();
    let request = format!(
        "{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n{control}Content-Length: 0\r\nConnection: close\r\n\r\n"
    );
    stream.write_all(request.as_bytes()).ok()?;
    let mut response = String::new();
    stream.read_to_string(&mut response).ok()?;
    let status = response.split_whitespace().nth(1)?.parse().ok()?;
    let body = response.split_once("\r\n\r\n").map(|(_, b)| b.to_string()).unwrap_or_default();
    Some((status, body))
}

/// DEIXIS_DATA_DIR, else the platform default (`config.platform_data_dir` in the backend); the backend's `listening`
/// line names the real folder once it has started.
fn default_data_dir() -> String {
    std::env::var("DEIXIS_DATA_DIR")
        .ok()
        .filter(|v| !v.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(platform::data_dir)
        .display()
        .to_string()
}

fn log_path(app: &AppHandle) -> String {
    let shell = app.state::<Shell>();
    let data = shell.data_dir.lock().unwrap().clone().unwrap_or_else(default_data_dir);
    PathBuf::from(data).join("logs").join("backend.log").display().to_string()
}

fn sidecar_path(app: &AppHandle) -> Result<PathBuf, String> {
    if cfg!(debug_assertions) {
        if let Ok(path) = std::env::var("DEIXIS_DESKTOP_SIDECAR") {
            return Ok(PathBuf::from(path)); // `cargo run` without a bundle; never read by a release build
        }
    }
    Ok(platform::resource_folder(app)?.join("sidecar").join("deixis-backend").join(platform::SIDECAR_EXE))
}

fn encode(text: &str) -> String {
    text.bytes()
        .map(|b| match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => (b as char).to_string(),
            _ => format!("%{b:02X}"),
        })
        .collect()
}

/// Show a local page of the shell (`ui/index.html`) in the window: starting, stopped.
fn show_local(app: &AppHandle, state: &str) {
    let log = log_path(app);
    if let Some(window) = app.get_webview_window(MAIN) {
        if let Ok(url) = Url::parse(&local_origin().page(&format!("state={state}&log={}", encode(&log)))) {
            let _ = window.navigate(url);
        }
        let _ = window.show();
    }
}

fn show_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(MAIN) {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn stopped_before(shell: &Shell) -> String {
    let tail = shell.stderr_tail.lock().unwrap().iter().rev().take(3).rev().cloned().collect::<Vec<_>>().join("\n");
    format!("The backend stopped before it started.\n{tail}")
}

/// Start the backend; returns once the window shows the backend's page or the start failed.
fn start(app: AppHandle) {
    let shell = app.state::<Shell>();
    if shell.quitting.load(Ordering::SeqCst) {
        return;
    }
    let generation = shell.generation.fetch_add(1, Ordering::SeqCst) + 1;
    show_local(&app, "starting");
    let failed = |message: String| fail_start(&app, generation, message);
    let path = match sidecar_path(&app) {
        Ok(path) => path,
        Err(message) => return failed(message),
    };
    let token = token();
    let Started { sidecar, mut stdin, stdout, stderr } = match Sidecar::spawn(&path) {
        Ok(started) => started,
        Err(e) => return failed(format!("The backend could not be started ({}): {e}", path.display())),
    };
    let _ = stdin.write_all(format!("{token}\n").as_bytes()).and_then(|_| stdin.flush());
    let (send, lines) = mpsc::channel::<Line>();
    let out = send.clone();
    thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if let Ok(event) = serde_json::from_str::<serde_json::Value>(&line) {
                let _ = out.send(Line::Event(event));
            }
        }
        let _ = out.send(Line::Eof);
    });
    let tail = shell.stderr_tail.clone();
    tail.lock().unwrap().clear();
    thread::spawn(move || {
        for line in BufReader::new(stderr).lines().map_while(Result::ok) {
            let mut kept = tail.lock().unwrap();
            if kept.len() == STDERR_LINES {
                kept.pop_front();
            }
            kept.push_back(line);
        }
    });
    let signal = platform::exit_signal(&sidecar);
    *shell.backend.lock().unwrap() = Some(Backend {
        generation,
        sidecar,
        stdin: Some(stdin),
        token: token.clone(),
        port: None,
        running: false,
        exited: false,
    });
    // From creation on, not after health and not on stdout EOF (a descendant may hold stdout open).
    platform::watch_exit(app.clone(), generation, signal, send);

    let event = match lines.recv_timeout(LISTEN_TIMEOUT) {
        Ok(Line::Event(event)) => event,
        Ok(Line::Eof) | Ok(Line::Exited) => return failed(stopped_before(&shell)),
        Err(_) => return failed("The backend did not start within 30 seconds.".into()),
    };
    match event.get("event").and_then(|v| v.as_str()) {
        Some("listening") => {}
        Some("startup_failed") => {
            let message = event.get("message").and_then(|v| v.as_str()).unwrap_or("The backend did not start.");
            return failed(message.to_string());
        }
        _ => return failed(format!("The backend sent an unexpected first line: {event}")),
    }
    let port = event.get("port").and_then(|v| v.as_u64()).unwrap_or(0) as u16;
    let nonce = event.get("nonce").and_then(|v| v.as_str()).unwrap_or("").to_string();
    *shell.data_dir.lock().unwrap() = event.get("data_dir").and_then(|v| v.as_str()).map(String::from);
    if let Some(backend) = shell.backend.lock().unwrap().as_mut().filter(|b| b.generation == generation) {
        backend.port = Some(port);
    }
    // 200 alone is not enough: another server could answer on this port; the nonce ties it to this start.
    let started = Instant::now();
    loop {
        if !shell.current(generation) {
            return; // a quit or a newer start owns the backend now
        }
        while let Ok(line) = lines.try_recv() {
            if matches!(line, Line::Exited) {
                return failed(stopped_before(&shell));
            }
        }
        if let Some((200, body)) = http(port, "GET", "/api/health", None, Duration::from_secs(2)) {
            let seen = serde_json::from_str::<serde_json::Value>(&body).ok();
            if seen.as_ref().and_then(|v| v.get("nonce")).and_then(|v| v.as_str()) == Some(nonce.as_str()) {
                break;
            }
        }
        if started.elapsed() > HEALTH_TIMEOUT {
            return failed("The backend started but did not answer its health check.".into());
        }
        thread::sleep(Duration::from_millis(100));
    }
    let running = match shell.backend.lock().unwrap().as_mut() {
        Some(backend) if backend.generation == generation && !backend.exited => {
            backend.running = true;
            true
        }
        _ => false,
    };
    if !running {
        return failed(stopped_before(&shell));
    }
    // Navigate while holding the backend slot: the exit watcher takes the same lock, so either it ran first (the slot
    // no longer holds this generation, it showed "stopped", nothing is navigated) or it runs after this navigation and
    // shows "stopped" then. A newer start (Restart) owns the slot too, so a stale start never covers its page.
    let slot = shell.backend.lock().unwrap();
    if slot.as_ref().is_some_and(|b| b.generation == generation && b.running) && shell.current(generation) {
        if let (Some(window), Ok(url)) = (app.get_webview_window(MAIN), Url::parse(&format!("http://127.0.0.1:{port}/"))) {
            let _ = window.navigate(url);
        }
    }
}

/// The backend's process of `generation` ended. A running backend: clean up that generation (on Windows its job, so no
/// descendant stays) and show "backend stopped"; no automatic restart. A start still waiting is told and reports it.
fn on_exit(app: &AppHandle, generation: u64, send: &Sender<Line>) {
    let shell = app.state::<Shell>();
    let mut slot = shell.backend.lock().unwrap();
    match exit_action(slot.as_ref().map(|b| (b.generation, b.running)), generation) {
        OnExit::Stale => {}
        OnExit::Starting => {
            if let Some(backend) = slot.as_mut() {
                backend.exited = true;
            }
            drop(slot);
            let _ = send.send(Line::Exited);
        }
        OnExit::Running => {
            let mut backend = slot.take().expect("checked above");
            drop(slot);
            backend.sidecar.force_stop();
            drop(backend);
            if !shell.quitting.load(Ordering::SeqCst) {
                show_local(app, "stopped");
            }
        }
    }
}

/// A start that failed: a visible message with the log's place, then this generation's backend (if any) is stopped
/// and the app ends. A stale start (a quit or a newer start came after it) does nothing.
fn fail_start(app: &AppHandle, generation: u64, message: String) {
    let shell = app.state::<Shell>();
    if !shell.current(generation) {
        return;
    }
    let log = log_path(app);
    eprintln!("DEIXIS could not start: {message} (log: {log})");
    stop_backend(app, Some(generation));
    let text = format!("{message}\n\nLog: {log}");
    // DEIXIS_DESKTOP_NO_DIALOG=1 (the desktop acceptance): the message goes to stderr only, nothing waits for a click.
    if std::env::var("DEIXIS_DESKTOP_NO_DIALOG").as_deref() != Ok("1") {
        app.dialog().message(text).title("DEIXIS could not start").kind(MessageDialogKind::Error).blocking_show();
    }
    shell.quitting.store(true, Ordering::SeqCst);
    app.exit(1);
}

/// Ask the backend to stop with the token and close its stdin (its signal that the shell is going), wait, then stop
/// what is left: on macOS the watchdog (this shell's own unreaped child, which kills what is left by verified identity),
/// if it has not ended in time; on Windows always the whole job. `only`: stop only that generation's backend.
fn stop_backend(app: &AppHandle, only: Option<u64>) {
    let shell = app.state::<Shell>();
    let Some(mut backend) = take_generation(&mut *shell.backend.lock().unwrap(), |b| b.generation, only) else {
        return;
    };
    if let Some(port) = backend.port {
        let _ = http(port, "POST", "/api/internal/shutdown", Some(&backend.token), Duration::from_secs(2));
    }
    backend.stdin.take();
    let ends = Instant::now() + platform::STOP_WAIT;
    while Instant::now() < ends && !backend.sidecar.exited() {
        thread::sleep(Duration::from_millis(100));
    }
    backend.sidecar.force_stop();
}

/// The last stop when the app ends without Quit (see RunEvent::Exit); nothing when a quit already ran.
fn stop_once(app: &AppHandle) {
    if !app.state::<Shell>().quitting.swap(true, Ordering::SeqCst) {
        stop_backend(app, None);
    }
}

fn quit(app: AppHandle) {
    let shell = app.state::<Shell>();
    if shell.quitting.swap(true, Ordering::SeqCst) {
        return;
    }
    thread::spawn(move || {
        stop_backend(&app, None);
        app.exit(0);
    });
}

/// One restart at a time; a second click while one runs is dropped.
fn restart(app: AppHandle) {
    if app.state::<Shell>().restarting.swap(true, Ordering::SeqCst) {
        return;
    }
    thread::spawn(move || {
        stop_backend(&app, None);
        start(app.clone());
        app.state::<Shell>().restarting.store(false, Ordering::SeqCst);
    });
}

/// A message that waits for nobody: a dialog the app keeps running behind, or stderr only under
/// DEIXIS_DESKTOP_NO_DIALOG=1 (the desktop acceptance).
fn notify(app: &AppHandle, title: &str, text: String, error: bool) {
    eprintln!("DEIXIS: {title}: {text}");
    if std::env::var("DEIXIS_DESKTOP_NO_DIALOG").as_deref() != Ok("1") {
        let kind = if error { MessageDialogKind::Error } else { MessageDialogKind::Info };
        app.dialog().message(text).title(title).kind(kind).show(|_| {});
    }
}

fn backend_port(app: &AppHandle) -> Option<u16> {
    app.state::<Shell>().backend.lock().unwrap().as_ref().and_then(|b| b.port)
}

fn own_origin(app: &AppHandle, url: &Url) -> bool {
    backend_origin(url, backend_port(app))
}

/// A download from the backend's page: a blob: or data: URL made by the page, or the backend's own origin. The file
/// goes where the webview's default put it (the Downloads folder, `name (n).ext` when the name is taken); anything
/// else is refused.
fn on_download(app: &AppHandle, event: DownloadEvent<'_>) -> bool {
    let shell = app.state::<Shell>();
    match event {
        DownloadEvent::Requested { url, destination } => {
            let from_page = match url.scheme() {
                "blob" => Url::parse(url.path()).is_ok_and(|inner| own_origin(app, &inner)),
                "data" => Url::parse(&shell.page.lock().unwrap()).is_ok_and(|shown| own_origin(app, &shown)),
                _ => own_origin(app, &url),
            };
            let folder = platform::downloads_folder();
            // Linux: Wry's own choice is the current folder when XDG names no Downloads folder; the shell names the file.
            #[cfg(target_os = "linux")]
            if let (Some(f), Some(name)) = (folder.as_deref(), destination.file_name().map(|n| n.to_os_string())) {
                *destination = free_destination(f, &name);
            }
            let named = folder.as_deref().is_some_and(|f| directly_in(f, destination, cfg!(windows)));
            let made = folder.as_deref().is_some_and(|f| std::fs::create_dir_all(f).is_ok());
            if !from_page || !named || !made {
                notify(app, "Download not saved", format!("DEIXIS did not save this download ({}).", destination.display()), true);
                return false;
            }
            shell.downloads.lock().unwrap().insert(url.to_string(), destination.clone());
            true
        }
        DownloadEvent::Finished { url, success, .. } => {
            let path = shell.downloads.lock().unwrap().remove(url.as_str());
            let shown = path
                .or_else(platform::downloads_folder)
                .map(|p| p.display().to_string())
                .unwrap_or_else(|| "Downloads".into());
            if success {
                notify(app, "Download saved", format!("Saved to {shown}"), false);
            } else {
                notify(app, "Download failed", format!("The file could not be saved ({shown})."), true);
            }
            true
        }
        _ => true,
    }
}

/// The tray count, read with the token from the backend's read-only status route.
fn refresh_status(app: AppHandle) {
    thread::spawn(move || loop {
        let shell = app.state::<Shell>();
        if shell.quitting.load(Ordering::SeqCst) {
            return;
        }
        let target = shell.backend.lock().unwrap().as_ref().and_then(|b| b.port.map(|p| (p, b.token.clone())));
        let text = match target.and_then(|(p, t)| http(p, "GET", "/api/internal/status", Some(&t), Duration::from_secs(2))) {
            Some((200, body)) => match serde_json::from_str::<serde_json::Value>(&body)
                .ok()
                .and_then(|v| v.get("running_researches").and_then(|n| n.as_u64()))
            {
                Some(0) => "No research running".to_string(),
                Some(1) => "1 research running".to_string(),
                Some(n) => format!("{n} researches running"),
                None => "Research status unknown".to_string(),
            },
            _ => "Backend not running".to_string(),
        };
        if let Some(item) = shell.status_item.lock().unwrap().as_ref() {
            let _ = item.set_text(text);
        }
        thread::sleep(STATUS_EVERY);
    });
}

fn on_navigation(app: &AppHandle, url: &Url) -> bool {
    let shown = Url::parse(&app.state::<Shell>().page.lock().unwrap()).ok();
    match navigation(local_origin(), url, shown.as_ref(), backend_port(app)) {
        Nav::Allow => return true,
        Nav::Restart => restart(app.clone()),
        Nav::Quit => quit(app.clone()),
        Nav::Outside => platform::open_outside(url), // another site: the default browser
        Nav::Deny => {}
    }
    false
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| show_main(app)))
        .plugin(tauri_plugin_dialog::init())
        .manage(Shell {
            backend: Mutex::new(None),
            quitting: AtomicBool::new(false),
            generation: AtomicU64::new(0),
            data_dir: Mutex::new(None),
            stderr_tail: Arc::new(Mutex::new(VecDeque::new())),
            status_item: Mutex::new(None),
            restarting: AtomicBool::new(false),
            page: Mutex::new(String::new()),
            downloads: Mutex::new(HashMap::new()),
        })
        .setup(|app| {
            let handle = app.handle().clone();
            let nav = handle.clone();
            let popup = handle.clone();
            let saver = handle.clone();
            WebviewWindowBuilder::new(app, MAIN, WebviewUrl::App("index.html".into()))
                .title("DEIXIS")
                .inner_size(1280.0, 840.0)
                .min_inner_size(720.0, 520.0)
                .on_navigation(move |url| on_navigation(&nav, url))
                .on_new_window(move |url, _features| {
                    // `target=_blank` and window.open: the app's own pages stay in this window, others open outside.
                    if on_navigation(&popup, &url) {
                        if let Some(window) = popup.get_webview_window(MAIN) {
                            let _ = window.navigate(url);
                        }
                    }
                    NewWindowResponse::Deny
                })
                .on_page_load(|window, payload| {
                    // The document now shown (committed), for the action check in on_navigation.
                    *window.app_handle().state::<Shell>().page.lock().unwrap() = payload.url().to_string();
                })
                .on_download(move |_webview, event| on_download(&saver, event))
                .build()?;
            let open = MenuItem::with_id(app, "open", "Open DEIXIS", true, None::<&str>)?;
            let status = MenuItem::with_id(app, "status", "Backend starting", false, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit DEIXIS", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &status, &PredefinedMenuItem::separator(app)?, &quit_item])?;
            *app.state::<Shell>().status_item.lock().unwrap() = Some(status);
            let mut tray = TrayIconBuilder::with_id("deixis").menu(&menu).tooltip("DEIXIS").show_menu_on_left_click(true);
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.on_menu_event(|app, event| match event.id.as_ref() {
                "open" => show_main(app),
                "quit" => quit(app.clone()),
                _ => {}
            })
            .build(app)?;
            thread::spawn(move || start(handle.clone()));
            refresh_status(app.handle().clone());
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                // Closing the window keeps DEIXIS running in the tray; Quit ends it.
                if !window.app_handle().state::<Shell>().quitting.load(Ordering::SeqCst) {
                    api.prevent_close();
                    if cfg!(target_os = "linux") {
                        // Linux quits: GNOME shows no tray without an extension, so a hidden window could not be found.
                        quit(window.app_handle().clone());
                    } else {
                        let _ = window.hide();
                    }
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("the DEIXIS shell could not be built");
    app.run(|app, event| match event {
        RunEvent::ExitRequested { api, .. } => {
            // An exit asked for inside the app: stop the backend first, then exit (quit() calls exit again).
            if !app.state::<Shell>().quitting.load(Ordering::SeqCst) {
                api.prevent_exit();
                quit(app.clone());
            }
        }
        RunEvent::Exit => {
            // Cmd+Q, the app menu's or the Dock's Quit and a logout reach the app as NSApplication's terminate, which
            // ends the run loop without ExitRequested (applicationWillTerminate): the same stop runs here, before the
            // process ends. The watchdog (macOS) or the job (Windows) would stop everything anyway once the shell is
            // gone; this keeps the token shutdown.
            stop_once(app)
        }
        #[cfg(target_os = "macos")]
        RunEvent::Reopen { .. } => show_main(app),
        _ => {}
    });
}

/// macOS and Linux: the watchdog is the shell's child; it owns the backend's process group and every recorded
/// descendant (on Linux also every orphan, as its child subreaper).
#[cfg(not(windows))]
mod platform {
    use std::path::{Path, PathBuf};
    use std::process::{Child, Command, Stdio};
    use std::sync::mpsc::Sender;
    use std::thread;
    use std::time::Duration;

    use tauri::{AppHandle, Manager, Url};

    use super::{on_exit, Line, Shell, Started};

    pub const SIDECAR_EXE: &str = "deixis-backend";
    /// The backend's 8 s plus the watchdog's own sweep (6 s) after it.
    pub const STOP_WAIT: Duration = Duration::from_secs(super::SHUTDOWN_WAIT.as_secs() + 6);

    pub struct Sidecar(Child);

    pub struct ExitSignal;

    impl Sidecar {
        pub fn spawn(path: &Path) -> Result<Started, String> {
            let home = std::env::var("HOME").unwrap_or_else(|_| "/".into());
            let mut command = Command::new(path);
            #[cfg(target_os = "linux")]
            command.env_clear().envs(super::outside_env(std::env::vars()));
            let mut child = command
                .args(["-m", "deixis.desktop_reaper"])
                .env_remove("DEIXIS_CONTROL_TOKEN")
                .current_dir(home)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()
                .map_err(|e| e.to_string())?;
            let stdin = child.stdin.take().expect("piped stdin");
            let stdout = child.stdout.take().expect("piped stdout");
            let stderr = child.stderr.take().expect("piped stderr");
            Ok(Started { sidecar: Sidecar(child), stdin: Box::new(stdin), stdout: Box::new(stdout), stderr: Box::new(stderr) })
        }

        pub fn exited(&mut self) -> bool {
            self.0.try_wait().ok().flatten().is_some()
        }

        /// Only the watchdog, this shell's own unreaped child, is ever signalled from here, and only if it is still
        /// there after the wait.
        pub fn force_stop(&mut self) {
            if !self.exited() {
                eprintln!("DEIXIS: the watchdog did not finish in time; stopping it");
                let _ = self.0.kill();
                let _ = self.0.wait();
            }
        }
    }

    pub fn exit_signal(_sidecar: &Sidecar) -> ExitSignal {
        ExitSignal
    }

    /// Polls this generation's child; ends when the slot holds another generation or nothing.
    pub fn watch_exit(app: AppHandle, generation: u64, _signal: ExitSignal, send: Sender<Line>) {
        thread::spawn(move || loop {
            thread::sleep(Duration::from_millis(250));
            let shell = app.state::<Shell>();
            let ended = match shell.backend.lock().unwrap().as_mut() {
                Some(backend) if backend.generation == generation => backend.sidecar.exited(),
                _ => return,
            };
            if ended {
                on_exit(&app, generation, &send);
                return;
            }
        });
    }

    #[cfg(target_os = "macos")]
    pub fn data_dir() -> PathBuf {
        PathBuf::from(std::env::var("HOME").unwrap_or_default()).join("Library").join("Application Support").join("DEIXIS")
    }

    #[cfg(target_os = "macos")]
    pub fn downloads_folder() -> Option<PathBuf> {
        Some(PathBuf::from(std::env::var("HOME").unwrap_or_default()).join("Downloads"))
    }

    #[cfg(target_os = "macos")]
    pub fn open_outside(url: &Url) {
        let _ = Command::new("/usr/bin/open").arg(url.as_str()).spawn();
    }

    /// `$XDG_DATA_HOME/deixis` when that is an absolute path, else `~/.local/share/deixis` (the backend's
    /// `config.platform_data_dir` follows the same rule).
    #[cfg(target_os = "linux")]
    pub fn data_dir() -> PathBuf {
        super::linux_data_dir(std::env::var_os("XDG_DATA_HOME").map(PathBuf::from), std::env::var_os("HOME").map(PathBuf::from))
    }

    /// The XDG Downloads folder, else `~/Downloads` (created at the first download).
    #[cfg(target_os = "linux")]
    pub fn downloads_folder() -> Option<PathBuf> {
        dirs::download_dir().or_else(|| std::env::var_os("HOME").map(|home| PathBuf::from(home).join("Downloads")))
    }

    /// xdg-open with the environment cleaned of the AppImage's own library and GTK settings (`outside_env`).
    #[cfg(target_os = "linux")]
    pub fn open_outside(url: &Url) {
        let _ = Command::new("xdg-open").arg(url.as_str()).env_clear().envs(super::outside_env(std::env::vars())).spawn();
    }

    /// The `.deb`'s `/usr/lib/DEIXIS` or the AppImage's `$APPDIR/usr/lib/DEIXIS`, as Tauri resolves it.
    #[cfg(target_os = "linux")]
    pub fn resource_folder(app: &AppHandle) -> Result<PathBuf, String> {
        app.path().resource_dir().map_err(|e| format!("no resource folder: {e}"))
    }

    /// Contents/Resources of this bundle. Tauri's resolver refuses an executable path with a symlink anywhere in it
    /// (tauri-utils `starting_binary`, for example /var -> /private/var); the fallback resolves the executable's real
    /// path first and accepts only the X.app/Contents/MacOS/<exe> layout.
    #[cfg(target_os = "macos")]
    pub fn resource_folder(app: &AppHandle) -> Result<PathBuf, String> {
        match app.path().resource_dir() {
            Ok(dir) => Ok(dir),
            Err(e) => {
                eprintln!("DEIXIS: Tauri found no resource folder ({e}); using the executable's bundle");
                bundle_resources().map_err(|x| format!("no resource folder: {e}; {x}"))
            }
        }
    }

    #[cfg(target_os = "macos")]
    fn bundle_resources() -> Result<PathBuf, String> {
        let exe = std::env::current_exe().map_err(|e| format!("the executable's path cannot be read: {e}"))?;
        let real = exe.canonicalize().map_err(|e| format!("{} cannot be resolved: {e}", exe.display()))?;
        let macos = real.parent().filter(|d| d.file_name().is_some_and(|n| n == "MacOS"));
        let contents = macos.and_then(Path::parent).filter(|d| d.file_name().is_some_and(|n| n == "Contents"));
        let bundle = contents.and_then(Path::parent).filter(|d| d.extension().is_some_and(|x| x == "app"));
        match (contents, bundle) {
            (Some(contents), Some(_)) if contents.join("Resources").is_dir() => Ok(contents.join("Resources")),
            _ => Err(format!("{} is not inside an .app bundle's Contents/MacOS", real.display())),
        }
    }
}

/// Windows: the backend itself, created inside this generation's kill-on-close job.
#[cfg(windows)]
mod platform {
    use std::ffi::OsStr;
    use std::path::{Path, PathBuf};
    use std::sync::mpsc::Sender;
    use std::thread;
    use std::time::Duration;

    use tauri::{AppHandle, Manager, Url};
    use windows_sys::Win32::UI::Shell::ShellExecuteW;
    use windows_sys::Win32::UI::WindowsAndMessaging::SW_SHOWNORMAL;

    use super::win_job;
    use super::{on_exit, Line, Started};

    pub const SIDECAR_EXE: &str = "deixis-backend.exe";
    /// Token shutdown, 8 s, then TerminateJobObject.
    pub const STOP_WAIT: Duration = super::SHUTDOWN_WAIT;
    /// After TerminateJobObject: how long to wait for the job to be empty (termination is asynchronous).
    const JOB_EMPTY_WAIT: Duration = Duration::from_secs(5);

    pub struct Sidecar(win_job::Backend);

    pub struct ExitSignal(win_job::Waiter);

    impl Sidecar {
        /// `serve --desktop`, the same arguments the macOS watchdog gives the backend; the token goes on stdin.
        pub fn spawn(path: &Path) -> Result<Started, String> {
            let env = std::env::vars_os().filter(|(name, _)| !name.eq_ignore_ascii_case("DEIXIS_CONTROL_TOKEN")).collect();
            let home = dirs::home_dir();
            let spawned = win_job::spawn(path, &["serve", "--desktop"], env, home.as_deref())?;
            Ok(Started {
                sidecar: Sidecar(spawned.backend),
                stdin: Box::new(spawned.stdin),
                stdout: Box::new(spawned.stdout),
                stderr: Box::new(spawned.stderr),
            })
        }

        pub fn exited(&mut self) -> bool {
            self.0.exited()
        }

        /// The whole job goes, whether or not the backend itself has ended: no descendant outlives it.
        pub fn force_stop(&mut self) {
            if !self.0.exited() {
                eprintln!("DEIXIS: the backend did not finish in time; ending its job");
            }
            if !self.0.terminate_job(JOB_EMPTY_WAIT) {
                eprintln!("DEIXIS: processes of the backend's job were still ending after {JOB_EMPTY_WAIT:?}");
            }
        }
    }

    pub fn exit_signal(sidecar: &Sidecar) -> ExitSignal {
        ExitSignal(sidecar.0.waiter())
    }

    /// Waits on this generation's process handle from its creation.
    pub fn watch_exit(app: AppHandle, generation: u64, signal: ExitSignal, send: Sender<Line>) {
        thread::spawn(move || {
            signal.0.wait();
            on_exit(&app, generation, &send);
        });
    }

    /// `%LOCALAPPDATA%\DEIXIS`, as the backend's `config.platform_data_dir`.
    pub fn data_dir() -> PathBuf {
        std::env::var_os("LOCALAPPDATA")
            .filter(|v| !v.is_empty())
            .map(PathBuf::from)
            .unwrap_or_else(|| dirs::home_dir().unwrap_or_default().join("AppData").join("Local"))
            .join("DEIXIS")
    }

    /// The user's Downloads known folder, where WebView2 puts downloads by default.
    pub fn downloads_folder() -> Option<PathBuf> {
        dirs::download_dir()
    }

    /// The default browser or mail program, through the shell's "open" verb on the URL itself: no command line.
    pub fn open_outside(url: &Url) {
        let verb = win_job::wide(OsStr::new("open"));
        let file = win_job::wide(OsStr::new(url.as_str()));
        unsafe {
            ShellExecuteW(std::ptr::null_mut(), verb.as_ptr(), file.as_ptr(), std::ptr::null(), std::ptr::null(), SW_SHOWNORMAL)
        };
    }

    /// The install folder (NSIS puts resources next to the executable), as a plain `C:\...` path. Tauri gives it
    /// canonicalized, `\\?\C:\...`: Windows does not resolve `..` in such a path, so the backend started from it
    /// found none of its relative files (`references\..\SKILL.md`) and refused to start.
    pub fn resource_folder(app: &AppHandle) -> Result<PathBuf, String> {
        let dir = app.path().resource_dir().map_err(|e| format!("no resource folder: {e}"))?;
        Ok(dunce::simplified(&dir).to_path_buf())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn url(text: &str) -> Url {
        Url::parse(text).unwrap()
    }

    #[test]
    fn local_page_is_exactly_the_platform_origin_and_index() {
        for (local, page) in [(MACOS_LOCAL, "tauri://localhost"), (WINDOWS_LOCAL, "http://tauri.localhost")] {
            assert_eq!(local.page("state=starting"), format!("{page}/index.html?state=starting"));
            assert!(local.is_page(&url(&format!("{page}/index.html?state=stopped&log=x"))));
            assert!(!local.is_page(&url(&format!("{page}/other.html"))));
            assert!(!local.is_page(&url(&format!("{page}/"))));
        }
        assert!(!WINDOWS_LOCAL.owns(&url("http://tauri.localhost:8080/index.html")));
        assert!(!WINDOWS_LOCAL.owns(&url("https://tauri.localhost/index.html")));
        assert!(!WINDOWS_LOCAL.owns(&url("http://user@tauri.localhost/index.html")));
        assert!(!WINDOWS_LOCAL.owns(&url("http://tauri.localhost.example.com/index.html")));
        assert!(!WINDOWS_LOCAL.owns(&url("tauri://localhost/index.html")));
        assert!(!MACOS_LOCAL.owns(&url("http://tauri.localhost/index.html")));
        assert!(!MACOS_LOCAL.owns(&url("http://localhost/index.html")));
    }

    #[test]
    fn actions_only_from_the_local_page_of_this_platform() {
        for (local, page) in [(MACOS_LOCAL, "tauri://localhost"), (WINDOWS_LOCAL, "http://tauri.localhost")] {
            let shown_local = url(&format!("{page}/index.html?state=stopped"));
            let shown_backend = url("http://127.0.0.1:8770/");
            let restart = url(&format!("{page}/action/restart"));
            let quit = url(&format!("{page}/action/quit"));
            assert_eq!(navigation(local, &restart, Some(&shown_local), Some(8770)), Nav::Restart);
            assert_eq!(navigation(local, &quit, Some(&shown_local), None), Nav::Quit);
            assert_eq!(navigation(local, &restart, Some(&shown_backend), Some(8770)), Nav::Deny);
            assert_eq!(navigation(local, &quit, None, Some(8770)), Nav::Deny);
            assert_eq!(navigation(local, &url(&format!("{page}/action/other")), Some(&shown_local), None), Nav::Deny);
            assert_eq!(navigation(local, &url(&format!("{page}/index.html?state=starting")), None, None), Nav::Allow);
        }
        // The other platform's local origin is no local page here.
        let mac_page = url("tauri://localhost/index.html");
        assert_eq!(navigation(WINDOWS_LOCAL, &url("tauri://localhost/action/quit"), Some(&mac_page), None), Nav::Deny);
        let win_page = url("http://tauri.localhost/index.html");
        assert_eq!(navigation(MACOS_LOCAL, &url("http://tauri.localhost/action/quit"), Some(&win_page), None), Nav::Outside);
    }

    #[test]
    fn backend_origin_and_outside_links() {
        let local = local_origin();
        assert_eq!(navigation(local, &url("http://127.0.0.1:8770/research/1"), None, Some(8770)), Nav::Allow);
        assert_eq!(navigation(local, &url("http://127.0.0.1:8771/"), None, Some(8770)), Nav::Outside);
        assert_eq!(navigation(local, &url("http://127.0.0.1:8770/"), None, None), Nav::Outside);
        assert_eq!(navigation(local, &url("https://doi.org/10.1/x"), None, Some(8770)), Nav::Outside);
        assert_eq!(navigation(local, &url("mailto:a@b.c"), None, Some(8770)), Nav::Outside);
        assert_eq!(navigation(local, &url("file:///etc/passwd"), None, Some(8770)), Nav::Deny);
        assert_eq!(navigation(local, &url("javascript:alert(1)"), None, Some(8770)), Nav::Deny);
    }

    #[test]
    fn a_stale_generation_never_takes_a_newer_backend() {
        let mut slot = Some(2u64);
        assert_eq!(take_generation(&mut slot, |g| *g, Some(1)), None);
        assert_eq!(slot, Some(2));
        assert_eq!(take_generation(&mut slot, |g| *g, Some(2)), Some(2));
        assert_eq!(slot, None);
        let mut slot = Some(3u64);
        assert_eq!(take_generation(&mut slot, |g| *g, None), Some(3)); // quit and restart stop whatever runs
        assert_eq!(take_generation(&mut None::<u64>, |g| *g, None), None);
    }

    #[test]
    fn exit_of_a_generation_acts_only_on_that_generation() {
        assert_eq!(exit_action(Some((2, true)), 1), OnExit::Stale);
        assert_eq!(exit_action(Some((2, false)), 1), OnExit::Stale);
        assert_eq!(exit_action(None, 1), OnExit::Stale);
        assert_eq!(exit_action(Some((1, false)), 1), OnExit::Starting);
        assert_eq!(exit_action(Some((1, true)), 1), OnExit::Running);
        assert!(is_current(3, false, 3));
        assert!(!is_current(3, false, 2));
        assert!(!is_current(3, true, 3));
    }

    #[test]
    fn downloads_land_directly_in_the_folder() {
        let folder = Path::new("/Users/a/Downloads");
        assert!(directly_in(folder, Path::new("/Users/a/Downloads/report.csv"), false));
        assert!(!directly_in(folder, Path::new("/Users/a/Downloads/sub/report.csv"), false));
        assert!(!directly_in(folder, Path::new("/Users/a/report.csv"), false));
        assert!(!directly_in(folder, Path::new("/Users/a/downloads/report.csv"), false));
        assert!(directly_in(folder, Path::new("/Users/a/downloads/report.csv"), true));
    }

    #[test]
    fn an_appimage_environment_is_cleaned_for_outside_programs() {
        let vars = [
            ("APPDIR", "/tmp/.mount_DEIXIS"),
            ("APPIMAGE", "/home/p/DEIXIS.AppImage"),
            ("PATH", "/tmp/.mount_DEIXIS/usr/bin:/usr/local/bin:/usr/bin"),
            ("XDG_DATA_DIRS", "/tmp/.mount_DEIXIS/usr/share:/usr/share"),
            ("GTK_EXE_PREFIX", "/tmp/.mount_DEIXIS/usr"),
            ("GDK_PIXBUF_MODULE_FILE", "/tmp/.mount_DEIXIS/usr/lib/loaders.cache"),
            ("LD_LIBRARY_PATH", "/tmp/.mount_DEIXIS/usr/lib"),
            ("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus"),
            ("HOME", "/home/p"),
            ("NOTE", "/tmp/.mount_DEIXISX/other"),
        ];
        let cleaned: HashMap<String, String> =
            outside_env(vars.iter().map(|(k, v)| (k.to_string(), v.to_string()))).into_iter().collect();
        assert_eq!(cleaned.get("PATH").map(String::as_str), Some("/usr/local/bin:/usr/bin"));
        assert_eq!(cleaned.get("XDG_DATA_DIRS").map(String::as_str), Some("/usr/share"));
        for gone in ["APPDIR", "APPIMAGE", "GTK_EXE_PREFIX", "GDK_PIXBUF_MODULE_FILE", "LD_LIBRARY_PATH"] {
            assert!(!cleaned.contains_key(gone), "{gone}");
        }
        assert_eq!(cleaned.get("DBUS_SESSION_BUS_ADDRESS").map(String::as_str), Some("unix:path=/run/user/1000/bus"));
        assert_eq!(cleaned.get("NOTE").map(String::as_str), Some("/tmp/.mount_DEIXISX/other")); // a prefix, not inside
        let plain = [("PATH".to_string(), "/usr/bin".to_string()), ("GTK_PATH".to_string(), "/opt/gtk".to_string())];
        assert_eq!(outside_env(plain.clone().into_iter()), plain.to_vec()); // no AppImage: unchanged
    }

    #[test]
    fn the_linux_data_folder_takes_only_an_absolute_xdg_data_home() {
        let home = Some(PathBuf::from("/home/p"));
        assert_eq!(linux_data_dir(Some(PathBuf::from("/data")), home.clone()), PathBuf::from("/data/deixis"));
        assert_eq!(linux_data_dir(Some(PathBuf::from("rel")), home.clone()), PathBuf::from("/home/p/.local/share/deixis"));
        assert_eq!(linux_data_dir(Some(PathBuf::from("")), home.clone()), PathBuf::from("/home/p/.local/share/deixis"));
        assert_eq!(linux_data_dir(None, home), PathBuf::from("/home/p/.local/share/deixis"));
    }

    #[test]
    fn a_download_never_replaces_a_file_already_there() {
        let folder = std::env::temp_dir().join(format!("deixis-free-{}", std::process::id()));
        std::fs::create_dir_all(&folder).unwrap();
        let name = std::ffi::OsStr::new("report.csv");
        assert_eq!(free_destination(&folder, name), folder.join("report.csv"));
        std::fs::write(folder.join("report.csv"), "x").unwrap();
        assert_eq!(free_destination(&folder, name), folder.join("report (1).csv"));
        std::fs::remove_dir_all(&folder).unwrap();
    }

    #[test]
    fn tokens_are_fresh_and_hex() {
        let (a, b) = (token(), token());
        assert_eq!(a.len(), 64);
        assert!(a.bytes().all(|c| c.is_ascii_hexdigit()));
        assert_ne!(a, b);
    }
}
