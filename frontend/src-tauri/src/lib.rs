//! Jarvis Tauri desktop shell: embeds the React portal and owns backend lifecycle.

use once_cell::sync::Lazy;
use serde::Serialize;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Manager, State, WindowEvent,
};
use tauri_plugin_autostart::MacosLauncher;

const HEALTH_URL: &str = "http://127.0.0.1:4780/api/health";
const MAX_START_ATTEMPTS: u32 = 3;
const HEALTH_TIMEOUT_SECS: u64 = 90;
const RESTART_BACKOFF_MS: u64 = 1500;

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum BackendLifecycleStatus {
    Starting,
    Ready,
    ModelLoading,
    Degraded,
    BackendFailed,
    BackendStopped,
    Unknown,
}

struct BackendState {
    child: Option<Child>,
    owned: bool,
    status: BackendLifecycleStatus,
    last_error: String,
    restart_count: u32,
    close_to_tray: bool,
    start_minimized: bool,
}

impl Default for BackendState {
    fn default() -> Self {
        Self {
            child: None,
            owned: false,
            status: BackendLifecycleStatus::Unknown,
            last_error: String::new(),
            restart_count: 0,
            close_to_tray: true,
            start_minimized: false,
        }
    }
}

struct AppState {
    backend: Mutex<BackendState>,
}

static HTTP: Lazy<reqwest::blocking::Client> = Lazy::new(|| {
    reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(3))
        .build()
        .expect("http client")
});

fn jarvis_root() -> PathBuf {
    if let Ok(p) = std::env::var("JARVIS_ROOT") {
        return PathBuf::from(p);
    }
    // Installed layout: next to Jarvis.exe → ../  or portable: repo root when developing.
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            // Prefer sibling data/ marker or sidecars folder.
            let candidate = dir.to_path_buf();
            if candidate.join("data").exists() || candidate.join("sidecars").exists() {
                return candidate;
            }
            if let Some(parent) = dir.parent() {
                if parent.join("backend").exists() || parent.join("data").exists() {
                    return parent.to_path_buf();
                }
            }
            return candidate;
        }
    }
    std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

fn logs_dir() -> PathBuf {
    let p = jarvis_root().join("logs");
    let _ = fs::create_dir_all(&p);
    p
}

fn data_dir() -> PathBuf {
    let p = jarvis_root().join("data");
    let _ = fs::create_dir_all(&p);
    p
}

fn health_ok() -> bool {
    match HTTP.get(HEALTH_URL).send() {
        Ok(resp) => resp.status().is_success(),
        Err(_) => false,
    }
}

fn backend_command(root: &Path) -> Option<(PathBuf, Vec<String>)> {
    // Prefer packaged sidecar next to the app / in resources.
    let candidates = [
        root.join("sidecars").join("jarvis-backend.exe"),
        root.join("sidecars").join("jarvis-backend"),
        root.join("jarvis-backend").join("jarvis-backend.exe"),
        root.join("runtime").join("backend").join("jarvis-backend.exe"),
    ];
    for exe in candidates {
        if exe.exists() {
            return Some((exe, vec![]));
        }
    }
    // Dev fallback: python -m uvicorn (developers still have Python).
    let python = if cfg!(windows) {
        root.join(".venv").join("Scripts").join("python.exe")
    } else {
        root.join(".venv").join("bin").join("python")
    };
    let py = if python.exists() {
        python
    } else {
        PathBuf::from(if cfg!(windows) { "python" } else { "python3" })
    };
    let args = vec![
        "-m".into(),
        "uvicorn".into(),
        "app.main:app".into(),
        "--host".into(),
        "127.0.0.1".into(),
        "--port".into(),
        "4780".into(),
        "--app-dir".into(),
        root.join("backend").to_string_lossy().to_string(),
    ];
    Some((py, args))
}

