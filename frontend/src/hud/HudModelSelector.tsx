import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react"
import { Link } from "react-router-dom"
import { api, getLmStudioCatalog, getSelectedRuntimeProfileId, listRuntimeProfiles, type LmStudioCatalogResponse, type RuntimeProfile } from "../api"
import { EngineModeControl } from "../components/EngineModeControl"
import { applyRuntimeProfile, playDiscoveredGguf, playLmStudioCatalogProfile } from "./applyRuntimeProfile"
import { hexStrikeSelectMessage } from "./hexstrikeAutostart"
import { isHexStrikeSuiteProfile } from "./hexstrikeSuite"
import { backendModelError, loadStatusLine, localCatalogHint, triggerMeta, vramHint } from "./modelMenuStatus"
import { NodeAiInventory } from "./NodeAiInventory"
import { modelName, nodeModelOptions, selectedModelOption, servingModel, type NodeModelState as ModelState, type NodeAiInventory as Inventory } from "./nodeModelOptions"
import "./hexstrike.css"
import "./nodeModels.css"

export type HudModelSelectorProps = { model: ModelState | null; onOpenChange?: (open: boolean) => void }

export function HudModelSelector({ model, onOpenChange }: HudModelSelectorProps) {
  const menuId = useId(), root = useRef<HTMLDivElement>(null)
  const revision = useRef(0), working = useRef(false)
  const [open, setOpen] = useState(false), [more, setMore] = useState(false)
  const [profiles, setProfiles] = useState<RuntimeProfile[]>([])
  const [catalog, setCatalog] = useState<LmStudioCatalogResponse | null>(null)
  const [selectedId, setSelectedId] = useState(getSelectedRuntimeProfileId)
  const [draft, setDraft] = useState("")
  const [snapshot, setSnapshot] = useState<ModelState | null>(null)
  const [engineMode, setEngineMode] = useState("hybrid")
  const [busy, setBusy] = useState(false), [refreshing, setRefreshing] = useState(false)
  const [runtimesFailed, setRuntimesFailed] = useState(false), [catalogFailed, setCatalogFailed] = useState(false), [elapsed, setElapsed] = useState(0)
  const [message, setMessage] = useState(""), [error, setError] = useState(""), [refreshError, setRefreshError] = useState("")
  const options = useMemo(() => nodeModelOptions(profiles.filter((p) => !isHexStrikeSuiteProfile(p)), catalog), [profiles, catalog])
  const suite = profiles.find(isHexStrikeSuiteProfile)
  const state = open ? snapshot || model : model || snapshot
  const serving = servingModel(state)
  const value = options.some((option) => option.key === draft) ? draft : selectedModelOption(options, selectedId)
  const choice = options.find((option) => option.key === value)
  const transferring = busy || !!state?.loading
  const suiteActive = !!suite && (suite.id === selectedId || suite.name === selectedId)
  const catalogHint = localCatalogHint(catalog, catalogFailed), vram = vramHint(catalog)
  const backendError = backendModelError(state?.last_error, [error, refreshError], transferring)

  useEffect(() => {
    if (!transferring) { setElapsed(0); return }
    const started = Date.now()
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000)
    return () => window.clearInterval(timer)
  }, [transferring])

  const refresh = useCallback(async () => {
    if (working.current) return
    const current = ++revision.current
    setRefreshing(true)
    const results = await Promise.allSettled([listRuntimeProfiles(), getLmStudioCatalog(), api<ModelState>("/api/model"), api<{ engine_mode?: string }>("/api/settings")])
    if (current !== revision.current || working.current) return
    const [runtime, files, live, settings] = results
    if (runtime.status === "fulfilled") setProfiles(runtime.value.profiles)
    if (files.status === "fulfilled") setCatalog(files.value)
    setRuntimesFailed(runtime.status === "rejected"); setCatalogFailed(files.status === "rejected")
    if (live.status === "fulfilled") setSnapshot(live.value)
    if (settings.status === "fulfilled") setEngineMode(settings.value.engine_mode || "hybrid")
    setRefreshError(live.status === "rejected" ? "Serving status could not refresh." : runtime.status === "rejected" || files.status === "rejected" ? "Some model choices could not refresh." : "")
    setRefreshing(false)
  }, [])
  useEffect(() => { onOpenChange?.(open) }, [open, onOpenChange])
  useEffect(() => {
    if (!open) return
    void refresh()
    const outside = (event: MouseEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false) }
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false) }
    const timer = window.setInterval(() => void refresh(), 8000)
    document.addEventListener("mousedown", outside); document.addEventListener("keydown", escape)
    window.addEventListener("anzu-engine-mode", refresh)
    return () => { ++revision.current; clearInterval(timer); document.removeEventListener("mousedown", outside); document.removeEventListener("keydown", escape); window.removeEventListener("anzu-engine-mode", refresh) }
  }, [open, refresh])
  useEffect(() => {
    const changed = () => { setSelectedId(getSelectedRuntimeProfileId()); if (!working.current) { setDraft(""); void refresh() } }
    window.addEventListener("jarvis:runtime-profile-changed", changed)
    return () => window.removeEventListener("jarvis:runtime-profile-changed", changed)
  }, [refresh])

  async function activate(suiteOnly = false) {
    if (busy || state?.loading || (!suiteOnly && !choice) || (suiteOnly && !suite)) return
    working.current = true; ++revision.current; setBusy(true); setError(""); setMessage("")
    try {
      const applied = suiteOnly ? await applyRuntimeProfile(suite!.id)
        : choice!.kind === "catalog" ? await playLmStudioCatalogProfile(choice!.id)
          : choice!.kind === "file" ? await playDiscoveredGguf(choice!.id) : await applyRuntimeProfile(choice!.id)
      setSelectedId(applied.id); setDraft("")
      const live = await api<ModelState>("/api/model")
      setSnapshot(live)
      setMessage(suiteOnly ? hexStrikeSelectMessage("hexStrikeAutoStarted" in applied && !!applied.hexStrikeAutoStarted)
        : live.loaded ? `Serving: ${servingModel(live)}` : "Selection saved; no model is serving yet.")
    } catch (err) { setError(err instanceof Error ? err.message : "Could not load model") }
    finally { working.current = false; setBusy(false); void refresh() }
  }
  async function unload() {
    if (busy || state?.loading || !state?.loaded) return
    working.current = true; ++revision.current; setBusy(true); setError(""); setMessage("")
    const previous = serving
    try {
      setSnapshot(await api<ModelState>("/api/model/unload", { method: "POST" }))
      const inventory = await api<Inventory>("/api/model/node-inventory?refresh=true")
      if (inventory.models.some((item) => item.verified_loaded && (item.model === previous || item.model_key === previous))) {
        setMore(true)
        throw new Error("ANZU disconnected, but this model is still resident. Unload is not verified; see More.")
      }
      setMessage("ANZU is disconnected. More shows the node’s resident models.")
    } catch (err) { setError(err instanceof Error ? err.message : "Could not verify model unload") }
    finally { working.current = false; setBusy(false); void refresh() }
  }

  return <div className="hud-model-selector" ref={root}>
    <button type="button" className={`hud-model-trigger${open ? " open" : ""}${transferring ? " transferring" : ""}`} aria-expanded={open} aria-controls={menuId} aria-busy={transferring} title="Model for current node" onClick={() => setOpen(!open)}>
      <span className="hud-model-trigger-label">{transferring ? "Switching model…" : modelName(serving)}</span>
      <span className="hud-model-trigger-meta">{triggerMeta({ transferring, suiteActive, runtimesFailed })}</span>
    </button>
    {open && <div id={menuId} className="hud-model-menu node-model-menu" role="dialog" aria-label="Model for current node">
      <div className="hud-model-menu-head"><span>Model for this node</span><button type="button" onClick={() => setOpen(false)}>Close</button></div>
      {transferring && <p className="hud-model-transferring" role="status">{loadStatusLine(elapsed)}</p>}
      <div className="node-model-serving" role="status"><strong>Serving now</strong><span>{serving}</span></div>
      <label htmlFor={`${menuId}-choice`} className="node-model-label">Choose a model</label>
      <select id={`${menuId}-choice`} className="node-model-select" value={value} disabled={busy} onChange={(event) => { setDraft(event.target.value); setMessage("") }}>
        <option value="">Choose a model…</option>
        <optgroup label="GGUF files on this node">{options.filter((option) => option.kind !== "runtime").map((option) => <option key={option.key} value={option.key}>{option.label}</option>)}</optgroup>
        <optgroup label="Configured runtimes">{options.filter((option) => option.kind === "runtime").map((option) => <option key={option.key} value={option.key}>{option.label}</option>)}</optgroup>
      </select>
      <p className="node-model-detail">{choice?.detail || "Select a model, then press Load."}</p>
      {(catalogHint || vram) && <p className="node-model-detail hud-model-local-hint">{[catalogHint, vram].filter(Boolean).join(" · ")}</p>}
      <div className="node-model-actions">
        <button type="button" disabled={busy || state?.loading || !choice || engineMode === "reflex_only"} onClick={() => void activate()}>Load</button>
        <button type="button" disabled={busy || state?.loading || !state?.loaded} onClick={() => void unload()}>Unload</button>
        <button type="button" disabled={busy || refreshing} onClick={() => void refresh()}>{refreshing ? "Refreshing…" : "Refresh"}</button>
        <button type="button" aria-expanded={more} onClick={() => setMore(!more)}>{more ? "Less" : "More"}</button>
      </div>
      {message && <p role="status" className="node-model-detail">{message}</p>}
      {(error || refreshError) && <p role="alert" className="node-model-error">{error || refreshError}</p>}
      {backendError && <p role="alert" className="node-model-error hud-model-error">{backendError}</p>}
      <EngineModeControl />
      {suite && <button type="button" className={`hud-model-suite-row${suiteActive ? " active" : ""}`} disabled={transferring} onClick={() => void activate(true)}>
        <span className="mark" aria-hidden>⬡</span><span>{suite.label || "HexStrike AI"}</span><span className="meta">Cyber suite</span></button>}
      {more && <NodeAiInventory />}
      <div className="hud-model-menu-foot"><Link to="/model" onClick={() => setOpen(false)}>All model settings →</Link></div>
    </div>}
  </div>
}
