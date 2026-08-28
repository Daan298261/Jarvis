import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent } from "react"
import {
  addPackTrustKey,
  exportPack,
  formatPackError,
  getPack,
  installPack,
  listPackHistory,
  listPackTrust,
  listPacks,
  markPackResourceUserModified,
  previewPack,
  rollbackPack,
  uninstallPack,
  upgradePack,
  type InstalledPack,
  type PackDetail,
  type PackHistoryEvent,
  type PackManifestObject,
  type PackPreview,
  type PackPreviewAction,
  type PackResourceChange,
  type PackResourceRecord,
} from "../api"

const OVERRIDE_OPTIONS = [
  { value: "", label: "Decide later" },
  { value: "keep_user", label: "Keep my version" },
  { value: "use_pack", label: "Use the pack version" },
  { value: "merge", label: "Merge both" },
] as const

function parseManifestText(text: string): { manifest?: PackManifestObject; error?: string } {
  const trimmed = text.trim()
  if (!trimmed) return { error: "Paste a pack file or JSON first." }
  try {
    const parsed = JSON.parse(trimmed) as unknown
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { error: "A pack file must be a JSON object." }
    }
    return { manifest: parsed as PackManifestObject }
  } catch {
    return { error: "That JSON could not be read. Check for a missing comma or quote." }
  }
}

function manifestId(manifest: PackManifestObject | null): string {
  if (!manifest) return ""
  const id = manifest.id
  return typeof id === "string" ? id : ""
}

function fingerprint(manifest: PackManifestObject, action: PackPreviewAction, overrides: Record<string, string>, requireSignature: boolean): string {
  return JSON.stringify({
    manifest,
    action,
    overrides,
    require_signature: requireSignature,
  })
}

function changeBadge(action: string): string {
  if (action === "create") return "completed"
  if (action === "update") return "waiting"
  if (action === "conflict" || action === "delete") return "failed"
  return "queued"
}

function changeLabel(action: string): string {
  if (action === "create") return "Will be added"
  if (action === "update") return "Will change"
  if (action === "skip") return "Left as-is"
  if (action === "conflict") return "Needs a choice"
  if (action === "delete") return "Will be removed"
  return action
}

function eventLabel(event: string): string {
  if (event === "pack.installed") return "Installed"
  if (event === "pack.upgraded") return "Upgraded"
  if (event === "pack.rolled_back") return "Rolled back"
  if (event === "pack.uninstalled") return "Removed"
  return event.replace(/^pack\./, "").replaceAll("_", " ")
}