fn spawn_backend(state: &mut BackendState) -> Result<(), String> {
    if health_ok() {
        state.owned = false;
        state.status = BackendLifecycleStatus::Ready;
        state.last_error.clear();
        return Ok(());
    }
    let root = jarvis_root();
    let (exe, args) = backend_command(&root).ok_or_else(|| "No backend binary found".to_string())?;
    let log_path = logs_dir().join("backend.sidecar.log");
    let err_path = logs_dir().join("backend.sidecar.err.log");
    let stdout = fs::File::create(&log_path).map_err(|e| e.to_string())?;
    let stderr = fs::File::create(&err_path).map_err(|e| e.to_string())?;

    let mut cmd = Command::new(&exe);
    cmd.args(&args)
        .current_dir(&root)
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr))
        .env("JARVIS_ROOT", root.as_os_str());
    // Avoid double-loading models if the shell will surface status separately.
    // Leave auto_load to settings unless JARVIS_SKIP_MODEL is set by the environment.

    match cmd.spawn() {
        Ok(child) => {
            state.child = Some(child);
            state.owned = true;
            state.status = BackendLifecycleStatus::Starting;
            state.last_error.clear();
            Ok(())
        }
        Err(err) => {
            state.status = BackendLifecycleStatus::BackendFailed;
            state.last_error = format!(
                "Failed to start backend ({exe:?}): {err}. Logs: {}",
                log_path.display()
            );
            Err(state.last_error.clone())
        }
    }
}

fn wait_for_health(state: &mut BackendState) -> bool {
    let deadline = Instant::now() + Duration::from_secs(HEALTH_TIMEOUT_SECS);
    while Instant::now() < deadline {
        if health_ok() {
            state.status = BackendLifecycleStatus::Ready;
            state.restart_count = 0;
            return true;
        }
        // If owned child exited early, fail fast.
        if let Some(child) = state.child.as_mut() {
            if let Ok(Some(status)) = child.try_wait() {
                state.status = BackendLifecycleStatus::BackendFailed;
                state.last_error = format!(
                    "Backend exited during startup ({status}). See {}",
                    logs_dir().join("backend.sidecar.err.log").display()
                );
                return false;
            }
        }
        thread::sleep(Duration::from_millis(500));
    }
    state.status = BackendLifecycleStatus::BackendFailed;
    state.last_error = format!(
        "Timed out waiting for {HEALTH_URL}. Logs: {}",
        logs_dir().display()
    );
    false
}

fn ensure_backend(state: &mut BackendState) {
    if health_ok() {
        state.status = BackendLifecycleStatus::Ready;
        return;
    }
    if state.restart_count >= MAX_START_ATTEMPTS {
        state.status = BackendLifecycleStatus::BackendFailed;
        if state.last_error.is_empty() {
            state.last_error = format!(
                "Backend failed after {MAX_START_ATTEMPTS} attempts. Logs: {}",
                logs_dir().display()
            );
        }
        return;
    }
    state.restart_count += 1;
    state.status = BackendLifecycleStatus::Starting;
    if let Err(err) = spawn_backend(state) {
        state.last_error = err;
        return;
    }
    if !wait_for_health(state) {
        // Bounded backoff before caller may retry.
        thread::sleep(Duration::from_millis(RESTART_BACKOFF_MS));
    }
}

fn stop_owned_backend(state: &mut BackendState) {
    if !state.owned {
        state.status = BackendLifecycleStatus::BackendStopped;
        return;
    }
    if let Some(mut child) = state.child.take() {
        let _ = child.kill();
        let _ = child.wait();
    }
    state.owned = false;
    state.status = BackendLifecycleStatus::BackendStopped;
}

fn show_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

fn hide_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.hide();
    }
}

#[tauri::command]
fn app_version(app: AppHandle) -> String {
    app.package_info().version.to_string()
}

#[tauri::command]
fn backend_status(state: State<'_, AppState>) -> BackendLifecycleStatus {
    state
        .backend
        .lock()
        .map(|g| g.status.clone())
        .unwrap_or(BackendLifecycleStatus::Unknown)
}

