import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react"
import { Link, useParams } from "react-router-dom"
import {
  activateSkillForgeCandidate,
  approveSkillForgeCandidate,
  disableSkillForgeSkill,
  formatSkillForgeError,
  getSkillForgeCandidate,
  getSkillForgeIndex,
  getSkillForgeVersion,
  importSkillForgeManifest,
  listSkillForgeCandidates,
  previewSkillForgePermissions,
  rejectSkillForgeCandidate,
  requestSkillForgeApproval,
  rollbackSkillForgeSkill,
  sandboxSkillForgeCandidate,
  searchSkillForge,
  skillForgeNeedsOwnerDecision,
  verifySkillForgeCandidate,
  type SkillForgeCandidate,
  type SkillForgePermissionPreview,
  type SkillForgeRegistryEntry,
  type SkillForgeSearchHit,
  type SkillForgeVersion,
} from "../api"

const ACTOR_KEY = "jarvis_skill_forge_actor"
const DEFAULT_ACTOR = "owner"

const STATUS_BADGE: Record<string, string> = {
  proposed: "queued",
  sandboxed: "queued",
  verified: "waiting",
  approved: "waiting",
  active: "completed",
  rejected: "failed",
  superseded: "queued",
  rolled_back: "queued",
  quarantined: "waiting",
}

function readStoredActor(): string {
  try {
    const stored = localStorage.getItem(ACTOR_KEY)?.trim()
    if (stored) return stored
  } catch {
    /* ignore */
  }
  return DEFAULT_ACTOR
}

function persistActor(actor: string) {
  try {
    localStorage.setItem(ACTOR_KEY, actor.trim() || DEFAULT_ACTOR)
  } catch {
    /* ignore */
  }
}

