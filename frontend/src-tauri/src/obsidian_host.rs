//! RFC-0107: Native host for the real Obsidian.exe UI inside Jarvis Desktop (Windows).

use serde::Serialize;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ObsidianEmbedState {
    Idle,
    Launching,
    Embedded,
    Failed,
    UnsupportedPlatform,
}

#[derive(Clone, Debug, Serialize)]
pub struct ObsidianProbeResult {
    pub installed: bool,
    pub exe_path: Option<String>,
    pub platform_embed_supported: bool,
    pub message: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct ObsidianEmbedStatus {
    pub state: ObsidianEmbedState,
    pub message: String,
    pub obsidian_hwnd: Option<isize>,
}

struct HostRuntime {
    state: ObsidianEmbedState,
    message: String,
    vault_path: String,
    host_hwnd: Option<isize>,
    obsidian_hwnd: Option<isize>,
}

static RUNTIME: Mutex<HostRuntime> = Mutex::new(HostRuntime {
    state: ObsidianEmbedState::Idle,
    message: String::new(),
    vault_path: String::new(),
    host_hwnd: None,
    obsidian_hwnd: None,
});

pub fn read_bound_vault_path(data_root: &Path) -> Option<String> {
    let settings = data_root.join("settings.json");
    let raw = std::fs::read_to_string(settings).ok()?;
    let v: serde_json::Value = serde_json::from_str(&raw).ok()?;
    let path = v
        .get("knowledge_vault")
        .and_then(|kv| kv.get("vault_path"))
        .and_then(|p| p.as_str())
        .unwrap_or("")
        .trim();
    if path.is_empty() {
        None
    } else {
        Some(path.to_string())
    }
}

#[cfg(not(target_os = "windows"))]
pub fn probe_install() -> ObsidianProbeResult {
    ObsidianProbeResult {
        installed: false,
        exe_path: None,
        platform_embed_supported: false,
        message: "Obsidian in-Jarvis embed requires Jarvis Desktop on Windows.".into(),
    }
}

#[cfg(not(target_os = "windows"))]
pub fn embed_start(
    _parent_hwnd: isize,
    _vault_path: &str,
    _x: i32,
    _y: i32,
    _width: i32,
    _height: i32,
) -> ObsidianEmbedStatus {
    let mut guard = RUNTIME.lock().expect("obsidian runtime");
    guard.state = ObsidianEmbedState::UnsupportedPlatform;
    guard.message = "Obsidian embed is only available in Jarvis Desktop on Windows.".into();
    ObsidianEmbedStatus {
        state: guard.state.clone(),
        message: guard.message.clone(),
        obsidian_hwnd: None,
    }
}

#[cfg(not(target_os = "windows"))]
pub fn embed_resize(_x: i32, _y: i32, _width: i32, _height: i32) -> ObsidianEmbedStatus {
    embed_start(0, "", 0, 0, 0, 0)
}

#[cfg(not(target_os = "windows"))]
pub fn embed_stop() -> ObsidianEmbedStatus {
    let mut guard = RUNTIME.lock().expect("obsidian runtime");
    guard.state = ObsidianEmbedState::Idle;
    guard.message.clear();
    ObsidianEmbedStatus {
        state: guard.state.clone(),
        message: guard.message.clone(),
        obsidian_hwnd: None,
    }
}

#[cfg(not(target_os = "windows"))]
pub fn focus_note(_vault_path: &str, _rel_path: &str) -> Result<(), String> {
    Err("Obsidian focus requires Jarvis Desktop on Windows.".into())
}

#[cfg(not(target_os = "windows"))]
pub fn open_install_page() -> Result<(), String> {
    open::that("https://obsidian.md/download").map_err(|e| e.to_string())
}

#[cfg(target_os = "windows")]
mod win {
    use super::*;
    use std::process::Command;
    use std::thread;
    use std::time::{Duration, Instant};
    use windows::core::PCWSTR;
    use windows::Win32::Foundation::{BOOL, HWND, LPARAM, TRUE};
    use windows::Win32::System::Threading::{
        OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION,
    };
    use windows::Win32::UI::WindowsAndMessaging::{
        CreateWindowExW, EnumWindows, GetClientRect, GetWindowLongPtrW, GetWindowThreadProcessId,
        IsWindowVisible, MoveWindow, SetParent, SetWindowLongPtrW, SetWindowPos, ShowWindow,
        GWL_STYLE, SWP_NOZORDER, SW_SHOW, WINDOW_EX_STYLE, WINDOW_STYLE, WS_CHILD, WS_CLIPCHILDREN,
        WS_VISIBLE,
    };