function formatWhen(value: string | null | undefined): string {
  if (!value) return ""
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function compactJson(value: Record<string, unknown> | null | undefined): string {
  if (!value) return "—"
  try {
    const text = JSON.stringify(value, null, 2)
    return text.length > 1200 ? `${text.slice(0, 1200)}\n…` : text
  } catch {
    return "—"
  }
}

function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" })
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

function uninstallStub(pack: InstalledPack): PackManifestObject {
  return {
    schema_version: "1.0",
    id: pack.id,
    name: pack.name || pack.id,
    version: pack.version || "0.0.0",
    description: pack.description || "",
  }
}

function PreviewChanges({
  preview,
  overrides,
  onOverride,
  allowOverrides,
}: {
  preview: PackPreview
  overrides: Record<string, string>
  onOverride?: (resourceId: string, value: string) => void
  allowOverrides?: boolean
}) {
  const trust = preview.trust || {}
  const capabilities = preview.capabilities || {}
  const dependencies = preview.dependencies || {}
  return (
    <div>
      <div className="kv" style={{ marginBottom: 12 }}>
        <b>Pack</b><span>{preview.pack_id} · {preview.version}</span>
        <b>Ready</b>
        <span>
          <span className={`badge ${preview.valid ? "completed" : "failed"}`}>
            {preview.valid ? "Looks good" : "Blocked"}
          </span>
        </span>
        <b>Trust</b>
        <span>
          {String(trust.message || trust.trust_level || "—")}
          {trust.signature_valid === true ? " · signature ok" : ""}
          {trust.signature_valid === false ? " · signature not accepted" : ""}
        </span>
        <b>Tools</b>
        <span>
          {capabilities.allowed === false
            ? `Not allowed${Array.isArray(capabilities.missing) && capabilities.missing.length ? `: missing ${capabilities.missing.join(", ")}` : ""}`
            : "Allowed on this PC"}
        </span>
        <b>Depends on</b>
        <span>
          {dependencies.satisfied === false
            ? `Missing ${((dependencies.missing as string[]) || []).join(", ") || "required packs"}`
            : "Nothing extra, or already installed"}
        </span>
      </div>
      {preview.errors.length > 0 && (
        <div className="card auth-card" style={{ margin: "0 0 12px", padding: "12px 16px" }}>
          {preview.errors.map((item) => (
            <p key={item} style={{ margin: "0 0 6px" }}>{item}</p>
          ))}
        </div>
      )}
      {preview.warnings.length > 0 && (
        <p className="lede" style={{ margin: "0 0 12px", color: "var(--warn)" }}>
          {preview.warnings.join(" ")}
        </p>
      )}
      {preview.changes.length === 0 && (
        <p className="lede" style={{ margin: 0 }}>Nothing would change.</p>
      )}
      {preview.changes.map((change) => (
        <ChangeCard
          key={change.resource_id}
          change={change}
          override={overrides[change.resource_id] || ""}
          onOverride={allowOverrides ? onOverride : undefined}
        />
      ))}
    </div>
  )
}

function ChangeCard({
  change,
  override,
  onOverride,
}: {
  change: PackResourceChange
  override: string
  onOverride?: (resourceId: string, value: string) => void
}) {
  const needsChoice = change.action === "conflict" || (change.action === "skip" && change.reason === "user_modified")
  return (
    <div className={`pack-change ${change.action}`}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <strong>{change.resource_id}</strong>
          <div className="lede" style={{ margin: "4px 0 0" }}>{change.resource_type}{change.reason ? ` · ${change.reason.replaceAll("_", " ")}` : ""}</div>
        </div>
        <span className={`badge ${changeBadge(change.action)}`}>{changeLabel(change.action)}</span>
      </div>
      {needsChoice && onOverride && (
        <label style={{ marginTop: 10 }}>
          What should stay
          <select value={override} onChange={(event) => onOverride(change.resource_id, event.target.value)}>
            {OVERRIDE_OPTIONS.map((option) => (
              <option key={option.value || "later"} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      )}
      <details style={{ marginTop: 10 }}>
        <summary className="lede" style={{ cursor: "pointer", margin: 0 }}>Show what changes</summary>
        <div className="grid two" style={{ marginTop: 8 }}>
          <div>
            <div className="lede" style={{ margin: "0 0 4px" }}>Now</div>
            <pre className="pack-change-json">{compactJson(change.before)}</pre>
          </div>
          <div>
            <div className="lede" style={{ margin: "0 0 4px" }}>After</div>
            <pre className="pack-change-json">{compactJson(change.after)}</pre>
          </div>
        </div>
      </details>
    </div>
  )
}

export function PacksPage() {
  const fileRef = useRef<HTMLInputElement>(null)
  const [packs, setPacks] = useState<InstalledPack[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<PackDetail | null>(null)
  const [events, setEvents] = useState<PackHistoryEvent[]>([])
  const [trustKeys, setTrustKeys] = useState<string[]>([])
  const [trustKeyId, setTrustKeyId] = useState("")
  const [trustSecret, setTrustSecret] = useState("")
  const [manifestText, setManifestText] = useState("")
  const [requireSignature, setRequireSignature] = useState(false)
  const [enforcePolicies, setEnforcePolicies] = useState(true)
  const [overrides, setOverrides] = useState<Record<string, string>>({})
  const [preview, setPreview] = useState<PackPreview | null>(null)
  const [previewedFingerprint, setPreviewedFingerprint] = useState("")
  const [uninstallPreview, setUninstallPreview] = useState<PackPreview | null>(null)
  const [uninstallTarget, setUninstallTarget] = useState<InstalledPack | null>(null)
  const [keepUserModified, setKeepUserModified] = useState(true)
  const [exportIncludeEdits, setExportIncludeEdits] = useState(false)
  const [exportName, setExportName] = useState("")
  const [exportVersion, setExportVersion] = useState("")
  const [exportDescription, setExportDescription] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [msg, setMsg] = useState("")

  const parsed = useMemo(() => parseManifestText(manifestText), [manifestText])
  const installedIds = useMemo(() => new Set(packs.map((pack) => pack.id)), [packs])
  const parsedId = manifestId(parsed.manifest || null)
  const applyAction: PackPreviewAction = parsedId && installedIds.has(parsedId) ? "upgrade" : "install"
  const currentFingerprint = parsed.manifest
    ? fingerprint(parsed.manifest, applyAction, overrides, requireSignature)
    : ""
  const previewMatches = Boolean(preview) && previewedFingerprint === currentFingerprint && preview?.action === applyAction
  const hasConflicts = Boolean(preview?.changes.some((change) => change.action === "conflict"))
  const canApply = previewMatches && Boolean(preview?.valid) && !hasConflicts && !busy

  const refresh = useCallback(async () => {
    const [listed, history, trust] = await Promise.all([
      listPacks(),
      listPackHistory().catch(() => ({ events: [] as PackHistoryEvent[] })),
      listPackTrust().catch(() => ({ key_ids: [] as string[] })),
    ])
    setPacks(listed.packs || [])
    setEvents(history.events || [])
    setTrustKeys(trust.key_ids || [])
  }, [])

  useEffect(() => {
    refresh().catch((err: unknown) => {
      setError(formatPackError(err) || "Could not load packs.")
    })
  }, [refresh])

  async function loadDetail(packId: string) {
    setSelectedId(packId)
    setBusy(true)
    setError("")
    try {
      const next = await getPack(packId)
      setDetail(next)
      setExportName(next.installation.name || "")
      setExportVersion(next.installation.version || "")
      setExportDescription(next.installation.description || "")
    } catch (err: unknown) {
      setError(formatPackError(err))
    } finally {
      setBusy(false)
    }
  }

  function onManifestChange(text: string) {
    setManifestText(text)
    setPreview(null)
    setPreviewedFingerprint("")
    setOverrides({})
  }

  async function onLoadFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ""
    if (!file) return
    try {
      const text = await file.text()
      onManifestChange(text)
      setMsg(`Loaded ${file.name}. Preview the changes before installing.`)
      setError("")
    } catch (err: unknown) {
      setError(formatPackError(err) || "Could not read that file.")
    }
  }

  async function onPreview(event?: FormEvent) {
    event?.preventDefault()
    if (!parsed.manifest) {
      setError(parsed.error || "Paste a pack file first.")
      return
    }
    setBusy(true)
    setError("")
    setMsg("")
    try {
      const result = await previewPack({
        manifest: parsed.manifest,
        action: applyAction,
        overrides,
        require_signature: requireSignature,
      })
      setPreview(result)
      setPreviewedFingerprint(fingerprint(parsed.manifest, applyAction, overrides, requireSignature))
      if (result.valid && !result.changes.some((change) => change.action === "conflict")) {
        setMsg("Review every item below, then confirm.")
      } else if (!result.valid) {
        setError(result.errors.join(" ") || "This pack cannot be applied yet.")
      } else {
        setError("Resolve conflicts before applying this pack.")
      }
    } catch (err: unknown) {
      setPreview(null)
      setPreviewedFingerprint("")
      setError(formatPackError(err))
    } finally {
      setBusy(false)
    }
  }

  function setOverride(resourceId: string, value: string) {
    setOverrides((current) => {
      const next = { ...current }
      if (value) next[resourceId] = value
      else delete next[resourceId]
      return next
    })
    setPreview(null)
    setPreviewedFingerprint("")
  }

  async function onApply() {
    if (!parsed.manifest || !canApply || !preview) return
    setBusy(true)
    setError("")
    setMsg("")
    try {
      const body = {
        manifest: parsed.manifest,
        overrides,
        require_signature: requireSignature,
        enforce_policies: enforcePolicies,
      }
      const result = applyAction === "upgrade" ? await upgradePack(body) : await installPack(body)
      setMsg(
        applyAction === "upgrade"
          ? `Upgraded ${result.installation.name} to ${result.installation.version}.`
          : `Installed ${result.installation.name} ${result.installation.version}.`,
      )
      setPreview(null)
      setPreviewedFingerprint("")
      setManifestText("")
      setOverrides({})
      await refresh()
      await loadDetail(result.installation.id)
    } catch (err: unknown) {
      setError(formatPackError(err))
    } finally {
      setBusy(false)
    }
  }

  async function onPreviewUninstall(pack: InstalledPack) {
    setBusy(true)
    setError("")
    setMsg("")
    setKeepUserModified(true)
    try {
      const result = await previewPack({
        manifest: uninstallStub(pack),
        action: "uninstall",
      })
      setUninstallTarget(pack)
      setUninstallPreview(result)
      if (!result.valid) {
        setError(result.errors.join(" ") || "This pack cannot be removed yet.")
      }
    } catch (err: unknown) {
      setUninstallTarget(null)
      setUninstallPreview(null)
      setError(formatPackError(err))
    } finally {
      setBusy(false)
    }
  }

  async function onConfirmUninstall() {
    if (!uninstallTarget || !uninstallPreview) return
    setBusy(true)
    setError("")
    try {
      const result = await uninstallPack(uninstallTarget.id, keepUserModified)
      setMsg(
        keepUserModified && result.kept_resources.length
          ? `Removed ${result.pack_id}. Kept ${result.kept_resources.length} item(s) you changed.`
          : `Removed ${result.pack_id}.`,
      )
      setUninstallTarget(null)
      setUninstallPreview(null)
      if (selectedId === uninstallTarget.id) {
        setSelectedId(null)
        setDetail(null)
      }
      await refresh()
    } catch (err: unknown) {
      setError(formatPackError(err))
    } finally {
      setBusy(false)
    }
  }

  async function onRollback(pack: InstalledPack) {
    if (!pack.snapshot_id) {
      setError("This pack has no previous version to go back to.")
      return
    }
    const previous = pack.previous_version || "the last version"
    if (!window.confirm(`Go back to ${previous} for ${pack.name}?`)) return
    setBusy(true)
    setError("")
    setMsg("")
    try {
      const result = await rollbackPack(pack.id)
      setMsg(`Restored ${result.installation.name} to ${result.installation.version}.`)
      await refresh()
      await loadDetail(pack.id)
    } catch (err: unknown) {
      setError(formatPackError(err))
    } finally {
      setBusy(false)
    }
  }

  async function onExport() {
    const packId = detail?.installation.id || selectedId
    if (!packId) {
      setError("Choose an installed pack to export.")
      return
    }
    setBusy(true)
    setError("")
    try {
      const exported = await exportPack({
        pack_id: packId,
        include_user_modifications: exportIncludeEdits,
        name: exportName.trim() || undefined,
        version: exportVersion.trim() || undefined,
        description: exportDescription.trim() || undefined,
      })
      const filename = `${packId.replaceAll(".", "-")}-${exportVersion.trim() || detail?.installation.version || "export"}.json`
      downloadJson(filename, exported)
      setMsg("Exported a pack file. Secrets such as keys and passwords are left out.")
    } catch (err: unknown) {
      setError(formatPackError(err))
    } finally {
      setBusy(false)
    }
  }

  async function onMarkEdited(resource: PackResourceRecord) {
    setBusy(true)
    setError("")
    try {
      await markPackResourceUserModified(resource.resource_id)
      setMsg(`Marked ${resource.resource_id} as something you changed. Upgrades will skip it unless you say otherwise.`)
      if (selectedId) await loadDetail(selectedId)
    } catch (err: unknown) {
      setError(formatPackError(err))
    } finally {
      setBusy(false)
    }
  }

  async function onAddTrust(event: FormEvent) {
    event.preventDefault()
    if (!trustKeyId.trim() || !trustSecret.trim()) {
      setError("Publisher id and secret are both required.")
      return
    }
    setBusy(true)
    setError("")
    try {
      const result = await addPackTrustKey(trustKeyId.trim(), trustSecret)
      setTrustKeys(result.key_ids || [])
      setTrustKeyId("")
      setTrustSecret("")
      setMsg("Trusted publisher saved. Signed packs from this publisher can be checked.")
    } catch (err: unknown) {
      setError(formatPackError(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="packs-page">
      <h1>Packs</h1>
      <p className="lede">
        Install and manage workspace packs on this PC. Every add, upgrade, or removal shows you the resources it will
        touch before anything is applied.
      </p>

      {msg && (
        <div className="card" style={{ marginBottom: 16, borderLeft: "4px solid var(--ok)", padding: "12px 16px" }}>
          {msg}
        </div>
      )}
      {error && (
        <div className="card auth-card" style={{ margin: "0 0 16px", padding: "12px 16px" }}>
          {error}
        </div>
      )}

      {uninstallPreview && uninstallTarget && (
        <div className="card" style={{ marginBottom: 16, borderColor: "var(--gold)" }}>
          <h2>Review before removing {uninstallTarget.name}</h2>
          <p className="lede">
            This list is what Jarvis would remove. Confirm only after you have checked it.
          </p>
          <PreviewChanges preview={uninstallPreview} overrides={{}} />
          <label className="row" style={{ marginTop: 12 }}>
            <input
              type="checkbox"
              checked={keepUserModified}
              onChange={(event) => setKeepUserModified(event.target.checked)}
            />
            Keep things I have changed
          </label>
          <div className="row" style={{ marginTop: 14 }}>
            <button className="btn danger" type="button" disabled={busy || !uninstallPreview.valid} onClick={onConfirmUninstall}>
              Remove this pack
            </button>
            <button
              className="btn secondary"
              type="button"
              onClick={() => {
                setUninstallPreview(null)
                setUninstallTarget(null)
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <h2>Installed on this PC</h2>
        {packs.length === 0 && (
          <p className="lede" style={{ margin: 0 }}>No packs yet. Paste a pack file below to install one.</p>
        )}
        <div className="template-grid">
          {packs.map((pack) => (
            <article
              key={pack.id}
              className={`template-card runtime-card${selectedId === pack.id ? " selected" : ""}`}
            >
              <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                <h3 style={{ margin: 0, fontSize: 15 }}>{pack.name}</h3>
                <span className={`badge ${pack.status === "installed" ? "completed" : "waiting"}`}>{pack.status}</span>
              </div>
              <p>{pack.description || pack.id}</p>
              <div className="runtime-tags">
                <span>{pack.version}</span>
                <span>{pack.id}</span>
                {pack.previous_version && <span>was {pack.previous_version}</span>}
              </div>
              <div className="row" style={{ marginTop: 12 }}>
                <button className="btn" type="button" disabled={busy} onClick={() => loadDetail(pack.id)}>
                  Manage
                </button>
                <button className="btn secondary" type="button" disabled={busy || !pack.snapshot_id} onClick={() => onRollback(pack)}>
                  Roll back
                </button>
                <button className="btn secondary" type="button" disabled={busy} onClick={() => onPreviewUninstall(pack)}>
                  Uninstall
                </button>
              </div>
            </article>
          ))}
        </div>
      </div>

      {detail && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2>{detail.installation.name}</h2>
          <div className="kv" style={{ marginBottom: 16 }}>
            <b>Version</b><span>{detail.installation.version}</span>
            <b>Installed</b><span>{formatWhen(detail.installation.installed_at) || "—"}</span>
            <b>Previous</b><span>{detail.installation.previous_version || "None"}</span>
            <b>Rollback</b><span>{detail.installation.snapshot_id ? "Available" : "Not available"}</span>
          </div>
          <h3 style={{ fontSize: 15, margin: "0 0 8px" }}>Resources</h3>
          {detail.resources.length === 0 && <p className="lede">This pack has no resources on disk.</p>}
          {detail.resources.map((resource) => (
            <div className="toggle" key={resource.resource_id}>
              <div>
                <strong>{resource.resource_id}</strong>
                <div className="lede" style={{ margin: "4px 0 0" }}>
                  {resource.resource_type}
                  {resource.user_modified ? " · you changed this" : ""}
                </div>
              </div>
              <button
                className="btn secondary"
                type="button"
                disabled={busy || resource.user_modified}
                onClick={() => onMarkEdited(resource)}
              >
                {resource.user_modified ? "Your edit" : "I changed this"}
              </button>
            </div>
          ))}
          <h3 style={{ fontSize: 15, margin: "18px 0 8px" }}>Export</h3>
          <p className="lede" style={{ margin: "0 0 12px" }}>
            Download a pack you can share. Keys, passwords, and other secrets are stripped by Jarvis before the file is written.
          </p>
          <div className="runtime-form">
            <label>
              Name
              <input value={exportName} onChange={(event) => setExportName(event.target.value)} />
            </label>
            <label>
              Version
              <input value={exportVersion} onChange={(event) => setExportVersion(event.target.value)} placeholder="1.0.0" />
            </label>
            <label className="span-2">
              Description
              <input value={exportDescription} onChange={(event) => setExportDescription(event.target.value)} />
            </label>
          </div>
          <label className="row" style={{ marginTop: 12 }}>
            <input
              type="checkbox"
              checked={exportIncludeEdits}
              onChange={(event) => setExportIncludeEdits(event.target.checked)}
            />
            Include things I changed
          </label>
          <div className="row" style={{ marginTop: 12 }}>
            <button className="btn" type="button" disabled={busy} onClick={onExport}>
              Export pack file
            </button>
          </div>
        </div>
      )}

      <form className="card" style={{ marginBottom: 16 }} onSubmit={onPreview}>
        <h2>Install or upgrade</h2>
        <p className="lede">
          Paste or load a pack manifest. Jarvis previews every created or changed resource. Nothing is applied until you confirm.
        </p>
        <input
          ref={fileRef}
          type="file"
          accept="application/json,.json"
          hidden
          onChange={onLoadFile}
        />
        <textarea
          className="command"
          rows={12}
          spellCheck={false}
          value={manifestText}
          onChange={(event) => onManifestChange(event.target.value)}
          placeholder='{"id":"example.demo","name":"Example","version":"1.0.0",...}'
          aria-label="Pack manifest JSON"
        />
        {parsed.error && manifestText.trim() && (
          <p className="lede" style={{ color: "var(--bad)", margin: "8px 0 0" }}>{parsed.error}</p>
        )}
        {parsed.manifest && !parsed.error && (
          <p className="lede" style={{ margin: "8px 0 0" }}>
            {applyAction === "upgrade"
              ? `${parsedId} is already on this PC — this will upgrade it.`
              : `${parsedId || "This pack"} is not installed yet.`}
          </p>
        )}
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn secondary" type="button" onClick={() => fileRef.current?.click()}>
            Load file
          </button>
          <button className="btn" type="submit" disabled={busy || !parsed.manifest}>
            Preview changes
          </button>
        </div>
        <label className="row" style={{ marginTop: 12 }}>
          <input
            type="checkbox"
            checked={requireSignature}
            onChange={(event) => {
              setRequireSignature(event.target.checked)
              setPreview(null)
              setPreviewedFingerprint("")
            }}
          />
          Require a trusted signature
        </label>
        <label className="row">
          <input
            type="checkbox"
            checked={enforcePolicies}
            onChange={(event) => setEnforcePolicies(event.target.checked)}
          />
          Enforce trust and tool rules when applying
        </label>
        {preview && previewMatches && (
          <div style={{ marginTop: 16 }}>
            <h3 style={{ fontSize: 15, margin: "0 0 8px" }}>What this pack will do</h3>
            <PreviewChanges
              preview={preview}
              overrides={overrides}
              onOverride={setOverride}
              allowOverrides
            />
            <div className="row" style={{ marginTop: 14 }}>
              <button className="btn" type="button" disabled={!canApply} onClick={onApply}>
                {applyAction === "upgrade" ? "Confirm upgrade" : "Confirm install"}
              </button>
              {!preview.valid && (
                <span className="lede" style={{ margin: 0 }}>Fix the problems above before applying.</span>
              )}
              {preview.valid && hasConflicts && (
                <span className="lede" style={{ margin: 0 }}>Choose what to keep on each conflict, then preview again.</span>
              )}
            </div>
          </div>
        )}
        {preview && !previewMatches && (
          <p className="lede" style={{ margin: "12px 0 0" }}>
            The pack file or choices changed. Preview again before installing.
          </p>
        )}
      </form>

      <div className="card" style={{ marginBottom: 16 }}>
        <h2>Trusted publishers</h2>
        <p className="lede">
          Signed packs can name a publisher. Add that publisher here so Jarvis can check the signature. Unsigned packs you create yourself still install as your own.
        </p>
        {trustKeys.length === 0 && <p className="lede">No trusted publishers yet.</p>}
        <div className="runtime-tags" style={{ marginBottom: 12 }}>
          {trustKeys.map((key) => (
            <span key={key}>{key}</span>
          ))}
        </div>
        <form className="runtime-form" onSubmit={onAddTrust}>
          <label>
            Publisher id
            <input value={trustKeyId} onChange={(event) => setTrustKeyId(event.target.value)} placeholder="publisher" />
          </label>
          <label>
            Secret
            <input
              type="password"
              value={trustSecret}
              onChange={(event) => setTrustSecret(event.target.value)}
              placeholder="Shared secret"
            />
          </label>
          <div className="span-2 row">
            <button className="btn" type="submit" disabled={busy}>
              Trust this publisher
            </button>
          </div>
        </form>
      </div>

      <div className="card">
        <h2>Recent pack activity</h2>
        {events.length === 0 && <p className="lede" style={{ margin: 0 }}>No pack changes recorded yet.</p>}
        {events.slice().reverse().slice(0, 20).map((event) => (
          <div className="suggestion-row" key={event.id}>
            <div>
              <strong>{eventLabel(event.event)}</strong>
              <p>
                {event.pack_id}
                {event.version ? ` · ${event.version}` : ""}
                {event.timestamp ? ` · ${formatWhen(event.timestamp)}` : ""}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