function formatWhen(value: string | null | undefined): string {
  if (!value) return "—"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function shortHash(value: string | null | undefined): string {
  if (!value) return "—"
  return value.length > 16 ? `${value.slice(0, 16)}…` : value
}

function statusBadgeClass(status: string): string {
  return STATUS_BADGE[String(status || "").toLowerCase()] || "queued"
}

function isApproved(candidate: SkillForgeCandidate): boolean {
  const status = String(candidate.status || "").toLowerCase()
  const approval = candidate.version?.approval || {}
  return status === "approved" || approval.approved === true
}

function canApprove(candidate: SkillForgeCandidate): boolean {
  const status = String(candidate.status || "").toLowerCase()
  return status === "verified" || status === "quarantined" || (status === "approved" && !isApproved(candidate))
}

function canActivate(candidate: SkillForgeCandidate): boolean {
  return isApproved(candidate) && String(candidate.status || "").toLowerCase() !== "active"
}

function canReject(candidate: SkillForgeCandidate): boolean {
  const status = String(candidate.status || "").toLowerCase()
  return !["active", "rejected", "superseded", "rolled_back"].includes(status)
}

function manifestSummary(manifest: SkillForgeCandidate["version"]["manifest"] | undefined): string {
  if (!manifest) return "No manifest."
  const tools = (manifest.tools || []).slice(0, 6).join(", ") || "no tools"
  const caps = (manifest.required_capabilities || []).slice(0, 4).join(", ") || "no declared capabilities"
  const steps = manifest.steps?.length ?? 0
  const tests = manifest.tests?.length ?? 0
  return `${manifest.scope || "workflow"} · ${tools} · ${caps} · ${steps} step${steps === 1 ? "" : "s"} · ${tests} test${tests === 1 ? "" : "s"}`
}

function verifierLabel(verifier: SkillForgeCandidate["version"]["verifier"] | null | undefined): string {
  if (!verifier) return "Not evaluated"
  if (verifier.passed) {
    return `Passed ${verifier.tests_passed ?? 0}/${verifier.tests_run ?? 0}`
  }
  return `Failed ${verifier.tests_failed ?? 0}/${verifier.tests_run ?? 0}`
}

export function SkillForgePage() {
  const { candidateId: routeCandidateId } = useParams<{ candidateId?: string }>()
  const [skills, setSkills] = useState<SkillForgeRegistryEntry[]>([])
  const [candidates, setCandidates] = useState<SkillForgeCandidate[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(routeCandidateId || null)
  const [selected, setSelected] = useState<SkillForgeCandidate | null>(null)
  const [permissionPreview, setPermissionPreview] = useState<SkillForgePermissionPreview | null>(null)
  const [versionDetail, setVersionDetail] = useState<SkillForgeVersion | null>(null)
  const [actor, setActor] = useState(readStoredActor)
  const [adminAuthority, setAdminAuthority] = useState(true)
  const [rejectReason, setRejectReason] = useState("")
  const [searchQuery, setSearchQuery] = useState("")
  const [searchHits, setSearchHits] = useState<SkillForgeSearchHit[] | null>(null)
  const [importText, setImportText] = useState("")
  const [statusFilter, setStatusFilter] = useState("")
  const [busy, setBusy] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionOk, setActionOk] = useState<string | null>(null)
  const [loaded, setLoaded] = useState(false)

  const inbox = useMemo(
    () => candidates.filter(skillForgeNeedsOwnerDecision).sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || "")),
    [candidates],
  )

  const filteredCandidates = useMemo(() => {
    if (!statusFilter) return candidates
    return candidates.filter((c) => String(c.status).toLowerCase() === statusFilter.toLowerCase())
  }, [candidates, statusFilter])

  const refresh = useCallback(async () => {
    setLoadError(null)
    try {
      const index = await getSkillForgeIndex()
      setSkills(index.skills || [])
      setCandidates(index.candidates || [])
      setLoaded(true)
    } catch (err: unknown) {
      setLoadError(formatSkillForgeError(err))
      setLoaded(true)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    if (routeCandidateId) setSelectedId(routeCandidateId)
  }, [routeCandidateId])

  useEffect(() => {
    if (!selectedId) {
      setSelected(null)
      setPermissionPreview(null)
      setVersionDetail(null)
      return
    }
    let cancelled = false
    ;(async () => {
      try {
        const candidate = await getSkillForgeCandidate(selectedId)
        if (cancelled) return
        setSelected(candidate)
        setActionError(null)
        const [preview, version] = await Promise.all([
          previewSkillForgePermissions(selectedId, { actor: actor.trim() || DEFAULT_ACTOR }).catch(() => null),
          getSkillForgeVersion(candidate.version.version_id).catch(() => null),
        ])
        if (cancelled) return
        setPermissionPreview(preview)
        setVersionDetail(version)
      } catch (err: unknown) {
        if (!cancelled) {
          setSelected(null)
          setActionError(formatSkillForgeError(err))
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [selectedId, actor])

  function updateActor(value: string) {
    setActor(value)
    persistActor(value)
  }

  function requireActor(): string | null {
    const trimmed = actor.trim()
    if (!trimmed) {
      setActionError("Actor is required. Enter your owner id (for example owner) before approve, activate, or reject.")
      setActionOk(null)
      return null
    }
    return trimmed
  }

  async function runAction(label: string, work: () => Promise<void>) {
    setBusy(true)
    setActionError(null)
    setActionOk(null)
    try {
      await work()
      setActionOk(label)
      await refresh()
      if (selectedId) {
        const fresh = await getSkillForgeCandidate(selectedId).catch(() => null)
        if (fresh) setSelected(fresh)
      }
    } catch (err: unknown) {
      setActionError(formatSkillForgeError(err))
      setActionOk(null)
    } finally {
      setBusy(false)
    }
  }

  async function onApprove(candidateId: string) {
    const who = requireActor()
    if (!who) return
    if (!adminAuthority) {
      setActionError("Owner / admin authority must be confirmed before approve. Anzu will not invent an admin actor.")
      return
    }
    await runAction("Approved — still inactive until you Activate.", async () => {
      await approveSkillForgeCandidate(candidateId, { actor: who, admin: true })
    })
  }

  async function onActivate(candidateId: string) {
    const who = requireActor()
    if (!who) return
    if (!adminAuthority) {
      setActionError("Owner / admin authority must be confirmed before activate.")
      return
    }
    await runAction("Activated — published as the active skill version.", async () => {
      await activateSkillForgeCandidate(candidateId, { actor: who, admin: true })
    })
  }

  async function onReject(candidateId: string) {
    const who = requireActor()
    if (!who) return
    const reason = rejectReason.trim()
    if (!reason) {
      setActionError("Reject requires a reason.")
      return
    }
    await runAction("Rejected.", async () => {
      await rejectSkillForgeCandidate(candidateId, { actor: who, reason, admin: adminAuthority })
      setRejectReason("")
    })
  }

  async function onRequestApproval(candidateId: string) {
    const who = requireActor()
    if (!who) return
    await runAction("Approval requested — waiting in Decision Inbox.", async () => {
      await requestSkillForgeApproval(candidateId, { actor: who, admin: adminAuthority })
    })
  }

  async function onSandbox(candidateId: string) {
    const who = requireActor()
    if (!who) return
    await runAction("Sandbox evaluation finished.", async () => {
      await sandboxSkillForgeCandidate(candidateId, { actor: who })
    })
  }

  async function onVerify(candidateId: string) {
    await runAction("Verification finished.", async () => {
      await verifySkillForgeCandidate(candidateId)
    })
  }

  async function onRefreshPermissions(candidateId: string) {
    const who = requireActor()
    if (!who) return
    setBusy(true)
    setActionError(null)
    try {
      const preview = await previewSkillForgePermissions(candidateId, { actor: who })
      setPermissionPreview(preview)
      setActionOk("Permission preview refreshed.")
    } catch (err: unknown) {
      setActionError(formatSkillForgeError(err))
    } finally {
      setBusy(false)
    }
  }

  async function onDisable(skillId: string) {
    const who = requireActor()
    if (!who) return
    if (!window.confirm("Disable this published skill? It will leave the active set until you activate another version.")) {
      return
    }
    await runAction("Skill disabled.", async () => {
      const result = await disableSkillForgeSkill(skillId, who)
      if (!result.ok) {
        throw new Error("Disable did not complete.")
      }
    })
  }

  async function onRollback(skillId: string, toVersionId?: string | null) {
    const who = requireActor()
    if (!who) return
    if (!window.confirm("Roll back this skill to a previous version? The current active version is left intact as history.")) {
      return
    }
    await runAction("Rollback applied.", async () => {
      await rollbackSkillForgeSkill(skillId, { actor: who, to_version_id: toVersionId || null })
    })
  }

  async function onSearch(event: FormEvent) {
    event.preventDefault()
    const q = searchQuery.trim()
    if (!q) {
      setSearchHits(null)
      return
    }
    setBusy(true)
    setActionError(null)
    try {
      const result = await searchSkillForge({ query: q, limit: 20 })
      setSearchHits(result.results || [])
    } catch (err: unknown) {
      setSearchHits([])
      setActionError(formatSkillForgeError(err))
    } finally {
      setBusy(false)
    }
  }

  async function onImport(event: FormEvent) {
    event.preventDefault()
    const trimmed = importText.trim()
    if (!trimmed) {
      setActionError("Paste a skill manifest JSON to import. Marketplace imports enter quarantine.")
      return
    }
    let manifest: Record<string, unknown>
    try {
      const parsed = JSON.parse(trimmed) as unknown
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        setActionError("Import must be a JSON object (skill manifest).")
        return
      }
      manifest = parsed as Record<string, unknown>
    } catch {
      setActionError("That JSON could not be read. Check for a missing comma or quote.")
      return
    }
    await runAction("Imported into quarantine — evaluate, then approve and activate.", async () => {
      const candidate = await importSkillForgeManifest({
        manifest,
        imported_from: "marketplace",
      })
      setImportText("")
      setSelectedId(candidate.candidate_id)
    })
  }

  async function onFilterStatus(status: string) {
    setStatusFilter(status)
    if (!status) {
      await refresh()
      return
    }
    setBusy(true)
    setActionError(null)
    try {
      const result = await listSkillForgeCandidates(status, 50)
      setCandidates(result.candidates || [])
    } catch (err: unknown) {
      setActionError(formatSkillForgeError(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="skill-forge-page">
      <h1>Modules / Skills</h1>
      <p className="lede">
        Anzu 1.0 Skill Forge. Verified traces become candidates — never auto-published. Review purpose,
        provenance, eval status, and permissions, then <strong>Approve</strong> and separately{" "}
        <strong>Activate</strong>. Coding merge conflicts stay on{" "}
        <Link to="/coding">Coding → Decision Inbox</Link>. Memory guides live on{" "}
        <Link to="/memory">Memory</Link>.
      </p>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="rail-heading" style={{ padding: "0 0 8px" }}>
          <span>Owner actor</span>
        </div>
        <p className="lede" style={{ marginTop: 0 }}>
          Approve, activate, reject, disable, and rollback send this actor string. Anzu does not silently
          substitute an auto-admin identity.
        </p>
        <div className="row" style={{ flexWrap: "wrap", gap: 12, alignItems: "flex-end" }}>
          <label style={{ flex: "1 1 220px" }}>
            Actor (owner id)
            <input
              type="text"
              value={actor}
              onChange={(event) => updateActor(event.target.value)}
              placeholder="owner"
              aria-label="Skill Forge actor"
              autoComplete="username"
            />
          </label>
          <label className="row" style={{ gap: 8, marginBottom: 6 }}>
            <input
              type="checkbox"
              checked={adminAuthority}
              onChange={(event) => setAdminAuthority(event.target.checked)}
            />
            Owner / admin authority
          </label>
          <button className="btn secondary" type="button" disabled={busy} onClick={() => void refresh()}>
            Refresh
          </button>
        </div>
      </div>

      {loadError && (
        <div className="card coding-banner bad" style={{ marginBottom: 16 }}>
          <p className="license-kicker">Could not load Skill Forge</p>
          <p className="lede" style={{ margin: 0 }}>{loadError}</p>
        </div>
      )}

      {actionError && (
        <div className="card coding-banner bad" style={{ marginBottom: 16 }}>
          <p className="license-kicker">Action failed</p>
          <p className="lede" style={{ margin: 0 }}>{actionError}</p>
        </div>
      )}

      {actionOk && (
        <div className="card" style={{ marginBottom: 16, borderLeft: "4px solid var(--ok)", padding: "12px 16px" }}>
          <p className="lede" style={{ margin: 0 }}>{actionOk}</p>
        </div>
      )}

      <DecisionInboxSection
        items={inbox}
        selectedId={selectedId}
        busy={busy}
        loaded={loaded}
        loadError={loadError}
        onSelect={setSelectedId}
      />

      {selected && (
        <CandidateDetail
          candidate={selected}
          permissionPreview={permissionPreview}
          versionDetail={versionDetail}
          busy={busy}
          rejectReason={rejectReason}
          onRejectReason={setRejectReason}
          onApprove={() => void onApprove(selected.candidate_id)}
          onActivate={() => void onActivate(selected.candidate_id)}
          onReject={() => void onReject(selected.candidate_id)}
          onRequestApproval={() => void onRequestApproval(selected.candidate_id)}
          onSandbox={() => void onSandbox(selected.candidate_id)}
          onVerify={() => void onVerify(selected.candidate_id)}
          onRefreshPermissions={() => void onRefreshPermissions(selected.candidate_id)}
          onClose={() => setSelectedId(null)}
        />
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="rail-heading" style={{ padding: "0 0 8px" }}>
          <span>Published skills</span>
        </div>
        <p className="lede">
          Active Skill Forge registry. Search routes by purpose and tools. Disable clears the active
          pointer; rollback restores a prior version without mutating history.
        </p>
        <form className="row" style={{ gap: 8, marginBottom: 12, flexWrap: "wrap" }} onSubmit={(e) => void onSearch(e)}>
          <input
            type="search"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Search published skills…"
            aria-label="Search skills"
            style={{ flex: "1 1 220px" }}
          />
          <button className="btn" type="submit" disabled={busy}>
            Search
          </button>
          {searchHits && (
            <button
              className="btn secondary"
              type="button"
              onClick={() => {
                setSearchHits(null)
                setSearchQuery("")
              }}
            >
              Clear
            </button>
          )}
        </form>

        {searchHits && (
          <div style={{ marginBottom: 16 }}>
            <h3 className="env-subhead">Search results</h3>
            {searchHits.length === 0 ? (
              <p className="lede" style={{ margin: 0 }}>No published skills matched that query.</p>
            ) : (
              <ul className="env-file-list">
                {searchHits.map((hit, index) => (
                  <li key={`${hit.skill_id || hit.name || "hit"}-${index}`}>
                    <strong>{String(hit.name || hit.skill_id || "Skill")}</strong>
                    {hit.purpose ? ` — ${String(hit.purpose)}` : ""}
                    {hit.version_id ? (
                      <span className="lede"> · {String(hit.version_id)}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {!loaded ? (
          <p className="lede" style={{ margin: 0 }}>Loading published skills…</p>
        ) : loadError ? (
          <p className="lede" style={{ margin: 0 }}>Published skills unavailable until Skill Forge loads.</p>
        ) : skills.length === 0 ? (
          <p className="lede" style={{ margin: 0 }}>
            No published skills yet. Approve and activate a verified candidate to publish one.
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Skill</th>
                <th>Origin</th>
                <th>Active version</th>
                <th>Versions</th>
                <th>Updated</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {skills.map((skill) => (
                <tr key={skill.skill_id}>
                  <td>
                    <strong>{skill.name || skill.skill_id}</strong>
                    <div className="lede" style={{ margin: "4px 0 0" }}>{skill.skill_id}</div>
                  </td>
                  <td>{skill.origin || "forge"}</td>
                  <td title={skill.active_version_id || undefined}>
                    {skill.active_version_id ? shortHash(skill.active_version_id) : (
                      <span className="badge queued">none</span>
                    )}
                  </td>
                  <td>{skill.versions?.length ?? 0}</td>
                  <td>{formatWhen(skill.updated_at)}</td>
                  <td>
                    <div className="row coding-actions" style={{ gap: 6, flexWrap: "wrap" }}>
                      <button
                        className="btn secondary"
                        type="button"
                        disabled={busy || !skill.active_version_id}
                        onClick={() => void onDisable(skill.skill_id)}
                      >
                        Disable
                      </button>
                      <button
                        className="btn secondary"
                        type="button"
                        disabled={busy || (skill.versions?.length || 0) < 2}
                        onClick={() => void onRollback(skill.skill_id)}
                      >
                        Rollback
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="rail-heading" style={{ padding: "0 0 8px" }}>
          <span>Candidate queue</span>
          <label className="row" style={{ gap: 8, color: "var(--muted)", fontSize: 13 }}>
            Status
            <select
              value={statusFilter}
              onChange={(event) => void onFilterStatus(event.target.value)}
              aria-label="Filter candidates by status"
            >
              <option value="">All</option>
              <option value="proposed">proposed</option>
              <option value="sandboxed">sandboxed</option>
              <option value="verified">verified</option>
              <option value="approved">approved</option>
              <option value="active">active</option>
              <option value="quarantined">quarantined</option>
              <option value="rejected">rejected</option>
            </select>
          </label>
        </div>
        <p className="lede">
          Full forge pipeline queue, including quarantine/marketplace imports. Select a row to review
          before any activation.
        </p>
        {!loaded ? (
          <p className="lede" style={{ margin: 0 }}>Loading candidates…</p>
        ) : filteredCandidates.length === 0 ? (
          <p className="lede" style={{ margin: 0 }}>
            {statusFilter
              ? `No candidates with status “${statusFilter}”.`
              : "No Skill Forge candidates yet. Eligible traces enter the pipeline from the forge backend."}
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Candidate</th>
                <th>Status</th>
                <th>Purpose</th>
                <th>Provenance</th>
                <th>Eval</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {filteredCandidates.map((candidate) => {
                const manifest = candidate.version?.manifest
                return (
                  <tr
                    key={candidate.candidate_id}
                    className={`env-row${candidate.candidate_id === selectedId ? " selected" : ""}`}
                    onClick={() => setSelectedId(candidate.candidate_id)}
                  >
                    <td>
                      <strong>{manifest?.name || candidate.candidate_id}</strong>
                      <div className="lede" style={{ margin: "4px 0 0" }}>{candidate.candidate_id}</div>
                    </td>
                    <td>
                      <span className={`badge ${statusBadgeClass(candidate.status)}`}>
                        {candidate.status}
                      </span>
                    </td>
                    <td title={manifest?.purpose || ""}>
                      {(manifest?.purpose || "—").slice(0, 80)}
                      {(manifest?.purpose || "").length > 80 ? "…" : ""}
                    </td>
                    <td>
                      {manifest?.provenance?.source || "—"}
                      {manifest?.provenance?.imported_from
                        ? ` · ${manifest.provenance.imported_from}`
                        : ""}
                    </td>
                    <td>{verifierLabel(candidate.version?.verifier)}</td>
                    <td>{formatWhen(candidate.updated_at)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <div className="rail-heading" style={{ padding: "0 0 8px" }}>
          <span>Marketplace / quarantine import</span>
        </div>
        <p className="lede">
          Imported manifests enter quarantine and use the same evaluate → approve → activate path. Nothing
          from an import becomes active without those steps.
        </p>
        <form onSubmit={(event) => void onImport(event)}>
          <label>
            Manifest JSON
            <textarea
              className="field"
              rows={8}
              value={importText}
              onChange={(event) => setImportText(event.target.value)}
              placeholder='{"name":"example","purpose":"…","tools":["filesystem"],…}'
              aria-label="Skill manifest JSON"
            />
          </label>
          <div className="row" style={{ marginTop: 12 }}>
            <button className="btn" type="submit" disabled={busy}>
              Import to quarantine
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function DecisionInboxSection({
  items,
  selectedId,
  busy,
  loaded,
  loadError,
  onSelect,
}: {
  items: SkillForgeCandidate[]
  selectedId: string | null
  busy: boolean
  loaded: boolean
  loadError: string | null
  onSelect: (id: string) => void
}) {
  return (
    <div className="card" style={{ marginBottom: 16 }} id="decision-inbox">
      <div className="rail-heading" style={{ padding: "0 0 8px" }}>
        <span>Decision Inbox</span>
        <span className={`badge ${items.length ? "waiting" : "completed"}`}>
          {items.length ? `${items.length} awaiting` : "Clear"}
        </span>
      </div>
      <p className="lede">
        Skill Forge candidates waiting for an explicit owner decision. Approve records authority;
        Activate publishes. Reject needs a reason. Anzu never auto-activates from this list.
      </p>
      {!loaded ? (
        <p className="lede" style={{ margin: 0 }}>Loading Decision Inbox…</p>
      ) : loadError ? (
        <p className="lede" style={{ margin: 0 }}>
          Decision Inbox could not load. Fix the Skill Forge error above — this is not an empty success.
        </p>
      ) : items.length === 0 ? (
        <p className="lede" style={{ margin: 0 }}>
          No Skill Forge candidates awaiting approval or activation.
        </p>
      ) : (
        items.map((candidate) => {
          const manifest = candidate.version?.manifest
          const approval = candidate.version?.approval || {}
          return (
            <button
              key={candidate.candidate_id}
              type="button"
              className={`context-entry${candidate.candidate_id === selectedId ? " selected" : " conflict"}`}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                cursor: busy ? "wait" : "pointer",
                marginBottom: 10,
                background: "transparent",
                border: "1px solid var(--line)",
                borderRadius: 8,
                padding: 12,
              }}
              onClick={() => onSelect(candidate.candidate_id)}
            >
              <div className="row" style={{ justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                <strong>{manifest?.name || candidate.candidate_id}</strong>
                <span className={`badge ${statusBadgeClass(candidate.status)}`}>{candidate.status}</span>
              </div>
              <p className="lede" style={{ margin: "6px 0 8px" }}>
                {manifest?.purpose || "No purpose declared."}
              </p>
              <div className="kv">
                <b>Next step</b>
                <span>
                  {canActivate(candidate)
                    ? "Activate (already approved)"
                    : canApprove(candidate)
                      ? "Approve, then Activate"
                      : candidate.status}
                </span>
                <b>Hash</b>
                <span title={manifest?.content_hash || undefined}>{shortHash(manifest?.content_hash)}</span>
                <b>Eval</b>
                <span>{verifierLabel(candidate.version?.verifier)}</span>
                <b>Approval</b>
                <span>
                  {approval.approved
                    ? `Approved by ${String(approval.approved_by || "—")}`
                    : approval.requested
                      ? "Requested — awaiting owner"
                      : "Not requested"}
                </span>
              </div>
            </button>
          )
        })
      )}
    </div>
  )
}

function CandidateDetail({
  candidate,
  permissionPreview,
  versionDetail,
  busy,
  rejectReason,
  onRejectReason,
  onApprove,
  onActivate,
  onReject,
  onRequestApproval,
  onSandbox,
  onVerify,
  onRefreshPermissions,
  onClose,
}: {
  candidate: SkillForgeCandidate
  permissionPreview: SkillForgePermissionPreview | null
  versionDetail: SkillForgeVersion | null
  busy: boolean
  rejectReason: string
  onRejectReason: (value: string) => void
  onApprove: () => void
  onActivate: () => void
  onReject: () => void
  onRequestApproval: () => void
  onSandbox: () => void
  onVerify: () => void
  onRefreshPermissions: () => void
  onClose: () => void
}) {
  const manifest = candidate.version?.manifest
  const approval = candidate.version?.approval || {}
  const provenance = manifest?.provenance
  const approved = isApproved(candidate)
  const activateReady = canActivate(candidate)

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="rail-heading" style={{ padding: "0 0 8px" }}>
        <span>Candidate review</span>
        <button className="btn secondary" type="button" onClick={onClose}>
          Close
        </button>
      </div>
      <h2 style={{ marginBottom: 8 }}>{manifest?.name || candidate.candidate_id}</h2>
      <p className="lede">{manifest?.purpose || "No purpose on this manifest."}</p>

      <div className="kv">
        <b>Status</b>
        <span className={`badge ${statusBadgeClass(candidate.status)}`}>{candidate.status}</span>
        <b>Candidate</b>
        <span>{candidate.candidate_id}</span>
        <b>Skill id</b>
        <span>{candidate.skill_id}</span>
        <b>Version</b>
        <span>{candidate.version?.version_id || "—"}</span>
        <b>Manifest version</b>
        <span>{manifest?.version || "—"}</span>
        <b>Summary</b>
        <span>{manifestSummary(manifest)}</span>
        <b>Content hash</b>
        <span title={manifest?.content_hash || undefined}>{manifest?.content_hash || "—"}</span>
        <b>Signature</b>
        <span title={manifest?.signature || undefined}>{shortHash(manifest?.signature)}</span>
        <b>Provenance</b>
        <span>
          {provenance?.source || "—"}
          {provenance?.created_by ? ` · by ${provenance.created_by}` : ""}
          {provenance?.imported_from ? ` · from ${provenance.imported_from}` : ""}
        </span>
        <b>Trajectories</b>
        <span>{(provenance?.trajectory_ids || []).join(", ") || "—"}</span>
        <b>Eval / verify</b>
        <span>{verifierLabel(candidate.version?.verifier || versionDetail?.verifier)}</span>
        <b>Decision inbox</b>
        <span>{candidate.decision_inbox_item_id || "—"}</span>
        <b>Approval</b>
        <span>
          {approved
            ? `Approved by ${String(approval.approved_by || "—")} at ${formatWhen(String(approval.approved_at || ""))}`
            : approval.requested
              ? `Requested by ${String(approval.requested_by || "—")}`
              : "Not approved"}
        </span>
        {candidate.rejection_reason && (
          <>
            <b>Rejection</b>
            <span>{candidate.rejection_reason}</span>
          </>
        )}
        {candidate.version?.quarantine_reason && (
          <>
            <b>Quarantine</b>
            <span>{candidate.version.quarantine_reason}</span>
          </>
        )}
        <b>Updated</b>
        <span>{formatWhen(candidate.updated_at)}</span>
      </div>

      <h3 className="env-subhead">Tools & scopes</h3>
      <div className="kv">
        <b>Tools</b>
        <span>{(manifest?.tools || []).join(", ") || "—"}</span>
        <b>Capabilities</b>
        <span>{(manifest?.required_capabilities || []).join(", ") || "—"}</span>
        <b>Secrets</b>
        <span>{(manifest?.secrets || []).join(", ") || "none"}</span>
        <b>Network</b>
        <span>{(manifest?.network_scope || []).join(", ") || "—"}</span>
        <b>Filesystem</b>
        <span>{(manifest?.filesystem_scope || []).join(", ") || "—"}</span>
        <b>Personas</b>
        <span>{(manifest?.compatible_personas || []).join(", ") || "—"}</span>
      </div>

      <h3 className="env-subhead">Permission preview</h3>
      {permissionPreview ? (
        <div className="kv">
          <b>Allows execution</b>
          <span className={`badge ${permissionPreview.allows_execution ? "completed" : "failed"}`}>
            {permissionPreview.allows_execution ? "yes" : "no"}
          </span>
          <b>Privilege expansion</b>
          <span className={`badge ${permissionPreview.privilege_expansion ? "failed" : "completed"}`}>
            {permissionPreview.privilege_expansion ? "blocked" : "none"}
          </span>
          <b>Effective</b>
          <span>{(permissionPreview.effective || []).join(", ") || "—"}</span>
          <b>Denied</b>
          <span>{(permissionPreview.denied || []).join(", ") || "none"}</span>
          <b>Declared</b>
          <span>{(permissionPreview.declared || []).join(", ") || "—"}</span>
        </div>
      ) : (
        <p className="lede" style={{ margin: 0 }}>
          Permission preview not loaded yet. Use Refresh permissions — empty here is not a silent allow.
        </p>
      )}

      <div className="row coding-actions" style={{ marginTop: 12, flexWrap: "wrap", gap: 8 }}>
        <button className="btn secondary" type="button" disabled={busy} onClick={onSandbox}>
          Sandbox
        </button>
        <button className="btn secondary" type="button" disabled={busy} onClick={onVerify}>
          Verify
        </button>
        <button className="btn secondary" type="button" disabled={busy} onClick={onRefreshPermissions}>
          Refresh permissions
        </button>
        {String(candidate.status).toLowerCase() === "verified" && !approval.requested && (
          <button className="btn secondary" type="button" disabled={busy} onClick={onRequestApproval}>
            Request approval
          </button>
        )}
      </div>

      <h3 className="env-subhead">Approve, then Activate</h3>
      <p className="lede">
        Two distinct steps. Activate stays disabled until approve succeeds. Failures surface the API
        detail — Anzu will not invent a successful activate.
      </p>
      <div className="row coding-actions" style={{ flexWrap: "wrap", gap: 8 }}>
        <button
          className="btn"
          type="button"
          disabled={busy || !canApprove(candidate) || approved}
          title={approved ? "Already approved" : "Record owner approval without publishing"}
          onClick={onApprove}
        >
          Approve
        </button>
        <button
          className="btn"
          type="button"
          disabled={busy || !activateReady}
          title={
            activateReady
              ? "Publish as the active skill version"
              : "Activate requires a successful Approve first"
          }
          onClick={onActivate}
        >
          Activate
        </button>
      </div>

      {canReject(candidate) && (
        <>
          <h3 className="env-subhead">Reject</h3>
          <label>
            Reason (required)
            <input
              type="text"
              value={rejectReason}
              onChange={(event) => onRejectReason(event.target.value)}
              placeholder="Why this candidate must not publish"
              aria-label="Rejection reason"
            />
          </label>
          <div className="row" style={{ marginTop: 12 }}>
            <button className="btn danger" type="button" disabled={busy || !rejectReason.trim()} onClick={onReject}>
              Reject
            </button>
          </div>
        </>
      )}
    </div>
  )
}