    const HOST_CLASS: PCWSTR = windows::core::w!("JarvisObsidianHost");
    static HOST_CLASS_REGISTERED: Mutex<bool> = Mutex::new(false);

    fn find_obsidian_exe() -> Option<PathBuf> {
        let local = std::env::var("LOCALAPPDATA").ok().map(PathBuf::from);
        let candidates: Vec<PathBuf> = [
            local
                .as_ref()
                .map(|p| p.join("Programs").join("Obsidian").join("Obsidian.exe")),
            local
                .as_ref()
                .map(|p| p.join("obsidian").join("Obsidian.exe")),
            Some(PathBuf::from(
                r"C:\Program Files\Obsidian\Obsidian.exe",
            )),
            Some(PathBuf::from(
                r"C:\Program Files (x86)\Obsidian\Obsidian.exe",
            )),
        ]
        .into_iter()
        .flatten()
        .collect();
        for path in candidates {
            if path.is_file() {
                return Some(path);
            }
        }
        None
    }

    pub fn probe_install() -> ObsidianProbeResult {
        match find_obsidian_exe() {
            Some(exe) => ObsidianProbeResult {
                installed: true,
                exe_path: Some(exe.to_string_lossy().to_string()),
                platform_embed_supported: true,
                message: "Obsidian found. Jarvis can host the real Obsidian UI for your bound vault.".into(),
            },
            None => ObsidianProbeResult {
                installed: false,
                exe_path: None,
                platform_embed_supported: true,
                message: "Obsidian is not installed. Install Obsidian to embed your vault inside Jarvis.".into(),
            },
        }
    }

    fn register_host_class() -> Result<(), String> {
        let mut registered = HOST_CLASS_REGISTERED.lock().expect("host class");
        if *registered {
            return Ok(());
        }
        use windows::Win32::System::LibraryLoader::GetModuleHandleW;
        use windows::Win32::UI::WindowsAndMessaging::{
            DefWindowProcW, RegisterClassW, WNDCLASSW,
        };
        unsafe {
            let hmodule = GetModuleHandleW(None).map_err(|e| e.to_string())?;
            let wc = WNDCLASSW {
                lpfnWndProc: Some(DefWindowProcW),
                hInstance: hmodule.into(),
                lpszClassName: HOST_CLASS,
                style: Default::default(),
                cbClsExtra: 0,
                cbWndExtra: 0,
                hIcon: Default::default(),
                hCursor: Default::default(),
                hbrBackground: Default::default(),
                lpszMenuName: PCWSTR::null(),
            };
            if RegisterClassW(&wc) == 0 {
                // Class may already exist from a prior session.
            }
        }
        *registered = true;
        Ok(())
    }

    fn create_host_panel(parent: HWND, x: i32, y: i32, width: i32, height: i32) -> Result<HWND, String> {
        register_host_class()?;
        unsafe {
            let hwnd = CreateWindowExW(
                WINDOW_EX_STYLE::default(),
                HOST_CLASS,
                windows::core::w!("JarvisObsidianHost"),
                WINDOW_STYLE(WS_CHILD.0 | WS_VISIBLE.0 | WS_CLIPCHILDREN.0),
                x,
                y,
                width.max(320),
                height.max(240),
                parent,
                None,
                None,
                None,
            );
            if hwnd.0 == 0 {
                return Err("Failed to create Obsidian host panel.".into());
            }
            let _ = ShowWindow(hwnd, SW_SHOW);
            Ok(hwnd)
        }
    }

    fn launch_obsidian(exe: &Path, vault_path: &str) -> Result<(), String> {
        let vault = Path::new(vault_path);
        if !vault.is_dir() {
            return Err("Bound vault path is missing on disk.".into());
        }
        Command::new(exe)
            .arg(vault)
            .spawn()
            .map_err(|e| format!("Failed to launch Obsidian: {e}"))?;
        Ok(())
    }

