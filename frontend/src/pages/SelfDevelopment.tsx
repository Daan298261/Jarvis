import { useCallback, useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { api } from "../api"
import "./self-development.css"

type Config = {
  enabled: boolean; resource_hold: string; repo: string; base_ref: string; interval_minutes: number
  max_run_minutes: number; failure_limit: number; ollama_url: string
  coder_model: string; vision_model: string; drive_folder_id: string
  drive_search_tool: string; drive_fetch_tool: string
}
type Item = { id: string; title: string; source: string; revision: string; status: string; url: string }
type Run = {
  id: string; task_id: string; title: string; status: string; worktree: string
  branch: string; base_sha: string; result?: unknown
  task: { current_action?: string; current_tool?: string; result?: string; error?: string; waiting_for_confirmation?: boolean; confirmation_payload?: string }
}
type Check = { command: string[]; returncode: number }
type Finding = { severity: string; file: string; issue: string }
type Delivery = {
  id: string; title: string; stage: string; branch: string; base_sha: string; head_sha: string; repairs: number
  pr: number | null; merge_sha: string; error: string; waiting?: string; authorized_by: string
  tests: { head_sha: string; ok: boolean; checks: Check[] } | null
  review: { head_sha: string; approved: boolean; findings: Finding[]; north_star: string } | null
  history: { stage: string; at: number; detail: string }[]
}
type Build = { merge_sha: string; status: string; attempts: number; error: string; artifact: string; sha256: string; log: string }
type SummaryEntry = { title: string; pr: number | null; merge_sha: string; artifact: string; sha256: string; error: string; tests: { command: string; returncode: number }[] }
type Away = {
  enabled: boolean; activated_at: number; waiting?: string
  summary: null | { since: number; until: number; reason: string; completed: SummaryEntry[]; merged_build_failed: SummaryEntry[]; blocked: SummaryEntry[]; in_progress: SummaryEntry[]; merged_prs: number[] }
}
type State = {
  config: Config; items: Item[]; runs: Run[]; drive_status: string; error: string; failures: number; next_run: number; emergency_stop: boolean
  away: Away; deliveries: Delivery[]; builds: Build[]; status: { phase: string; detail: string }
}
const endpoint = "/api/self-dev/scheduler"

export function SelfDevelopmentPage() {
  const [state, setState] = useState<State | null>(null)
  const [config, setConfig] = useState<Config | null>(null)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const [drive, setDrive] = useState({ file_id: "", title: "", content: "" })
  const [explanation, setExplanation] = useState("")
  const refresh = useCallback(async () => {
    try {
      const result = await api<State>(endpoint)
      setState(result)
      setConfig(current => current || result.config)
    } catch (e) { setError(String(e)) }
  }, [])
  useEffect(() => { void refresh(); const timer = window.setInterval(() => void refresh(), 5000); return () => window.clearInterval(timer) }, [refresh])
  async function action(path: string, body?: unknown, method = "POST") {
    setBusy(true); setError("")
    try {
      await api(endpoint + path, { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) })
      await refresh()
    } catch (e) { setError(String(e)) } finally { setBusy(false) }
  }
  if (!config || !state) return <main className="page"><h1>Self-development</h1><p>{error || "Loading…"}</p></main>
  const textField = (key: keyof Config, label: string) => <label key={key} style={{ display: "grid", gap: 6 }}>{label}<input value={String(config[key])} onChange={e => setConfig({ ...config, [key]: e.target.value })} /></label>
  const numberField = (key: "interval_minutes" | "max_run_minutes" | "failure_limit", label: string) => <label key={key} style={{ display: "grid", gap: 6 }}>{label}<input type="number" min="1" value={config[key]} onChange={e => setConfig({ ...config, [key]: Number(e.target.value) })} /></label>
  return <main className="page self-development-page" style={{ maxWidth: 1100, margin: "0 auto", padding: 24 }}>
    <h1>Self-development</h1>
    <p>Let your local Qwen worker develop ANZU, one RFC at a time. Choose the work, schedule it, and review the tested changes.</p>
    <p><Link to="/coding">Coding review</Link> · <Link to="/mcp">Connections</Link> · <Link to="/tools">Tool permissions</Link></p>
    {(error || state.error) && <p role="alert">{error || state.error}</p>}
    {state.emergency_stop && <p role="alert">ANZU’s emergency stop is active. Resume it in System before starting work.</p>}
    <section className="card self-development-away" style={{ padding: 20, marginBottom: 20 }} aria-label="Away Mode">
      <h2>Away Mode — develop ANZU</h2>
      <label className="self-development-switch">
        <input type="checkbox" role="switch" checked={state.away.enabled} disabled={busy || (state.emergency_stop && !state.away.enabled)}
          onChange={async e => {
            setBusy(true); setError("")
            try {
              const result = await api<State & { explanation: string }>(endpoint + "/away", { method: "PUT", body: JSON.stringify({ enabled: e.target.checked }) })
              setExplanation(result.explanation)
              await refresh()
            } catch (err) { setError(String(err)) } finally { setBusy(false) }
          }} />
        <span>{state.away.enabled ? "On" : "Off"}</span>
      </label>
      {explanation && <p role="status">{explanation}</p>}
      <p role="status"><strong>{state.status.phase}</strong>{state.status.detail ? ` · ${state.status.detail}` : ""}</p>
      <p>You can also say “I’m AFK, go develop yourself” in chat, and “I’m back” to pause. Each change is tested, independently reviewed against the North Star, merged into development only when every check passes, and built into a development installer. Nothing is installed on this PC automatically.</p>
      {state.away.summary && <details open={!state.away.enabled}>
        <summary>While you were away ({new Date(state.away.summary.since * 1000).toLocaleString()} – {new Date(state.away.summary.until * 1000).toLocaleString()})</summary>
        {!state.away.summary.completed.length && !state.away.summary.blocked.length && !state.away.summary.merged_build_failed.length && <p>No tasks finished.</p>}
        {state.away.summary.completed.map(entry => <p key={entry.merge_sha}>✓ {entry.title} · PR #{entry.pr} · <span style={{ overflowWrap: "anywhere" }}>{entry.artifact}</span> · sha256 {entry.sha256.slice(0, 16)} · {entry.tests.filter(t => t.returncode === 0).length}/{entry.tests.length} checks passed</p>)}
        {state.away.summary.merged_build_failed.map(entry => <p key={entry.merge_sha}>Merged, build not ready: {entry.title} · PR #{entry.pr} · {entry.error}</p>)}
        {state.away.summary.blocked.map((entry, index) => <p key={index}>Needs you: {entry.title} · {entry.error}</p>)}
      </details>}
    </section>
    <section className="card" style={{ padding: 20, marginBottom: 20 }}>
      <h2>Local worker</h2>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 16 }}>
        {textField("repo", "Repository folder")}{textField("base_ref", "Development base")}
        {textField("ollama_url", "Ollama address")}{textField("coder_model", "Coding model")}{textField("vision_model", "Vision model")}
        {numberField("interval_minutes", "Run every (minutes)")}{numberField("max_run_minutes", "Mission time limit (minutes)")}
        {numberField("failure_limit", "Pause after consecutive failures")}
        {textField("resource_hold", "Priority work reservation (leave empty when workers are free)")}
      </div>
      <p><label><input type="checkbox" checked={config.enabled} onChange={e => setConfig({ ...config, enabled: e.target.checked })} /> Schedule queued RFCs</label></p>
      <button disabled={busy} onClick={() => void action("", config, "PUT")}>Save settings</button>
      <p>{state.config.enabled ? `Schedule enabled · next check ${new Date(state.next_run * 1000).toLocaleString()}` : "Schedule paused"} · {state.failures} consecutive failures</p>
      {state.config.resource_hold && <p role="status">Local workers reserved: {state.config.resource_hold}. Scheduled work waits until you clear this reservation.</p>}
      <p>Changes stay in a separate checkout for review. Merging and installing require a separate owner action.</p>
    </section>
    <section className="card" style={{ padding: 20, marginBottom: 20 }}>
      <h2>RFC sources</h2><p>{state.drive_status}</p>
      <details><summary>Connect a Drive RFC folder</summary>
        <p>Choose your configured Drive MCP search and fetch tools in Connections. Search must return files/results and a next_page_token; fetch must return plain text content.</p>
        <div style={{ display: "grid", gap: 12 }}>{textField("drive_folder_id", "Drive folder ID")}{textField("drive_search_tool", "Read-only search tool")}{textField("drive_fetch_tool", "Read-only fetch tool")}</div>
        <p>Save settings to enable recurring refresh. An edited RFC needs to be queued again.</p>
      </details>
      <details><summary>Import a Drive RFC snapshot</summary>
        <p>Use this when the Drive connector is not yet configured in ANZU.</p>
        <div style={{ display: "grid", gap: 12 }}>
          <input aria-label="Drive file ID" placeholder="Drive file ID" value={drive.file_id} onChange={e => setDrive({ ...drive, file_id: e.target.value })} />
          <input aria-label="RFC title" placeholder="RFC title" value={drive.title} onChange={e => setDrive({ ...drive, title: e.target.value })} />
          <textarea aria-label="RFC content" rows={6} placeholder="RFC text" value={drive.content} onChange={e => setDrive({ ...drive, content: e.target.value })} />
          <button disabled={busy || !drive.file_id || !drive.content} onClick={() => void action("/drive-import", drive)}>Import RFC</button>
        </div>
      </details>
      <p><button disabled={busy} onClick={() => void action("/scan")}>Scan RFCs</button> <button disabled={busy || state.emergency_stop || !!state.config.resource_hold} onClick={() => void action("/run")}>Run next queued RFC</button> <button disabled={busy} onClick={() => void action("/stop")}>Stop worker and pause schedule</button></p>
      {!state.items.length && <p>Scan your repository’s accepted RFCs or import a Drive RFC to begin.</p>}
      {state.items.map(item => <article key={item.id} style={{ padding: "14px 0", borderTop: "1px solid var(--border, #333)" }}>
        <strong>{item.title}</strong><p>{item.source.startsWith("drive:") ? <a href={item.url} target="_blank" rel="noreferrer">Drive source</a> : item.source.split(":").at(-1)} · {item.status} · revision {item.revision.slice(0, 10)}</p>
        <button disabled={busy || ["unavailable", "needs_refresh", "running"].includes(item.status)} onClick={() => void action(`/items/${item.id}`, { revision: item.revision, queued: item.status !== "queued" })}>{item.status === "queued" ? "Remove from queue" : "Queue this revision"}</button>
      </article>)}
    </section>
    <section className="card" style={{ padding: 20, marginBottom: 20 }}><h2>Deliveries</h2>
      {!state.deliveries.length && <p>No deliveries yet.</p>}
      {[...state.deliveries].reverse().map(delivery => {
        const build = state.builds.find(b => b.merge_sha && b.merge_sha === delivery.merge_sha)
        return <article key={delivery.id} style={{ padding: "14px 0", borderTop: "1px solid var(--border, #333)" }}>
          <strong>{delivery.title}</strong>
          <p>{delivery.stage.replace(/_/g, " ")}{delivery.waiting ? ` · ${delivery.waiting}` : ""}{delivery.repairs ? ` · ${delivery.repairs} repair${delivery.repairs > 1 ? "s" : ""}` : ""}{delivery.pr ? ` · PR #${delivery.pr}` : ""}{delivery.merge_sha ? ` · merged ${delivery.merge_sha.slice(0, 12)}` : ""}</p>
          {delivery.error && <p role="alert">{delivery.error}</p>}
          {delivery.tests && <p>Controller checks at {delivery.tests.head_sha.slice(0, 12)}: {delivery.tests.ok ? "passed" : "failed"} ({delivery.tests.checks.map(c => `${c.command.join(" ")} → ${c.returncode}`).join("; ")})</p>}
          {delivery.review && <details><summary>Independent review: {delivery.review.approved ? "approved" : "changes requested"} at {delivery.review.head_sha.slice(0, 12)}</summary>
            {delivery.review.north_star && <p>{delivery.review.north_star}</p>}
            <ul>{delivery.review.findings.map((f, i) => <li key={i}>[{f.severity}] {f.file}: {f.issue}</li>)}</ul>
          </details>}
          {delivery.stage === "approved" && !state.away.enabled && <button disabled={busy} onClick={() => void action(`/deliveries/${delivery.id}/publish`)}>Publish to development</button>}
          {build && <p>Build: {build.status}{build.attempts ? ` · attempt ${build.attempts}` : ""}{build.artifact ? ` · ${build.artifact} · sha256 ${build.sha256.slice(0, 16)}` : ""}{build.error ? ` · ${build.error}` : ""}</p>}
          {build && ["failed", "pending"].includes(build.status) && <button disabled={busy} onClick={() => void action(`/builds/${build.merge_sha}/retry`)}>{build.status === "failed" ? "Retry build" : "Build now"}</button>}
          <details><summary>Timeline</summary><ul>{delivery.history.map((h, i) => <li key={i}>{new Date(h.at * 1000).toLocaleString()} · {h.stage.replace(/_/g, " ")}{h.detail ? ` · ${h.detail.slice(0, 300)}` : ""}</li>)}</ul></details>
        </article>
      })}
    </section>
    <section className="card" style={{ padding: 20 }}><h2>Missions</h2>
      {!state.runs.length && <p>No missions yet.</p>}
      {[...state.runs].reverse().map(run => <article key={run.id} style={{ padding: "14px 0", borderTop: "1px solid var(--border, #333)" }}>
        <strong>{run.title}</strong><p>{run.status}{run.status === "running" && run.task.current_action ? ` · ${run.task.current_action}` : ""}</p>
        <p style={{ overflowWrap: "anywhere" }}>{run.worktree}<br />{run.branch} · base {run.base_sha.slice(0, 12)}</p>
        {run.task.waiting_for_confirmation && run.status === "running" && <div><p>Worker needs your decision:</p><pre style={{ whiteSpace: "pre-wrap" }}>{run.task.confirmation_payload}</pre><button disabled={busy} onClick={() => void action(`/runs/${run.id}/decision`, { task_id: run.task_id, expected_payload: run.task.confirmation_payload, approved: true })}>Allow once</button> <button disabled={busy} onClick={() => void action(`/runs/${run.id}/decision`, { task_id: run.task_id, expected_payload: run.task.confirmation_payload, approved: false })}>Deny</button></div>}
        {run.task.error && <p role="alert">{run.task.error}</p>}
        {run.task.result && <details><summary>Worker report</summary><pre style={{ whiteSpace: "pre-wrap" }}>{run.task.result}</pre></details>}
        {!!run.result && <details><summary>Verification result</summary><pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(run.result, null, 2)}</pre></details>}
      </article>)}
    </section>
  </main>
}
