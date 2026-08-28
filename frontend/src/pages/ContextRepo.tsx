import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import {
  CONTEXT_ENTRY_CATEGORIES,
  createContextRepoEntry,
  deleteContextRepoEntry,
  formatContextRepoError,
  getContextRepo,
  getContextRepoDiff,
  getContextRepoEntry,
  getContextRepoSchedulePreference,
  listAgentPolicyProfiles,
  listContextRepoHistory,
  listContextRepoVersions,
  pinContextRepoEntry,
  revertContextRepoMutation,
  type AgentPolicyProfile,
  type ContextConsolidationNode,
  type ContextEntry,
  type ContextEntryInspect,
  type ContextMutationRecord,
  type ContextRepoVersion,
  type ContextRepoVersionSummary,
  type ContextSchedulePreference,
  type ContextVersionDiff,
} from "../api"

const SELECTED_AGENT_KEY = "jarvis_context_repo_agent_id"

const CATEGORY_LABELS: Record<string, string> = {
  identity: "Who this agent is",
  projects: "Projects",
  procedures: "How to do things",
  lessons: "Lessons",
  priorities: "Priorities",
  skills: "Written skills",
}

const ACTION_LABELS: Record<string, string> = {
  create: "Added",
  update: "Updated",
  pin: "Pinned",
  unpin: "Unpinned",
  delete: "Removed",
  revert: "Undone",
  consolidate: "Tidied up",
}

type Tab = "notes" | "compare" | "history"

function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category] || category.replaceAll("_", " ")
}

function actionLabel(action: string): string {
  return ACTION_LABELS[action] || action.replaceAll("_", " ")
}

function actionBadge(action: string): string {
  if (action === "create" || action === "pin") return "completed"
  if (action === "delete") return "failed"
  if (action === "revert" || action === "unpin") return "waiting"
  if (action === "consolidate") return "queued"
  return "waiting"
}

