/**
 * Thin desktop capability adapter.
 * Browser / PWA / phone clients degrade gracefully when Tauri is unavailable.
 */

export type BackendLifecycleStatus =
  | "starting"
  | "ready"
  | "model_loading"
  | "degraded"
  | "backend_failed"
  | "backend_stopped"
  | "unknown"

export type ObsidianEmbedState =
  | "idle"
  | "launching"
  | "embedded"
  | "failed"
  | "unsupported_platform"

export type ObsidianProbeResult = {
  installed: boolean
  exe_path: string | null
  platform_embed_supported: boolean
  message: string
}

export type ObsidianEmbedStatus = {
  state: ObsidianEmbedState
  message: string
  obsidian_hwnd: number | null
}

export type ObsidianEmbedBounds = {
  vault_path?: string
  x: number
  y: number
  width: number
  height: number
}

type TauriInvoke = (cmd: string, args?: Record<string, unknown>) => Promise<unknown>

function getInvoke(): TauriInvoke | null {
  const w = window as Window & {
    __TAURI__?: { core?: { invoke?: TauriInvoke } }
    __TAURI_INTERNALS__?: { invoke?: TauriInvoke }
  }
  if (w.__TAURI_INTERNALS__?.invoke) return w.__TAURI_INTERNALS__.invoke.bind(w.__TAURI_INTERNALS__)
  if (w.__TAURI__?.core?.invoke) return w.__TAURI__.core.invoke.bind(w.__TAURI__.core)
  return null
}

export const DesktopBridge = {
  isDesktop(): boolean {
    return getInvoke() !== null || navigator.userAgent.includes("Tauri")
  },

  async appVersion(): Promise<string | null> {
    const invoke = getInvoke()
    if (!invoke) return null
    try {
      return String(await invoke("app_version"))
    } catch {
      return null
    }
  },

  async backendStatus(): Promise<BackendLifecycleStatus> {
    const invoke = getInvoke()
    if (!invoke) return "unknown"
    try {
      return (await invoke("backend_status")) as BackendLifecycleStatus
    } catch {
      return "unknown"
    }
  },

  async minimize(): Promise<boolean> {
    const invoke = getInvoke()
    if (!invoke) return false
    try {
      await invoke("minimize_window")
      return true
    } catch {
      return false
    }
  },

  async showWindow(): Promise<boolean> {
    const invoke = getInvoke()
    if (!invoke) return false
    try {
      await invoke("show_window")
      return true
    } catch {
      return false
    }
  },

  async hideWindow(): Promise<boolean> {
    const invoke = getInvoke()
    if (!invoke) return false
    try {
      await invoke("hide_window")
      return true
    } catch {
      return false
    }
  },

  async startBackend(): Promise<boolean> {
    const invoke = getInvoke()
    if (!invoke) return false
    try {
      await invoke("start_backend")
      return true
    } catch {
      return false
    }
  },

  async stopBackend(): Promise<boolean> {
    const invoke = getInvoke()
    if (!invoke) return false
    try {
      await invoke("stop_backend")
      return true
    } catch {
      return false
    }
  },

  async restartBackend(): Promise<boolean> {
    const invoke = getInvoke()
    if (!invoke) return false
    try {
      await invoke("restart_backend")
      return true
    } catch {
      return false
    }
  },

  async openLogs(): Promise<boolean> {
    const invoke = getInvoke()
    if (!invoke) return false
    try {
      await invoke("open_logs")
      return true
    } catch {
      return false
    }
  },

  async setAutostart(enabled: boolean): Promise<boolean> {
    const invoke = getInvoke()
    if (!invoke) return false
    try {
      await invoke("set_autostart", { enabled })
      return true
    } catch {
      return false
    }
  },

  async getAutostart(): Promise<boolean | null> {
    const invoke = getInvoke()
    if (!invoke) return null
    try {
      return Boolean(await invoke("get_autostart"))
    } catch {
      return null
    }
  },

  async setCloseToTray(enabled: boolean): Promise<boolean> {
    const invoke = getInvoke()
    if (!invoke) return false
    try {
      await invoke("set_close_to_tray", { enabled })
      return true
    } catch {
      return false
    }
  },

  async quitJarvis(): Promise<boolean> {
    const invoke = getInvoke()
    if (!invoke) return false
    try {
      await invoke("quit_jarvis")
      return true
    } catch {
      return false
    }
  },

  async dataPaths(): Promise<Record<string, string> | null> {
    const invoke = getInvoke()
    if (!invoke) return null
    try {
      return (await invoke("data_paths")) as Record<string, string>
    } catch {
      return null
    }
  },

  async obsidianProbe(): Promise<ObsidianProbeResult | null> {
    const invoke = getInvoke()
    if (!invoke) return null
    try {
      return (await invoke("obsidian_probe")) as ObsidianProbeResult
    } catch {
      return null
    }
  },

  async obsidianBoundVaultPath(): Promise<string | null> {
    const invoke = getInvoke()
    if (!invoke) return null
    try {
      const path = await invoke("obsidian_bound_vault_path")
      return typeof path === "string" && path.trim() ? path.trim() : null
    } catch {
      return null
    }
  },

  async obsidianEmbedStart(bounds: ObsidianEmbedBounds): Promise<ObsidianEmbedStatus | null> {
    const invoke = getInvoke()
    if (!invoke) return null
    try {
      return (await invoke("obsidian_embed_start", { bounds })) as ObsidianEmbedStatus
    } catch {
      return null
    }
  },

  async obsidianEmbedResize(bounds: ObsidianEmbedBounds): Promise<ObsidianEmbedStatus | null> {
    const invoke = getInvoke()
    if (!invoke) return null
    try {
      return (await invoke("obsidian_embed_resize", { bounds })) as ObsidianEmbedStatus
    } catch {
      return null
    }
  },

  async obsidianEmbedStop(): Promise<ObsidianEmbedStatus | null> {
    const invoke = getInvoke()
    if (!invoke) return null
    try {
      return (await invoke("obsidian_embed_stop")) as ObsidianEmbedStatus
    } catch {
      return null
    }
  },

  async obsidianFocusNote(relPath: string, vaultPath?: string): Promise<boolean> {
    const invoke = getInvoke()
    if (!invoke) return false
    try {
      await invoke("obsidian_focus_note", {
        relPath,
        vaultPath: vaultPath?.trim() || null,
      })
      return true
    } catch {
      return false
    }
  },

  async obsidianOpenInstall(): Promise<boolean> {
    const invoke = getInvoke()
    if (!invoke) return false
    try {
      await invoke("obsidian_open_install")
      return true
    } catch {
      return false
    }
  },
}

/** Pure helpers exported for unit tests (no window dependency). */
export function browserBridgeFallback(): {
  isDesktop: boolean
  backendStatus: BackendLifecycleStatus
} {
  return { isDesktop: false, backendStatus: "unknown" }
}
