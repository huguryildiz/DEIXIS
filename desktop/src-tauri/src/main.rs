//! The DEIXIS macOS shell (P10 M2): one window, a menu-bar item and the backend's lifetime.
//!
//! The backend ships inside the app (`Contents/Resources/sidecar/deixis-backend/`). The shell starts it through its
//! watchdog (`deixis-backend -m deixis.desktop_reaper`, which starts `serve --desktop`), writes a fresh control token
//! as the first stdin line and keeps stdin open: EOF on that pipe is how the watchdog learns the shell is gone. The
//! first JSON line on stdout decides the start: `listening` (port, pid, nonce, data folder) or `startup_failed`; an
//! exit without a line or 30 s without one is a failed start too. Health must answer 200 with the same nonce before the
//! window leaves the local launch page for `http://127.0.0.1:<port>/`.
//!
//! No IPC: the app registers no command and grants no capability, so neither the local pages nor the backend's page
//! can call into Rust. The local pages ask for "restart" and "quit" by navigating to `/action/...`, which the
//! navigation handler below cancels and acts on, only while the window shows the local page. Links to other sites open
//! in the default browser. Downloads (the CSV and report exports, blob: links) go to ~/Downloads under a name not yet
//! taken; a failed one is said in a message.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::collections::{HashMap, VecDeque};
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::webview::{DownloadEvent, NewWindowResponse};
use tauri::{AppHandle, Manager, RunEvent, Url, WebviewUrl, WebviewWindowBuilder, WindowEvent, Wry};
use tauri_plugin_dialog::{DialogExt, MessageDialogKind};

const LISTEN_TIMEOUT: Duration = Duration::from_secs(30);
const HEALTH_TIMEOUT: Duration = Duration::from_secs(30);
const SHUTDOWN_WAIT: Duration = Duration::from_secs(8);
const REAPER_WAIT: Duration = Duration::from_secs(6); // the watchdog's own sweep after its 8 s wait
const STATUS_EVERY: Duration = Duration::from_secs(5);
const STDERR_LINES: usize = 40;
const MAIN: &str = "main";

struct Backend {
    child: Child,
    stdin: Option<ChildStdin>,
    token: String,
    port: Option<u16>,
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

enum Line {
    Event(serde_json::Value),
    Eof,
}

fn token() -> String {
    let mut bytes = [0u8; 32];
    std::fs::File::open("/dev/urandom").and_then(|mut f| f.read_exact(&mut bytes)).expect("no randomness");
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

fn default_data_dir() -> String {
    std::env::var("DEIXIS_DATA_DIR").ok().filter(|v| !v.is_empty()).unwrap_or_else(|| {
        format!("{}/Library/Application Support/DEIXIS", std::env::var("HOME").unwrap_or_default())
    })
}

fn log_path(app: &AppHandle) -> String {
    let shell = app.state::<Shell>();
    let data = shell.data_dir.lock().unwrap().clone().unwrap_or_else(default_data_dir);
    format!("{data}/logs/backend.log")
}

fn sidecar_path(app: &AppHandle) -> Result<PathBuf, String> {
    if cfg!(debug_assertions) {
        if let Ok(path) = std::env::var("DEIXIS_DESKTOP_SIDECAR") {
            return Ok(PathBuf::from(path)); // `cargo run` without a bundle; never read by a release build
        }
    }
    // Contents/Resources of this bundle. Tauri's resolver refuses an executable path with a symlink anywhere in it
    // (tauri-utils `starting_binary`, for example /var -> /private/var); the fallback resolves the executable's real
    // path first and accepts only the X.app/Contents/MacOS/<exe> layout.
    let dir = match app.path().resource_dir() {
        Ok(dir) => dir,
        Err(e) => {
            eprintln!("DEIXIS: Tauri found no resource folder ({e}); using the executable's bundle");
            bundle_resources().map_err(|x| format!("no resource folder: {e}; {x}"))?
        }
    };
    Ok(dir.join("sidecar").join("deixis-backend").join("deixis-backend"))
}

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
        if let Ok(url) = Url::parse(&format!("tauri://localhost/index.html?state={state}&log={}", encode(&log))) {
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

/// Start the watchdog and the backend; returns once the window shows the backend's page or the start failed.
fn start(app: AppHandle) {
    let shell = app.state::<Shell>();
    if shell.quitting.load(Ordering::SeqCst) {
        return;
    }
    let generation = shell.generation.fetch_add(1, Ordering::SeqCst) + 1;
    show_local(&app, "starting");
    let failed = |message: String| fail_start(&app, message);
    let sidecar = match sidecar_path(&app) {
        Ok(path) => path,
        Err(message) => return failed(message),
    };
    let token = token();
    let home = std::env::var("HOME").unwrap_or_else(|_| "/".into());
    let spawned = Command::new(&sidecar)
        .args(["-m", "deixis.desktop_reaper"])
        .env_remove("DEIXIS_CONTROL_TOKEN")
        .current_dir(home)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn();
    let mut child = match spawned {
        Ok(child) => child,
        Err(e) => return failed(format!("The backend could not be started ({}): {e}", sidecar.display())),
    };
    let mut stdin = child.stdin.take();
    if let Some(pipe) = stdin.as_mut() {
        let _ = pipe.write_all(format!("{token}\n").as_bytes()).and_then(|_| pipe.flush());
    }
    let (send, lines) = mpsc::channel::<Line>();
    let stdout = child.stdout.take().expect("piped stdout");
    thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if let Ok(event) = serde_json::from_str::<serde_json::Value>(&line) {
                let _ = send.send(Line::Event(event));
            }
        }
        let _ = send.send(Line::Eof);
    });
    let tail = shell.stderr_tail.clone();
    tail.lock().unwrap().clear();
    let stderr = child.stderr.take().expect("piped stderr");
    thread::spawn(move || {
        for line in BufReader::new(stderr).lines().map_while(Result::ok) {
            let mut kept = tail.lock().unwrap();
            if kept.len() == STDERR_LINES {
                kept.pop_front();
            }
            kept.push_back(line);
        }
    });
    *shell.backend.lock().unwrap() = Some(Backend { child, stdin, token: token.clone(), port: None });

