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
import { buildObsidianOpenUri, OBSIDIAN_DOWNLOAD_URL } from "../vault/obsidianUri"
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

function openProtocolUri(uri: string) {
  const anchor = document.createElement("a")
  anchor.href = uri
  anchor.rel = "noopener"
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
}

type HostSurface =
  | "loading"
  | "unbound"
  | "browser"
  | "missing_install"
  | "unsupported"
  | "ready"
  | "error"

export function ObsidianPage() {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const [searchParams] = useSearchParams()
  const focusNote = searchParams.get("focus") || ""

  const [status, setStatus] = useState<VaultPublicStatus | null>(null)
  const [health, setHealth] = useState<VaultHealthResponse | null>(null)
  const [metaError, setMetaError] = useState("")
  const [probe, setProbe] = useState<ObsidianProbeResult | null>(null)
  const [embed, setEmbed] = useState<ObsidianEmbedStatus | null>(null)
  const [vaultPath, setVaultPath] = useState("")
  const [focusInput, setFocusInput] = useState(focusNote)
  const [busy, setBusy] = useState(false)
  const [healthOpen, setHealthOpen] = useState(false)
  const [chromeCollapsed, setChromeCollapsed] = useState(false)
  const isDesktop = DesktopBridge.isDesktop()

  const refreshMeta = useCallback(async () => {
    try {
      const [st, h] = await Promise.all([fetchVaultStatus(), fetchVaultHealth()])
      setStatus(st)
      setHealth(h)
      setMetaError("")
    } catch (err) {
      setMetaError(err instanceof Error ? err.message : String(err))
    }
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
    void DesktopBridge.obsidianProbe().then((result) => setProbe(result))
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
    setEmbed({
      state: "launching",
      message: "Launching Obsidian inside Jarvis…",
      obsidian_hwnd: null,
    })
    const bounds = embedBoundsFromElement(hostRef.current, path)
    const result = await DesktopBridge.obsidianEmbedStart(bounds)
    setEmbed(
      result || {
        state: "failed",
        message: "Desktop shell did not start the Obsidian host.",
        obsidian_hwnd: null,
      },
    )
    setBusy(false)
    if (focusNote.trim()) {
      await DesktopBridge.obsidianFocusNote(focusNote.trim(), path)
    }
  }, [focusNote, isDesktop, resolveVaultPath])

  useEffect(() => {
    if (!isDesktop || !status?.bound) return
    // Mount host first; start embed on next frame so the host rect is non-zero.
    const id = window.requestAnimationFrame(() => {
      void startEmbed()
    })
    return () => {
      window.cancelAnimationFrame(id)
      void DesktopBridge.obsidianEmbedStop()
    }
    // Auto-embed once when vault is bound; manual restart uses the toolbar button.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDesktop, status?.bound])

  useEffect(() => {
    if (!isDesktop || !hostRef.current) return
    if (embed?.state !== "embedded" && embed?.state !== "launching") return
    const el = hostRef.current
    const ro = new ResizeObserver(() => {
      const path = vaultPath || readCachedVaultPath()
      if (!path || embed?.state !== "embedded") return
      void DesktopBridge.obsidianEmbedResize(embedBoundsFromElement(el, path)).then((next) => {
        if (next) setEmbed(next)
      })
    })
    ro.observe(el)
    const onWinResize = () => {
      const path = vaultPath || readCachedVaultPath()
      if (!path || embed?.state !== "embedded") return
      void DesktopBridge.obsidianEmbedResize(embedBoundsFromElement(el, path)).then((next) => {
        if (next) setEmbed(next)
      })
    }
    window.addEventListener("resize", onWinResize)
    return () => {
      ro.disconnect()
      window.removeEventListener("resize", onWinResize)
    }
  }, [embed?.state, isDesktop, vaultPath])

  useEffect(() => {
    if (embed?.state === "embedded") {
      setChromeCollapsed(true)
    }
  }, [embed?.state])

  async function handleFocusSubmit(event: React.FormEvent) {
    event.preventDefault()
    const rel = focusInput.trim()
    if (!rel) return
    const path = await resolveVaultPath()
    if (isDesktop) {
      const ok = await DesktopBridge.obsidianFocusNote(rel, path || undefined)
      if (!ok || embed?.state !== "embedded") {
        await startEmbed()
        await DesktopBridge.obsidianFocusNote(rel, path || undefined)
      }
      return
    }
    const vault = path || status?.vault_name || ""
    if (!vault) return
    openProtocolUri(buildObsidianOpenUri(vault, rel))
  }

  function openVaultInObsidian() {
    const vault = vaultPath || status?.vault_name || readCachedVaultPath()
    if (!vault) return
    openProtocolUri(buildObsidianOpenUri(vault))
  }

  function openInstallPage() {
    if (isDesktop) {
      void DesktopBridge.obsidianOpenInstall()
      return
    }
    window.open(OBSIDIAN_DOWNLOAD_URL, "_blank", "noopener,noreferrer")
  }

  const brokenCount = health?.broken_links?.length ?? 0
  const healthTone = brokenCount > 0 || health?.missing_router ? "warn" : "ok"
  const embedded = embed?.state === "embedded"
  const launching = embed?.state === "launching" || busy
  const embedFailed = embed?.state === "failed" || embed?.state === "unsupported_platform"

  let surface: HostSurface = "loading"
  if (metaError && !status) surface = "error"
  else if (status && !status.bound) surface = "unbound"
  else if (status?.bound && !isDesktop) surface = "browser"
  else if (status?.bound && isDesktop && probe && !probe.installed) surface = "missing_install"
  else if (status?.bound && isDesktop && probe && !probe.platform_embed_supported) surface = "unsupported"
  else if (status?.bound && isDesktop) surface = "ready"

  const showNativeHost = surface === "ready" || surface === "unsupported" || (isDesktop && !!status?.bound)

  return (
    <div
      className={`obsidian-host-page${embedded && chromeCollapsed ? " is-embedded" : ""}`}
      data-testid="obsidian-host-page"
    >
      <header className={`obsidian-host-chrome${chromeCollapsed && embedded ? " is-collapsed" : ""}`}>
        <div className="obsidian-host-chrome-head">
          <div className="obsidian-host-title-row">
            <h1>Obsidian</h1>
            {embedded && (
              <button
                type="button"
                className="btn secondary obsidian-chrome-toggle"
                onClick={() => setChromeCollapsed((v) => !v)}
                aria-expanded={!chromeCollapsed}
              >
                {chromeCollapsed ? "Show host controls" : "Hide host controls"}
              </button>
            )}
          </div>
          {!chromeCollapsed && (
            <p className="lede">
              This pane hosts the <strong>real Obsidian</strong> app for your bound vault — editor,
              graph, wiki-links, and plugins. Jarvis indexes the same files; it does not ship a
              second notebook.
            </p>
          )}
        </div>

        {!chromeCollapsed && (
          <>
            <div className="obsidian-host-status-grid" role="status">
              <div className={`obsidian-pill tone-${status?.bound ? "ok" : "warn"}`}>
                Vault: {status?.bound ? "bound" : "not bound"}
                {status?.bound && status.vault_name ? ` · ${status.vault_name}` : ""}
                {status?.bound && status.note_count > 0 ? ` · ${status.note_count} notes` : ""}
              </div>
              <div className={`obsidian-pill tone-${healthTone}`}>
                Health: {brokenCount ? `${brokenCount} broken links` : "OK"}
                {health?.missing_router ? " · router missing" : ""}
              </div>
              {isDesktop && (
                <div
                  className={`obsidian-pill tone-${
                    probe?.installed ? "ok" : probe ? "warn" : "muted"
                  }`}
                >
                  Obsidian:{" "}
                  {probe ? (probe.installed ? "installed" : "not installed") : "checking…"}
                </div>
              )}
              {isDesktop && embed?.message && (
                <div
                  className={`obsidian-pill tone-${
                    embed.state === "embedded" ? "ok" : embed.state === "launching" ? "muted" : "warn"
                  }`}
                >
                  Host: {embed.message}
                </div>
              )}
              {metaError && <div className="obsidian-pill tone-warn">Status: {metaError}</div>}
            </div>

            {(brokenCount > 0 || health?.missing_router) && (
              <div className="obsidian-health-chrome">
                <button
                  type="button"
                  className="obsidian-health-toggle"
                  onClick={() => setHealthOpen((open) => !open)}
                  aria-expanded={healthOpen}
                >
                  {healthOpen ? "Hide vault health detail" : "Show vault health detail"}
                </button>
                {healthOpen && (
                  <ul className="obsidian-health-list">
                    {health?.missing_router && (
                      <li>
                        Missing <code>_Config/router.md</code> — add it in Obsidian for local-model
                        orientation.
                      </li>
                    )}
                    {(health?.broken_links || []).slice(0, 12).map((link) => (
                      <li key={`${link.source}->${link.target}`}>
                        <code>{link.source}</code> → <code>{link.target}</code>
                      </li>
                    ))}
                    {brokenCount > 12 && <li>…and {brokenCount - 12} more</li>}
                  </ul>
                )}
              </div>
            )}

            <div className="obsidian-host-actions row">
              <Link
                className="btn secondary"
                to={settingsSubmenuPath("integrations", "#knowledge-vault")}
              >
                Vault bind / settings
              </Link>
              {!isDesktop && status?.bound && (
                <button type="button" className="btn" onClick={openVaultInObsidian}>
                  Open vault in Obsidian
                </button>
              )}
              {isDesktop && probe && !probe.installed && (
                <button type="button" className="btn" onClick={openInstallPage}>
                  Install Obsidian
                </button>
              )}
              {isDesktop && status?.bound && (
                <button
                  type="button"
                  className="btn"
                  disabled={busy}
                  onClick={() => void startEmbed()}
                >
                  {busy ? "Starting…" : "Restart Obsidian host"}
                </button>
              )}
            </div>

            <form
              className="obsidian-focus-form row"
              onSubmit={(e) => void handleFocusSubmit(e)}
            >
              <label className="obsidian-focus-label">
                Focus note (vault-relative path)
                <input
                  type="text"
                  value={focusInput}
                  onChange={(e) => setFocusInput(e.target.value)}
                  placeholder="Projects/alpha.md"
                  spellCheck={false}
                  autoComplete="off"
                />
              </label>
              <button type="submit" className="btn secondary" disabled={!focusInput.trim()}>
                Focus in Obsidian
              </button>
            </form>
          </>
        )}
      </header>

      <section className="obsidian-embed-region" aria-label="Obsidian application host">
        {surface === "loading" && (
          <div className="obsidian-embed-placeholder" data-testid="obsidian-surface-loading">
            <p>Checking vault binding…</p>
          </div>
        )}

        {surface === "error" && (
          <div className="obsidian-embed-placeholder" data-testid="obsidian-surface-error">
            <p>Could not load vault status from this PC.</p>
            <p className="muted">{metaError}</p>
            <button type="button" className="btn" onClick={() => void refreshMeta()}>
              Retry
            </button>
          </div>
        )}

        {surface === "unbound" && (
          <div className="obsidian-embed-placeholder" data-testid="obsidian-surface-unbound">
            <p>
              Bind a local Obsidian vault so Jarvis can index Markdown and this pane can host the
              real Obsidian UI.
            </p>
            <Link className="btn" to={settingsSubmenuPath("integrations", "#knowledge-vault")}>
              Vault settings
            </Link>
          </div>
        )}

        {surface === "browser" && (
          <div className="obsidian-embed-placeholder" data-testid="obsidian-surface-browser">
            <p>
              Vault <strong>{status?.vault_name || "bound"}</strong> is ready on this PC. This
              browser tab cannot parent <code>Obsidian.exe</code>. Open Obsidian in Jarvis Desktop
              for the in-window host, or open the vault in Obsidian on this machine.
            </p>
            <div className="row obsidian-cta-row">
              <button type="button" className="btn" onClick={openVaultInObsidian}>
                Open vault in Obsidian
              </button>
              <Link
                className="btn secondary"
                to={settingsSubmenuPath("integrations", "#knowledge-vault")}
              >
                Vault settings
              </Link>
            </div>
            <p className="obsidian-browser-hint">
              No custom note browser ships here — the owner surface is official Obsidian only.
            </p>
          </div>
        )}

        {surface === "missing_install" && (
          <div className="obsidian-embed-placeholder" data-testid="obsidian-surface-missing">
            <p>Install Obsidian to embed the real editor inside Jarvis Desktop.</p>
            <button type="button" className="btn" onClick={openInstallPage}>
              Download Obsidian
            </button>
          </div>
        )}

        {showNativeHost && surface !== "missing_install" && (
          <div className="obsidian-native-host-wrap">
            <div
              ref={hostRef}
              className={`obsidian-native-host${embedded ? " is-live" : ""}`}
              data-testid="obsidian-native-host"
            />
            {(launching || embedFailed || surface === "unsupported") && !embedded && (
              <div className="obsidian-host-overlay" data-testid="obsidian-host-overlay">
                {launching && <p>Starting Obsidian inside Jarvis…</p>}
                {surface === "unsupported" && (
                  <>
                    <p>
                      {probe?.message ||
                        "In-window Obsidian embed requires Jarvis Desktop on Windows."}
                    </p>
                    <button type="button" className="btn" onClick={openVaultInObsidian}>
                      Open vault in Obsidian
                    </button>
                  </>
                )}
                {embedFailed && surface !== "unsupported" && (
                  <>
                    <p>{embed?.message || "Obsidian host failed to start."}</p>
                    <div className="row obsidian-cta-row">
                      <button
                        type="button"
                        className="btn"
                        disabled={busy}
                        onClick={() => void startEmbed()}
                      >
                        Retry embed
                      </button>
                      <button type="button" className="btn secondary" onClick={openVaultInObsidian}>
                        Open vault in Obsidian
                      </button>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  )
}
