import { useCallback, useEffect, useRef, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { DesktopBridge, type ObsidianEmbedStatus, type ObsidianProbeResult } from "../desktop/bridge"
import {
  fetchVaultHealth,
  fetchVaultStatus,
  readCachedVaultPath,
  type VaultHealthResponse,
  type VaultPublicStatus,
} from "../vault/vaultApi"
import { settingsSubmenuPath } from "../settings/settingsSubmenus"
import "../styles/obsidian-host.css"

function embedBoundsFromElement(el: HTMLElement, vaultPath: string) {
  const rect = el.getBoundingClientRect()
  const scale = window.devicePixelRatio || 1
  return {
    vault_path: vaultPath,
    x: Math.round(rect.left * scale),
    y: Math.round(rect.top * scale),
    width: Math.round(rect.width * scale),
    height: Math.round(rect.height * scale),
  }
}

export function ObsidianPage() {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const [searchParams] = useSearchParams()
  const focusNote = searchParams.get("focus") || ""

  const [status, setStatus] = useState<VaultPublicStatus | null>(null)
  const [health, setHealth] = useState<VaultHealthResponse | null>(null)
  const [probe, setProbe] = useState<ObsidianProbeResult | null>(null)
  const [embed, setEmbed] = useState<ObsidianEmbedStatus | null>(null)
  const [vaultPath, setVaultPath] = useState("")
  const [focusInput, setFocusInput] = useState(focusNote)
  const [busy, setBusy] = useState(false)
  const isDesktop = DesktopBridge.isDesktop()

  const refreshMeta = useCallback(async () => {
    const [st, h] = await Promise.all([fetchVaultStatus(), fetchVaultHealth()])
    setStatus(st)
    setHealth(h)
  }, [])

  useEffect(() => {
    void refreshMeta()
    const timer = window.setInterval(() => void refreshMeta(), 15000)
    return () => window.clearInterval(timer)
  }, [refreshMeta])

  useEffect(() => {
    setFocusInput(focusNote)
  }, [focusNote])

  useEffect(() => {
    if (!isDesktop) return
    void DesktopBridge.obsidianProbe().then(setProbe)
    void (async () => {
      const fromShell = await DesktopBridge.obsidianBoundVaultPath()
      setVaultPath(fromShell || readCachedVaultPath())
    })()
  }, [isDesktop])

  const resolveVaultPath = useCallback(async () => {
    const fromShell = await DesktopBridge.obsidianBoundVaultPath()
    const path = fromShell || readCachedVaultPath()
    setVaultPath(path)
    return path
  }, [])

  const startEmbed = useCallback(async () => {
    if (!isDesktop || !hostRef.current) return
    const path = await resolveVaultPath()
    if (!path) {
      setEmbed({
        state: "failed",
        message: "Bind a vault path in Settings → Integrations before embedding Obsidian.",
        obsidian_hwnd: null,
      })
      return
    }
    setBusy(true)
    const bounds = embedBoundsFromElement(hostRef.current, path)
    const result = await DesktopBridge.obsidianEmbedStart(bounds)
    setEmbed(result)
    setBusy(false)
    if (focusNote.trim()) {
      await DesktopBridge.obsidianFocusNote(focusNote.trim(), path)
    }
  }, [focusNote, isDesktop, resolveVaultPath])

  useEffect(() => {
    if (!isDesktop || !status?.bound) return
    void startEmbed()
    return () => {
      void DesktopBridge.obsidianEmbedStop()
    }
    // Auto-embed once when vault is bound; manual restart uses the toolbar button.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDesktop, status?.bound])

  useEffect(() => {
    if (!isDesktop || !hostRef.current || embed?.state !== "embedded") return
    const el = hostRef.current
    const ro = new ResizeObserver(() => {
      const path = vaultPath || readCachedVaultPath()
      if (!path) return
      void DesktopBridge.obsidianEmbedResize(embedBoundsFromElement(el, path)).then(setEmbed)
    })
    ro.observe(el)
    const onWinResize = () => {
      const path = vaultPath || readCachedVaultPath()
      if (!path) return
      void DesktopBridge.obsidianEmbedResize(embedBoundsFromElement(el, path)).then(setEmbed)
    }
    window.addEventListener("resize", onWinResize)
    return () => {
      ro.disconnect()
      window.removeEventListener("resize", onWinResize)
    }
  }, [embed?.state, isDesktop, vaultPath])

  async function handleFocusSubmit(event: React.FormEvent) {
    event.preventDefault()
    const rel = focusInput.trim()
    if (!rel) return
    const path = await resolveVaultPath()
    if (isDesktop) {
      await DesktopBridge.obsidianFocusNote(rel, path || undefined)
      if (embed?.state !== "embedded") {
        await startEmbed()
      }
    }
  }

  const brokenCount = health?.broken_links?.length ?? 0
  const healthTone = brokenCount > 0 || health?.missing_router ? "warn" : "ok"

  return (
    <div className="obsidian-host-page">
      <header className="obsidian-host-chrome card">
        <div className="obsidian-host-chrome-head">
          <h1>Obsidian</h1>
          <p className="lede">
            Your linked memory vault runs in the <strong>real Obsidian app</strong> inside Jarvis — not a
            custom note browser.
          </p>
        </div>
        <div className="obsidian-host-status-grid">
          <div className={`obsidian-pill tone-${status?.bound ? "ok" : "warn"}`}>
            Vault: {status?.bound ? "bound" : "not bound"}
            {status?.bound && status.note_count > 0 ? ` · ${status.note_count} notes indexed` : ""}
          </div>
          <div className={`obsidian-pill tone-${healthTone}`}>
            Health: {brokenCount ? `${brokenCount} broken links` : "OK"}
            {health?.missing_router ? " · router missing" : ""}
          </div>
          {isDesktop && probe && (
            <div className={`obsidian-pill tone-${probe.installed ? "ok" : "warn"}`}>
              Obsidian: {probe.installed ? "installed" : "not installed"}
            </div>
          )}
          {isDesktop && embed?.message && (
            <div className={`obsidian-pill tone-${embed.state === "embedded" ? "ok" : "warn"}`}>
              Host: {embed.message}
            </div>
          )}
        </div>
        <div className="obsidian-host-actions row">
          <Link className="btn secondary" to={settingsSubmenuPath("integrations", "#knowledge-vault")}>
            Vault bind / settings
          </Link>
          {!isDesktop && (
            <span className="obsidian-browser-hint">
              Open <strong>Jarvis Desktop</strong> on Windows to embed Obsidian here. Browser portal does not
              host Obsidian.exe.
            </span>
          )}
          {isDesktop && probe && !probe.installed && (
            <button
              type="button"
              className="btn"
              onClick={() => void DesktopBridge.obsidianOpenInstall()}
            >
              Install Obsidian
            </button>
          )}
          {isDesktop && status?.bound && (
            <button type="button" className="btn" disabled={busy} onClick={() => void startEmbed()}>
              {busy ? "Starting…" : "Restart Obsidian host"}
            </button>
          )}
        </div>
        <form className="obsidian-focus-form row" onSubmit={(e) => void handleFocusSubmit(e)}>
          <label className="obsidian-focus-label">
            Focus note (vault path)
            <input
              type="text"
              value={focusInput}
              onChange={(e) => setFocusInput(e.target.value)}
              placeholder="Projects/alpha.md"
              spellCheck={false}
            />
          </label>
          <button type="submit" className="btn secondary" disabled={!focusInput.trim()}>
            Focus in Obsidian
          </button>
        </form>
      </header>

      <section className="obsidian-embed-region" aria-label="Obsidian application host">
        {!status?.bound && (
          <div className="obsidian-embed-placeholder card">
            <p>
              Jarvis binds a managed vault on first start. If you still see this, bind a folder in
              Settings → Integrations.
            </p>
            <Link className="btn" to={settingsSubmenuPath("integrations", "#knowledge-vault")}>
              Vault settings
            </Link>
          </div>
        )}
        {status?.bound && !isDesktop && (
          <div className="obsidian-embed-placeholder card">
            <p>
              Vault is bound on this PC. Launch <strong>Jarvis Desktop</strong> and return to this Obsidian pane
              to edit notes in the embedded Obsidian UI.
            </p>
          </div>
        )}
        {status?.bound && isDesktop && probe && !probe.installed && (
          <div className="obsidian-embed-placeholder card">
            <p>Install Obsidian to embed the real editor inside Jarvis.</p>
            <button type="button" className="btn" onClick={() => void DesktopBridge.obsidianOpenInstall()}>
              Download Obsidian
            </button>
          </div>
        )}
        {status?.bound && isDesktop && probe?.installed && (
          <div ref={hostRef} className="obsidian-native-host" data-testid="obsidian-native-host" />
        )}
      </section>
    </div>
  )
}