    fn process_image_name(pid: u32) -> Option<String> {
        unsafe {
            let handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid);
            if handle.is_err() {
                return None;
            }
            let handle = handle.unwrap();
            let mut buf = [0u16; 260];
            let mut len = buf.len() as u32;
            let ok = windows::Win32::System::Threading::QueryFullProcessImageNameW(
                handle,
                windows::Win32::System::Threading::PROCESS_NAME_FORMAT::default(),
                windows::core::PWSTR(buf.as_mut_ptr()),
                &mut len,
            );
            if ok.is_err() {
                return None;
            }
            let path = String::from_utf16_lossy(&buf[..len as usize]);
            Some(path)
        }
    }

    struct EnumCtx {
        target: Option<HWND>,
    }

    unsafe extern "system" fn enum_obsidian(hwnd: HWND, lparam: LPARAM) -> BOOL {
        let ctx = &mut *(lparam.0 as *mut EnumCtx);
        if !IsWindowVisible(hwnd).as_bool() {
            return TRUE;
        }
        let mut pid = 0u32;
        GetWindowThreadProcessId(hwnd, Some(&mut pid));
        if pid == 0 {
            return TRUE;
        }
        if let Some(image) = process_image_name(pid) {
            if image.to_ascii_lowercase().contains("obsidian.exe") {
                ctx.target = Some(hwnd);
                return BOOL(0);
            }
        }
        TRUE
    }

    fn find_obsidian_main_window(timeout: Duration) -> Option<HWND> {
        let deadline = Instant::now() + timeout;
        while Instant::now() < deadline {
            let mut ctx = EnumCtx { target: None };
            unsafe {
                let _ = EnumWindows(Some(enum_obsidian), LPARAM(&mut ctx as *mut _ as isize));
            }
            if let Some(hwnd) = ctx.target {
                return Some(hwnd);
            }
            thread::sleep(Duration::from_millis(400));
        }
        None
    }

    fn reparent_obsidian(obsidian: HWND, host: HWND) -> Result<(), String> {
        unsafe {
            let style = GetWindowLongPtrW(obsidian, GWL_STYLE) as u32;
            let child_style = (style & !0x00CF0000) | WS_CHILD.0 | WS_VISIBLE.0;
            SetWindowLongPtrW(obsidian, GWL_STYLE, child_style as isize);
            SetParent(obsidian, host).map_err(|e| e.to_string())?;
            let mut rect = windows::Win32::Foundation::RECT::default();
            GetClientRect(host, &mut rect).map_err(|e| e.to_string())?;
            let w = rect.right - rect.left;
            let h = rect.bottom - rect.top;
            MoveWindow(obsidian, 0, 0, w, h, true).map_err(|e| e.to_string())?;
            let _ = ShowWindow(obsidian, SW_SHOW);
        }
        Ok(())
    }

    fn resize_embedded(host: HWND, obsidian: HWND) {
        unsafe {
            let mut rect = windows::Win32::Foundation::RECT::default();
            if GetClientRect(host, &mut rect).is_ok() {
                let w = rect.right - rect.left;
                let h = rect.bottom - rect.top;
                let _ = MoveWindow(obsidian, 0, 0, w, h, true);
                let _ = SetWindowPos(host, HWND::default(), 0, 0, 0, 0, SWP_NOZORDER);
            }
        }
    }