function formatWhen(value: string | null | undefined): string {
  if (!value) return "—"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function sourceLabel(type: string | null | undefined): string {
  const key = (type || "").toLowerCase()
  if (key === "manual") return "Written here"
  if (key === "revert") return "Undo"
  if (key === "consolidate") return "Idle tidy-up"
  if (key === "trajectory") return "From a finished task"
  return type ? type.replaceAll("_", " ") : "Unknown source"
}

function provenanceLine(source: {
  source_type?: string
  source_id?: string | null
  trajectory_id?: string | null
  note?: string | null
} | null | undefined): string {
  if (!source) return "No source recorded"
  const parts = [sourceLabel(source.source_type)]
  if (source.source_id) parts.push(`source ${source.source_id}`)
  if (source.trajectory_id) parts.push(`task ${source.trajectory_id}`)
  if (source.note) parts.push(source.note)
  return parts.join(" · ")
}

function storedAgentId(): string {
  try {
    return localStorage.getItem(SELECTED_AGENT_KEY) || ""
  } catch {
    return ""
  }
}

function storeAgentId(id: string) {
  try {
    if (id) localStorage.setItem(SELECTED_AGENT_KEY, id)
    else localStorage.removeItem(SELECTED_AGENT_KEY)
  } catch {
    // ignore
  }
}

function titleOf(entry: ContextEntry | null | undefined): string {
  return entry?.title?.trim() || "Untitled note"
}

function permissionLabel(permission: string): string {
  const key = permission.toLowerCase()
  if (key === "read") return "Can read"
  if (key === "write") return "Can edit"
  if (key === "delete") return "Can remove"
  return permission.replaceAll("_", " ")
}

function EntryCard({
  entry,
  selected,
  others,
  onOpen,
  onPin,
  onDelete,
  busy,
}: {
  entry: ContextEntry
  selected: boolean
  others: ContextEntry[]
  onOpen: () => void
  onPin: () => void
  onDelete: () => void
  busy: boolean
}) {
  const conflictTitles = entry.conflicts_with
    .map((id) => others.find((item) => item.id === id)?.title)
    .filter(Boolean) as string[]
  return (
    <div className={`context-entry${entry.pinned ? " pinned" : ""}${entry.conflicts_with.length ? " conflict" : ""}${selected ? " selected" : ""}`}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <button type="button" className="context-entry-open" onClick={onOpen}>
          <strong>{titleOf(entry)}</strong>
          <div className="lede" style={{ margin: "4px 0 0" }}>
            {categoryLabel(entry.category)}
            {entry.pinned ? " · pinned" : ""}
          </div>
        </button>
        <div className="row" style={{ gap: 6 }}>
          {entry.conflicts_with.length > 0 && (
            <span className="badge waiting">Conflict</span>
          )}
          {entry.pinned && <span className="badge ok">Pinned</span>}
        </div>
      </div>
      <p className="context-entry-preview">{entry.content}</p>
      {conflictTitles.length > 0 && (
        <p className="lede" style={{ margin: "0 0 8px", color: "var(--warn)" }}>
          Conflicts with {conflictTitles.join(", ")}. Both notes were kept.
        </p>
      )}
      <p className="lede" style={{ margin: "0 0 10px" }}>{provenanceLine(entry.provenance)}</p>
      <div className="row">
        <button className="btn secondary" type="button" disabled={busy} onClick={onOpen}>
          Inspect
        </button>
        <button className="btn secondary" type="button" disabled={busy} onClick={onPin}>
          {entry.pinned ? "Unpin" : "Pin"}
        </button>
        <button className="btn danger" type="button" disabled={busy || entry.pinned} onClick={onDelete}>
          Remove
        </button>
      </div>
    </div>
  )
}

function DiffEntry({ entry, kind }: { entry: ContextEntry; kind: "added" | "removed" | "changed" }) {
  return (
    <div className={`pack-change ${kind === "removed" ? "delete" : kind === "added" ? "create" : "update"}`}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <strong>{titleOf(entry)}</strong>
        <span className={`badge ${kind === "removed" ? "failed" : kind === "added" ? "completed" : "waiting"}`}>
          {kind === "removed" ? "Removed" : kind === "added" ? "Added" : "Changed"}
        </span>
      </div>
      <div className="lede" style={{ margin: "4px 0 0" }}>{categoryLabel(entry.category)}</div>
      <pre className="pack-change-json">{entry.content}</pre>
    </div>
  )
}

export function ContextRepoPage() {
  const [profiles, setProfiles] = useState<AgentPolicyProfile[]>([])
  const [agentId, setAgentId] = useState("")
  const [tab, setTab] = useState<Tab>("notes")
  const [repo, setRepo] = useState<ContextRepoVersion | null>(null)
  const [versions, setVersions] = useState<ContextRepoVersionSummary[]>([])
  const [history, setHistory] = useState<ContextMutationRecord[]>([])
  const [detail, setDetail] = useState<ContextEntryInspect | null>(null)
  const [diff, setDiff] = useState<ContextVersionDiff | null>(null)
  const [fromVersion, setFromVersion] = useState<number | "">("")
  const [toVersion, setToVersion] = useState<number | "">("")
  const [filter, setFilter] = useState<string>("all")
  const [showAdd, setShowAdd] = useState(false)
  const [addCategory, setAddCategory] = useState("lessons")
  const [addTitle, setAddTitle] = useState("")
  const [addContent, setAddContent] = useState("")
  const [addNote, setAddNote] = useState("")
  const [schedule, setSchedule] = useState<ContextSchedulePreference | null>(null)
  const [showSchedule, setShowSchedule] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [msg, setMsg] = useState("")

  const activeEntries = useMemo(
    () => (repo?.entries || []).filter((entry) => entry.active),
    [repo],
  )

  const filteredEntries = useMemo(() => {
    if (filter === "all") return activeEntries
    return activeEntries.filter((entry) => entry.category === filter)
  }, [activeEntries, filter])

  const grouped = useMemo(() => {
    const map = new Map<string, ContextEntry[]>()
    for (const category of CONTEXT_ENTRY_CATEGORIES) map.set(category, [])
    for (const entry of filteredEntries) {
      const list = map.get(entry.category) || []
      list.push(entry)
      map.set(entry.category, list)
    }
    return CONTEXT_ENTRY_CATEGORIES
      .map((category) => ({ category, entries: map.get(category) || [] }))
      .filter((group) => group.entries.length > 0)
  }, [filteredEntries])

  const refresh = useCallback(async (id: string) => {
    const [nextRepo, nextVersions, nextHistory] = await Promise.all([
      getContextRepo(id),
      listContextRepoVersions(id),
      listContextRepoHistory(id, 100),
    ])
    setRepo(nextRepo)
    setVersions(nextVersions)
    setHistory(nextHistory)
    setFromVersion((current) => {
      if (current !== "" && nextVersions.some((item) => item.version === current)) return current
      return nextVersions[0]?.version ?? ""
    })
    setToVersion((current) => {
      if (current !== "" && nextVersions.some((item) => item.version === current)) return current
      return nextVersions[nextVersions.length - 1]?.version ?? ""
    })
  }, [])

  useEffect(() => {
    listAgentPolicyProfiles()
      .then((list) => {
        const next = list.profiles || []
        setProfiles(next)
        const saved = storedAgentId()
        const pick = next.find((profile) => profile.id === saved) || next[0]
        if (pick) setAgentId(pick.id)
      })
      .catch((err: unknown) => {
        setError(formatContextRepoError(err) || "Could not load agents.")
      })
    getContextRepoSchedulePreference()
      .then(setSchedule)
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!agentId) {
      setRepo(null)
      setVersions([])
      setHistory([])
      setDetail(null)
      setDiff(null)
      return
    }
    storeAgentId(agentId)
    setBusy(true)
    setError("")
    refresh(agentId)
      .catch((err: unknown) => {
        setError(formatContextRepoError(err))
      })
      .finally(() => setBusy(false))
  }, [agentId, refresh])

  async function withBusy(work: () => Promise<void>, success?: string) {
    if (!agentId) return
    setBusy(true)
    setError("")
    setMsg("")
    try {
      await work()
      await refresh(agentId)
      if (success) setMsg(success)
    } catch (err: unknown) {
      setError(formatContextRepoError(err))
    } finally {
      setBusy(false)
    }
  }

  async function onInspect(entry: ContextEntry) {
    if (!agentId) return
    setBusy(true)
    setError("")
    try {
      const next = await getContextRepoEntry(agentId, entry.id)
      setDetail(next)
    } catch (err: unknown) {
      setError(formatContextRepoError(err))
    } finally {
      setBusy(false)
    }
  }

  async function onPin(entry: ContextEntry) {
    await withBusy(async () => {
      const next = await pinContextRepoEntry(agentId, entry.id, !entry.pinned)
      if (detail?.id === entry.id) setDetail({ ...detail, ...next })
    }, entry.pinned ? `Unpinned “${titleOf(entry)}”.` : `Pinned “${titleOf(entry)}”.`)
  }

  async function onDelete(entry: ContextEntry) {
    if (!window.confirm(`Remove “${titleOf(entry)}”? You can undo this from History.`)) return
    await withBusy(async () => {
      await deleteContextRepoEntry(agentId, entry.id)
      if (detail?.id === entry.id) setDetail(null)
    }, `Removed “${titleOf(entry)}”.`)
  }

  async function onAdd(event: FormEvent) {
    event.preventDefault()
    if (!agentId) return
    await withBusy(async () => {
      const created = await createContextRepoEntry(agentId, {
        category: addCategory,
        title: addTitle,
        content: addContent,
        note: addNote.trim() || null,
        source_type: "manual",
      })
      setDetail(created.entry)
      setAddTitle("")
      setAddContent("")
      setAddNote("")
      setShowAdd(false)
    }, "Note saved.")
  }

  async function onCompare() {
    if (!agentId || fromVersion === "" || toVersion === "") return
    setBusy(true)
    setError("")
    try {
      const next = await getContextRepoDiff(agentId, Number(fromVersion), Number(toVersion))
      setDiff(next)
    } catch (err: unknown) {
      setError(formatContextRepoError(err))
    } finally {
      setBusy(false)
    }
  }

  async function onRevert(record: ContextMutationRecord) {
    const label = actionLabel(record.action)
    const title = titleOf(record.after || record.before)
    if (!window.confirm(`Undo this change (“${label}” on “${title}”)? The previous version of this note will come back.`)) {
      return
    }
    await withBusy(async () => {
      await revertContextRepoMutation(agentId, record.mutation_id)
      setDiff(null)
    }, `Undid “${label}” on “${title}”.`)
  }

  const preferredNodes: ContextConsolidationNode[] = schedule?.preferred?.length
    ? schedule.preferred
    : (schedule?.nodes || []).filter((node) => node.preferred)

  return (
    <div className="context-page">
      <h1>Context</h1>
      <p className="lede">
        Curated notes this agent keeps — who it is, projects, how-tos, lessons, priorities, and written skills.
        Every change is recorded and can be undone. Skills that run themselves still live on{" "}
        <Link to="/memory">Memory</Link>.
      </p>

      {msg && (
        <div className="card" style={{ marginBottom: 16, borderLeft: "4px solid var(--ok)", padding: "12px 16px" }}>
          {msg}
        </div>
      )}
      {error && (
        <div className="card" style={{ marginBottom: 16, borderLeft: "4px solid var(--bad)", padding: "12px 16px" }}>
          {error}
        </div>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <label>
          Agent
          <select
            value={agentId}
            aria-label="Agent"
            onChange={(event) => {
              setAgentId(event.target.value)
              setDetail(null)
              setDiff(null)
              setMsg("")
              setError("")
            }}
          >
            {profiles.length === 0 && <option value="">No agents yet</option>}
            {profiles.map((profile) => (
              <option key={profile.id} value={profile.id}>
                {profile.name || profile.id}
              </option>
            ))}
          </select>
        </label>
        {profiles.length === 0 && (
          <p className="lede" style={{ margin: "10px 0 0" }}>
            Create an agent first on <Link to="/agents">Agents</Link>, then come back to inspect its saved notes.
          </p>
        )}
        {repo && (
          <div className="lede" style={{ margin: "10px 0 0" }}>
            Version {repo.version}
            {repo.parent_version != null ? ` · from ${repo.parent_version}` : ""}
            {" · "}{activeEntries.length} note{activeEntries.length === 1 ? "" : "s"}
            {" · "}updated {formatWhen(repo.created_at)}
          </div>
        )}
      </div>

      <div className="tabs">
        <button className={tab === "notes" ? "btn" : "btn secondary"} type="button" onClick={() => setTab("notes")}>
          Notes
        </button>
        <button className={tab === "compare" ? "btn" : "btn secondary"} type="button" onClick={() => setTab("compare")}>
          Compare
        </button>
        <button className={tab === "history" ? "btn" : "btn secondary"} type="button" onClick={() => setTab("history")}>
          History
        </button>
      </div>

      {tab === "notes" && (
        <div className="grid two context-notes">
          <div>
            <div className="row" style={{ marginBottom: 12, justifyContent: "space-between" }}>
              <div className="row">
                <button
                  className={filter === "all" ? "btn" : "btn secondary"}
                  type="button"
                  onClick={() => setFilter("all")}
                >
                  All
                </button>
                {CONTEXT_ENTRY_CATEGORIES.map((category) => (
                  <button
                    key={category}
                    className={filter === category ? "btn" : "btn secondary"}
                    type="button"
                    onClick={() => setFilter(category)}
                  >
                    {categoryLabel(category)}
                  </button>
                ))}
              </div>
              <button className="btn" type="button" disabled={!agentId} onClick={() => setShowAdd((open) => !open)}>
                {showAdd ? "Close" : "Add a note"}
              </button>
            </div>

            {showAdd && (
              <form className="card" style={{ marginBottom: 16 }} onSubmit={onAdd}>
                <h2>Add a note</h2>
                <p className="lede" style={{ margin: "0 0 12px" }}>
                  This is curated text you choose to keep. It does not change agent policy on its own.
                </p>
                <label>
                  Kind
                  <select value={addCategory} onChange={(event) => setAddCategory(event.target.value)}>
                    {CONTEXT_ENTRY_CATEGORIES.map((category) => (
                      <option key={category} value={category}>
                        {categoryLabel(category)}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Title
                  <input
                    type="text"
                    value={addTitle}
                    onChange={(event) => setAddTitle(event.target.value)}
                    required
                  />
                </label>
                <label>
                  Note
                  <textarea
                    className="field"
                    rows={5}
                    value={addContent}
                    onChange={(event) => setAddContent(event.target.value)}
                    required
                  />
                </label>
                <label>
                  Why you are saving this (optional)
                  <input
                    type="text"
                    value={addNote}
                    onChange={(event) => setAddNote(event.target.value)}
                  />
                </label>
                <div className="row" style={{ marginTop: 12 }}>
                  <button className="btn" type="submit" disabled={busy || !addTitle.trim() || !addContent.trim()}>
                    Save note
                  </button>
                </div>
              </form>
            )}

            {!agentId && <p className="lede">Pick an agent to inspect its notes.</p>}
            {agentId && !filteredEntries.length && (
              <p className="lede">No notes in this view yet. Add one, or wait for idle tidy-up to suggest lessons.</p>
            )}
            {grouped.map((group) => (
              <div key={group.category} style={{ marginBottom: 18 }}>
                <h2>{categoryLabel(group.category)}</h2>
                {group.entries.map((entry) => (
                  <EntryCard
                    key={entry.id}
                    entry={entry}
                    selected={detail?.id === entry.id}
                    others={activeEntries}
                    onOpen={() => onInspect(entry)}
                    onPin={() => onPin(entry)}
                    onDelete={() => onDelete(entry)}
                    busy={busy}
                  />
                ))}
              </div>
            ))}
          </div>

          <div>
            <div className="card">
              <h2>Inspect</h2>
              {!detail && <p className="lede" style={{ margin: 0 }}>Open a note to see the full text, who wrote it, and any access rules.</p>}
              {detail && (
                <div>
                  <div className="kv" style={{ marginBottom: 12 }}>
                    <b>Title</b><span>{titleOf(detail)}</span>
                    <b>Kind</b><span>{categoryLabel(detail.category)}</span>
                    <b>Pinned</b><span>{detail.pinned ? "Yes — kept unless you unpin" : "No"}</span>
                    <b>Source</b><span>{provenanceLine(detail.provenance)}</span>
                    <b>Saved</b><span>{formatWhen(detail.provenance?.created_at)}</span>
                  </div>
                  {detail.conflicts_with?.length > 0 && (
                    <p className="lede" style={{ color: "var(--warn)" }}>
                      This note conflicts with another saved note. Both were kept instead of overwriting.
                    </p>
                  )}
                  <pre className="pack-change-json">{detail.content}</pre>
                  <h3 style={{ margin: "16px 0 8px", fontSize: 15 }}>Who can use this</h3>
                  {(!detail.permissions || detail.permissions.length === 0) && (
                    <p className="lede" style={{ margin: 0 }}>
                      No extra access rules. This note follows the agent’s usual policy.
                    </p>
                  )}
                  {(detail.permissions || []).map((row, index) => (
                    <div className="lede" key={`${row.principal_id}-${index}`} style={{ margin: "0 0 6px" }}>
                      {permissionLabel(row.permission)} · {row.principal_type} {row.principal_id}
                      {row.created_at ? ` · ${formatWhen(row.created_at)}` : ""}
                    </div>
                  ))}
                  <div className="row" style={{ marginTop: 12 }}>
                    <button className="btn secondary" type="button" disabled={busy} onClick={() => onPin(detail)}>
                      {detail.pinned ? "Unpin" : "Pin"}
                    </button>
                    <button
                      className="btn danger"
                      type="button"
                      disabled={busy || detail.pinned}
                      onClick={() => onDelete(detail)}
                    >
                      Remove
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {tab === "compare" && (
        <div className="card">
          <h2>Compare versions</h2>
          <p className="lede">
            See what was added, removed, or changed between two saved versions. Conflicting notes stay visible instead of being overwritten.
          </p>
          {versions.length < 1 && <p className="lede">No versions on file yet. Add a note first.</p>}
          {versions.length >= 1 && (
            <div className="row" style={{ marginBottom: 16, alignItems: "flex-end" }}>
              <label style={{ minWidth: 180 }}>
                From
                <select
                  value={fromVersion}
                  onChange={(event) => setFromVersion(event.target.value ? Number(event.target.value) : "")}
                >
                  {versions.map((item) => (
                    <option key={`from-${item.version}`} value={item.version}>
                      Version {item.version} · {item.entry_count} notes · {formatWhen(item.created_at)}
                    </option>
                  ))}
                </select>
              </label>
              <label style={{ minWidth: 180 }}>
                To
                <select
                  value={toVersion}
                  onChange={(event) => setToVersion(event.target.value ? Number(event.target.value) : "")}
                >
                  {versions.map((item) => (
                    <option key={`to-${item.version}`} value={item.version}>
                      Version {item.version} · {item.entry_count} notes · {formatWhen(item.created_at)}
                    </option>
                  ))}
                </select>
              </label>
              <button
                className="btn"
                type="button"
                disabled={busy || fromVersion === "" || toVersion === ""}
                onClick={onCompare}
              >
                Compare
              </button>
            </div>
          )}
          {diff && (
            <div>
              <p className="lede">
                Version {diff.from_version} → {diff.to_version}
                {diff.conflicts_flagged.length
                  ? ` · ${diff.conflicts_flagged.length} conflict${diff.conflicts_flagged.length === 1 ? "" : "s"} kept`
                  : ""}
              </p>
              {diff.conflicts_flagged.length > 0 && (
                <p className="lede" style={{ color: "var(--warn)" }}>
                  Conflicting notes were flagged, not overwritten.
                </p>
              )}
              {!diff.added.length && !diff.removed.length && !diff.changed.length && (
                <p className="lede">These versions look the same.</p>
              )}
              {diff.added.map((entry) => (
                <DiffEntry key={`add-${entry.id}`} entry={entry} kind="added" />
              ))}
              {diff.removed.map((entry) => (
                <DiffEntry key={`rem-${entry.id}`} entry={entry} kind="removed" />
              ))}
              {diff.changed.map((change) => (
                <div className="pack-change update" key={`chg-${change.after.id}`}>
                  <div className="row" style={{ justifyContent: "space-between" }}>
                    <strong>{titleOf(change.after)}</strong>
                    <span className="badge waiting">Changed</span>
                  </div>
                  <div className="grid two" style={{ marginTop: 8 }}>
                    <div>
                      <div className="lede" style={{ margin: "0 0 4px" }}>Before</div>
                      <pre className="pack-change-json">{change.before.content}</pre>
                    </div>
                    <div>
                      <div className="lede" style={{ margin: "0 0 4px" }}>After</div>
                      <pre className="pack-change-json">{change.after.content}</pre>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === "history" && (
        <div className="card">
          <h2>History</h2>
          <p className="lede">Every change, who it came from, and whether it can be undone. The database stays the source of truth.</p>
          {!history.length && <p className="lede">No changes recorded yet.</p>}
          {history.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Change</th>
                  <th>Note</th>
                  <th>Provenance</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {history.map((record) => {
                  const canRevert = record.reversible && !record.reverted_by
                  return (
                    <tr key={record.mutation_id}>
                      <td>{formatWhen(record.created_at)}</td>
                      <td>
                        <span className={`badge ${actionBadge(record.action)}`}>{actionLabel(record.action)}</span>
                        <div className="lede" style={{ margin: "4px 0 0" }}>
                          v{record.version_before} → v{record.version_after}
                        </div>
                      </td>
                      <td>{titleOf(record.after || record.before)}</td>
                      <td>
                        {provenanceLine(record.source)}
                        {record.reverted_by ? " · already undone" : ""}
                      </td>
                      <td>
                        {canRevert ? (
                          <button className="btn secondary" type="button" disabled={busy} onClick={() => onRevert(record)}>
                            Undo
                          </button>
                        ) : (
                          <span className="lede">{record.reverted_by ? "Undone" : "—"}</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      <details
        className="card"
        style={{ marginTop: 16 }}
        open={showSchedule}
        onToggle={(event) => setShowSchedule((event.target as HTMLDetailsElement).open)}
      >
        <summary className="lede" style={{ cursor: "pointer", margin: 0 }}>
          Quiet machines for idle tidy-up (optional)
        </summary>
        <p className="lede" style={{ margin: "10px 0 0" }}>
          Background tidy-up prefers idle or junior machines. This is a hint only — it is not the main page, and it does not change policy.
        </p>
        {(!schedule || !(schedule.nodes || []).length) && (
          <p className="lede">No machines reported a preference.</p>
        )}
        {(preferredNodes.length ? preferredNodes : schedule?.nodes || []).map((node) => (
          <div className="lede" key={node.node_id || node.hostname} style={{ margin: "0 0 6px" }}>
            {node.hostname || node.node_id || "Machine"}
            {node.preferred ? " · preferred" : ""}
            {node.status ? ` · ${node.status}` : ""}
            {node.class ? ` · ${String(node.class).replaceAll("_", " ")}` : ""}
          </div>
        ))}
      </details>
    </div>
  )
}