    let event = match lines.recv_timeout(LISTEN_TIMEOUT) {
        Ok(Line::Event(event)) => event,
        Ok(Line::Eof) => {
            let tail = shell.stderr_tail.lock().unwrap().iter().rev().take(3).rev().cloned().collect::<Vec<_>>().join("\n");
            return failed(format!("The backend stopped before it started.\n{tail}"));
        }
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
    if let Some(backend) = shell.backend.lock().unwrap().as_mut() {
        backend.port = Some(port);
    }
    // 200 alone is not enough: another server could answer on this port; the nonce ties it to this start.
    let started = Instant::now();
    loop {
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
    if let (Some(window), Ok(url)) = (app.get_webview_window(MAIN), Url::parse(&format!("http://127.0.0.1:{port}/"))) {
        let _ = window.navigate(url);
    }
    watch_exit(app.clone(), generation);
}

/// The backend's process ended while the shell runs: the "backend stopped" page. No automatic restart.
fn watch_exit(app: AppHandle, generation: u64) {
    thread::spawn(move || loop {
        thread::sleep(Duration::from_millis(250));
        let shell = app.state::<Shell>();
        if shell.quitting.load(Ordering::SeqCst) || shell.generation.load(Ordering::SeqCst) != generation {
            return;
        }
        let mut guard = shell.backend.lock().unwrap();
        let ended = match guard.as_mut() {
            Some(backend) => backend.child.try_wait().ok().flatten().is_some(),
            None => return,
        };
        if ended {
            guard.take();
            drop(guard);
            show_local(&app, "stopped");
            return;
        }
    });
}

/// A start that failed: a visible message with the log's place, then the backend (if any) is stopped and the app ends.
fn fail_start(app: &AppHandle, message: String) {
    let log = log_path(app);
    eprintln!("DEIXIS could not start: {message} (log: {log})");
    stop_backend(app);
    let text = format!("{message}\n\nLog: {log}");
    // DEIXIS_DESKTOP_NO_DIALOG=1 (the desktop acceptance): the message goes to stderr only, nothing waits for a click.
    if std::env::var("DEIXIS_DESKTOP_NO_DIALOG").as_deref() != Ok("1") {
        app.dialog().message(text).title("DEIXIS could not start").kind(MessageDialogKind::Error).blocking_show();
    }
    app.state::<Shell>().quitting.store(true, Ordering::SeqCst);
    app.exit(1);
}

/// Ask the backend to stop with the token and close the watchdog's stdin (its signal that the shell is going), then
/// wait for the watchdog: it waits for the backend, kills what is left by verified identity and exits. Only the
/// watchdog, this shell's own unreaped child, is ever signalled from here, and only if it has not ended in time.
fn stop_backend(app: &AppHandle) {
    let shell = app.state::<Shell>();
    let Some(mut backend) = shell.backend.lock().unwrap().take() else { return };
    if let Some(port) = backend.port {
        let _ = http(port, "POST", "/api/internal/shutdown", Some(&backend.token), Duration::from_secs(2));
    }
    backend.stdin.take();
    let ends = Instant::now() + SHUTDOWN_WAIT + REAPER_WAIT;
    while Instant::now() < ends {
        if backend.child.try_wait().ok().flatten().is_some() {
            return;
        }
        thread::sleep(Duration::from_millis(100));
    }
    eprintln!("DEIXIS: the watchdog did not finish in time; stopping it");
    let _ = backend.child.kill();
    let _ = backend.child.wait();
}

fn quit(app: AppHandle) {
    let shell = app.state::<Shell>();
    if shell.quitting.swap(true, Ordering::SeqCst) {
        return;
    }
    thread::spawn(move || {
        stop_backend(&app);
        app.exit(0);
    });
}

/// One restart at a time; a second click while one runs is dropped.
fn restart(app: AppHandle) {
    if app.state::<Shell>().restarting.swap(true, Ordering::SeqCst) {
        return;
    }
    thread::spawn(move || {
        stop_backend(&app);
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
    let port = backend_port(app);
    port.is_some() && url.scheme() == "http" && url.host_str() == Some("127.0.0.1") && url.port() == port
}

fn local_page(url: &Url) -> bool {
    url.scheme() == "tauri" && url.host_str() == Some("localhost") && url.path() == "/index.html"
}

/// A download from the backend's page: a blob: or data: URL made by the page, or the backend's own origin. The file
/// goes where WebKit's default put it (~/Downloads, `name (n).ext` when the name is taken); anything else is refused.
fn on_download(app: &AppHandle, event: DownloadEvent<'_>) -> bool {
    let shell = app.state::<Shell>();
    match event {
        DownloadEvent::Requested { url, destination } => {
            let from_page = match url.scheme() {
                "blob" => Url::parse(url.path()).is_ok_and(|inner| own_origin(app, &inner)),
                "data" => Url::parse(&shell.page.lock().unwrap()).is_ok_and(|shown| own_origin(app, &shown)),
                _ => own_origin(app, &url),
            };
            let folder = PathBuf::from(std::env::var("HOME").unwrap_or_default()).join("Downloads");
            let named = destination.file_name().is_some() && destination.parent() == Some(folder.as_path());
            if !from_page || !named || std::fs::create_dir_all(&folder).is_err() {
                notify(app, "Download not saved", format!("DEIXIS did not save this download ({}).", destination.display()), true);
                return false;
            }
            shell.downloads.lock().unwrap().insert(url.to_string(), destination.clone());
            true
        }
        DownloadEvent::Finished { url, success, .. } => {
            let path = shell.downloads.lock().unwrap().remove(url.as_str());
            let shown = path.as_ref().map(|p| p.display().to_string()).unwrap_or_else(|| "~/Downloads".into());
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

/// The menu-bar count, read with the token from the backend's read-only status route.
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

/// What the window may show: the shell's own page (tauri://localhost/index.html) and the backend's origin. The local
/// page's Restart and Quit links act only while that page is the one shown; every other URL is cancelled, and a web or
/// mail link opens outside.
fn on_navigation(app: &AppHandle, url: &Url) -> bool {
    if url.scheme() == "tauri" && url.host_str() == Some("localhost") {
        let shown = Url::parse(&app.state::<Shell>().page.lock().unwrap()).ok();
        match url.path() {
            "/index.html" => return true,
            "/action/restart" if shown.as_ref().is_some_and(local_page) => restart(app.clone()),
            "/action/quit" if shown.as_ref().is_some_and(local_page) => quit(app.clone()),
            _ => {}
        }
        return false;
    }
    if own_origin(app, url) {
        return true;
    }
    if url.scheme() == "https" || url.scheme() == "http" || url.scheme() == "mailto" {
        let _ = Command::new("/usr/bin/open").arg(url.as_str()).spawn(); // another site: the default browser
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
                // Closing the window keeps DEIXIS running in the menu bar; Quit ends it.
                if !window.app_handle().state::<Shell>().quitting.load(Ordering::SeqCst) {
                    api.prevent_close();
                    let _ = window.hide();
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
            // process ends. The watchdog would stop everything anyway once stdin closes; this keeps the token shutdown.
            if !app.state::<Shell>().quitting.swap(true, Ordering::SeqCst) {
                stop_backend(app);
            }
        }
        RunEvent::Reopen { .. } => show_main(app),
        _ => {}
    });
}