    pub fn embed_start(
        parent_hwnd: isize,
        vault_path: &str,
        x: i32,
        y: i32,
        width: i32,
        height: i32,
    ) -> ObsidianEmbedStatus {
        let mut guard = RUNTIME.lock().expect("obsidian runtime");
        guard.state = ObsidianEmbedState::Launching;
        guard.vault_path = vault_path.to_string();
        guard.message = "Launching Obsidian…".into();

        let exe = find_obsidian_exe();
        if exe.is_none() {
            guard.state = ObsidianEmbedState::Failed;
            guard.message = "Obsidian is not installed.".into();
            return ObsidianEmbedStatus {
                state: guard.state.clone(),
                message: guard.message.clone(),
                obsidian_hwnd: None,
            };
        }
        let exe = exe.unwrap();
        let parent = HWND(parent_hwnd as _);

        let host = match create_host_panel(parent, x, y, width, height) {
            Ok(h) => h,
            Err(err) => {
                guard.state = ObsidianEmbedState::Failed;
                guard.message = err;
                return ObsidianEmbedStatus {
                    state: guard.state.clone(),
                    message: guard.message.clone(),
                    obsidian_hwnd: None,
                };
            }
        };
        guard.host_hwnd = Some(host.0 as isize);

        if let Err(err) = launch_obsidian(&exe, vault_path) {
            guard.state = ObsidianEmbedState::Failed;
            guard.message = err;
            return ObsidianEmbedStatus {
                state: guard.state.clone(),
                message: guard.message.clone(),
                obsidian_hwnd: None,
            };
        }

        let obsidian = find_obsidian_main_window(Duration::from_secs(45));
        if obsidian.is_none() {
            guard.state = ObsidianEmbedState::Failed;
            guard.message =
                "Obsidian did not present a main window. Open Obsidian once manually, then retry."
                    .into();
            return ObsidianEmbedStatus {
                state: guard.state.clone(),
                message: guard.message.clone(),
                obsidian_hwnd: None,
            };
        }
        let obsidian = obsidian.unwrap();

        if let Err(err) = reparent_obsidian(obsidian, host) {
            guard.state = ObsidianEmbedState::Failed;
            guard.message = err;
            return ObsidianEmbedStatus {
                state: guard.state.clone(),
                message: guard.message.clone(),
                obsidian_hwnd: None,
            };
        }

        guard.obsidian_hwnd = Some(obsidian.0 as isize);
        guard.state = ObsidianEmbedState::Embedded;
        guard.message = "Obsidian is hosted inside Jarvis.".into();
        ObsidianEmbedStatus {
            state: guard.state.clone(),
            message: guard.message.clone(),
            obsidian_hwnd: guard.obsidian_hwnd,
        }
    }

    pub fn embed_resize(x: i32, y: i32, width: i32, height: i32) -> ObsidianEmbedStatus {
        let mut guard = RUNTIME.lock().expect("obsidian runtime");
        let host = guard.host_hwnd.map(|h| HWND(h as _));
        let obsidian = guard.obsidian_hwnd.map(|h| HWND(h as _));
        if let (Some(host), Some(obsidian)) = (host, obsidian) {
            unsafe {
                let _ = MoveWindow(host, x, y, width.max(320), height.max(240), true);
            }
            resize_embedded(host, obsidian);
        }
        ObsidianEmbedStatus {
            state: guard.state.clone(),
            message: guard.message.clone(),
            obsidian_hwnd: guard.obsidian_hwnd,
        }
    }

    pub fn embed_stop() -> ObsidianEmbedStatus {
        let mut guard = RUNTIME.lock().expect("obsidian runtime");
        if let Some(obsidian) = guard.obsidian_hwnd.map(|h| HWND(h as _)) {
            unsafe {
                let _ = SetParent(obsidian, HWND::default());
            }
        }
        guard.state = ObsidianEmbedState::Idle;
        guard.message.clear();
        guard.host_hwnd = None;
        guard.obsidian_hwnd = None;
        ObsidianEmbedStatus {
            state: guard.state.clone(),
            message: guard.message.clone(),
            obsidian_hwnd: None,
        }
    }

    fn pct_encode(input: &str) -> String {
        let mut out = String::new();
        for b in input.bytes() {
            match b {
                b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                    out.push(b as char);
                }
                _ => out.push_str(&format!("%{:02X}", b)),
            }
        }
        out
    }

    pub fn focus_note(vault_path: &str, rel_path: &str) -> Result<(), String> {
        let vault_name = Path::new(vault_path)
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("vault");
        let file = rel_path.trim().replace('\\', "/");
        let file = file.strip_suffix(".md").unwrap_or(&file);
        let uri = if file.is_empty() {
            format!("obsidian://open?vault={}", pct_encode(vault_name))
        } else {
            format!(
                "obsidian://open?vault={}&file={}",
                pct_encode(vault_name),
                pct_encode(file)
            )
        };
        open::that(uri).map_err(|e| e.to_string())
    }

    pub fn open_install_page() -> Result<(), String> {
        open::that("https://obsidian.md/download").map_err(|e| e.to_string())
    }
}

#[cfg(target_os = "windows")]
pub use win::{
    embed_resize, embed_start, embed_stop, focus_note, open_install_page, probe_install,
};