#[tauri::command]
fn minimize_window(app: AppHandle) -> Result<(), String> {
    app.get_webview_window("main")
        .ok_or_else(|| "window missing".to_string())?
        .minimize()
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn show_window(app: AppHandle) -> Result<(), String> {
    show_main(&app);
    Ok(())
}

#[tauri::command]
fn hide_window(app: AppHandle) -> Result<(), String> {
    hide_main(&app);
    Ok(())
}

#[tauri::command]
fn start_backend(state: State<'_, AppState>) -> Result<(), String> {
    let mut guard = state.backend.lock().map_err(|e| e.to_string())?;
    guard.restart_count = 0;
    ensure_backend(&mut guard);
    if matches!(
        guard.status,
        BackendLifecycleStatus::Ready | BackendLifecycleStatus::Degraded | BackendLifecycleStatus::ModelLoading
    ) {
        Ok(())
    } else {
        Err(guard.last_error.clone())
    }
}

#[tauri::command]
fn stop_backend(state: State<'_, AppState>) -> Result<(), String> {
    let mut guard = state.backend.lock().map_err(|e| e.to_string())?;
    stop_owned_backend(&mut guard);
    Ok(())
}

#[tauri::command]
fn restart_backend(state: State<'_, AppState>) -> Result<(), String> {
    let mut guard = state.backend.lock().map_err(|e| e.to_string())?;
    stop_owned_backend(&mut guard);
    thread::sleep(Duration::from_millis(400));
    guard.restart_count = 0;
    ensure_backend(&mut guard);
    if matches!(guard.status, BackendLifecycleStatus::Ready) {
        Ok(())
    } else {
        Err(guard.last_error.clone())
    }
}

#[tauri::command]
fn open_logs() -> Result<(), String> {
    let path = logs_dir();
    open::that(&path).map_err(|e| e.to_string())
}

#[tauri::command]
fn set_autostart(app: AppHandle, enabled: bool) -> Result<(), String> {
    #[cfg(desktop)]
    {
        use tauri_plugin_autostart::ManagerExt;
        let autostart = app.autolaunch();
        if enabled {
            autostart.enable().map_err(|e| e.to_string())?;
        } else {
            autostart.disable().map_err(|e| e.to_string())?;
        }
        Ok(())
    }
    #[cfg(not(desktop))]
    {
        let _ = (app, enabled);
        Err("autostart unavailable".into())
    }
}

#[tauri::command]
fn get_autostart(app: AppHandle) -> Result<bool, String> {
    #[cfg(desktop)]
    {
        use tauri_plugin_autostart::ManagerExt;
        app.autolaunch().is_enabled().map_err(|e| e.to_string())
    }
    #[cfg(not(desktop))]
    {
        let _ = app;
        Ok(false)
    }
}

#[tauri::command]
fn set_close_to_tray(state: State<'_, AppState>, enabled: bool) -> Result<(), String> {
    let mut guard = state.backend.lock().map_err(|e| e.to_string())?;
    guard.close_to_tray = enabled;
    // Persist preference beside other Jarvis data.
    let path = data_dir().join("desktop_shell.json");
    let payload = serde_json::json!({
        "close_to_tray": guard.close_to_tray,
        "start_minimized": guard.start_minimized,
    });
    fs::write(path, payload.to_string()).map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
fn quit_jarvis(app: AppHandle, state: State<'_, AppState>) -> Result<(), String> {
    {
        let mut guard = state.backend.lock().map_err(|e| e.to_string())?;
        stop_owned_backend(&mut guard);
    }
    app.exit(0);
    Ok(())
}

#[tauri::command]
fn data_paths() -> Result<serde_json::Value, String> {
    let root = jarvis_root();
    Ok(serde_json::json!({
        "root": root,
        "data": root.join("data"),
        "logs": root.join("logs"),
        "models": root.join("models"),
        "runtime": root.join("runtime").join("llama.cpp"),
    }))
}

fn load_shell_prefs(state: &mut BackendState) {
    let path = data_dir().join("desktop_shell.json");
    if let Ok(raw) = fs::read_to_string(path) {
        if let Ok(v) = serde_json::from_str::<serde_json::Value>(&raw) {
            if let Some(b) = v.get("close_to_tray").and_then(|x| x.as_bool()) {
                state.close_to_tray = b;
            }
            if let Some(b) = v.get("start_minimized").and_then(|x| x.as_bool()) {
                state.start_minimized = b;
            }
        }
    }
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            Some(vec![]),
        ))
        .manage(AppState {
            backend: Mutex::new(BackendState::default()),
        })
        .setup(|app| {
            {
                let state = app.state::<AppState>();
                let mut guard = state.backend.lock().expect("backend lock");
                load_shell_prefs(&mut guard);
                ensure_backend(&mut guard);
                let start_minimized = guard.start_minimized;
                drop(guard);
                if start_minimized {
                    hide_main(app.handle());
                }
            }

            let show_i = MenuItem::with_id(app, "show", "Show Jarvis", true, None::<&str>)?;
            let hide_i = MenuItem::with_id(app, "hide", "Hide Jarvis", true, None::<&str>)?;
            let start_i = MenuItem::with_id(app, "start_backend", "Start backend", true, None::<&str>)?;
            let stop_i = MenuItem::with_id(app, "stop_backend", "Stop backend", true, None::<&str>)?;
            let restart_i =
                MenuItem::with_id(app, "restart_backend", "Restart backend", true, None::<&str>)?;
            let logs_i = MenuItem::with_id(app, "open_logs", "Open logs", true, None::<&str>)?;
            let quit_i = MenuItem::with_id(app, "quit", "Quit Jarvis", true, None::<&str>)?;
            let menu = Menu::with_items(
                app,
                &[&show_i, &hide_i, &start_i, &stop_i, &restart_i, &logs_i, &quit_i],
            )?;

            let _tray = TrayIconBuilder::new()
                .menu(&menu)
                .tooltip("Jarvis")
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => show_main(app),
                    "hide" => hide_main(app),
                    "start_backend" => {
                        if let Ok(mut g) = app.state::<AppState>().backend.lock() {
                            g.restart_count = 0;
                            ensure_backend(&mut g);
                        }
                    }
                    "stop_backend" => {
                        if let Ok(mut g) = app.state::<AppState>().backend.lock() {
                            stop_owned_backend(&mut g);
                        }
                    }
                    "restart_backend" => {
                        if let Ok(mut g) = app.state::<AppState>().backend.lock() {
                            stop_owned_backend(&mut g);
                            thread::sleep(Duration::from_millis(400));
                            g.restart_count = 0;
                            ensure_backend(&mut g);
                        }
                    }
                    "open_logs" => {
                        let _ = open::that(logs_dir());
                    }
                    "quit" => {
                        if let Ok(mut g) = app.state::<AppState>().backend.lock() {
                            stop_owned_backend(&mut g);
                        }
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        show_main(tray.app_handle());
                    }
                })
                .build(app)?;

            // Watchdog: if owned backend dies, attempt bounded restart.
            let handle = app.handle().clone();
            thread::spawn(move || loop {
                thread::sleep(Duration::from_secs(5));
                let state = handle.state::<AppState>();
                let Ok(mut guard) = state.backend.lock() else {
                    continue;
                };
                if !guard.owned {
                    if health_ok() {
                        guard.status = BackendLifecycleStatus::Ready;
                    }
                    continue;
                }
                let dead = guard
                    .child
                    .as_mut()
                    .and_then(|c| c.try_wait().ok().flatten())
                    .is_some();
                if dead {
                    guard.child = None;
                    if guard.restart_count < MAX_START_ATTEMPTS {
                        ensure_backend(&mut guard);
                    } else {
                        guard.status = BackendLifecycleStatus::BackendFailed;
                        guard.last_error = format!(
                            "Backend crashed repeatedly. Logs: {}",
                            logs_dir().display()
                        );
                    }
                } else if !health_ok()
                    && matches!(guard.status, BackendLifecycleStatus::Ready)
                {
                    guard.status = BackendLifecycleStatus::Degraded;
                } else if health_ok() {
                    guard.status = BackendLifecycleStatus::Ready;
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                let app = window.app_handle();
                let close_to_tray = app
                    .state::<AppState>()
                    .backend
                    .lock()
                    .map(|g| g.close_to_tray)
                    .unwrap_or(true);
                if close_to_tray {
                    api.prevent_close();
                    let _ = window.hide();
                } else {
                    // Closing the window without close-to-tray still leaves backend if owned;
                    // use Quit Jarvis to stop owned processes.
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            app_version,
            backend_status,
            minimize_window,
            show_window,
            hide_window,
            start_backend,
            stop_backend,
            restart_backend,
            open_logs,
            set_autostart,
            get_autostart,
            set_close_to_tray,
            quit_jarvis,
            data_paths,
        ])
        .run(tauri::generate_context!())
        .expect("error while running Jarvis desktop shell");
}
