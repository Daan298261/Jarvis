import { Link } from "react-router-dom"
import { AutonomySection } from "../pages/Autonomy"
import { ComputerUsePermissions } from "../pages/ComputerUsePermissions"

type AdvancedSettingsPaneProps = {
  settings: Record<string, unknown>
  queueStatus: Record<string, unknown> | null
  save: (patch: Record<string, unknown>) => Promise<void>
}

export function AdvancedSettingsPane({ settings, queueStatus, save }: AdvancedSettingsPaneProps) {
  const selfDev = (settings.self_dev && typeof settings.self_dev === "object"
    ? settings.self_dev
    : {}) as Record<string, unknown>
  const browser = (settings.browser && typeof settings.browser === "object"
    ? settings.browser
    : {}) as Record<string, unknown>
  const allowedDirs = Array.isArray(settings.allowed_directories) ? settings.allowed_directories : []

  return (
    <>
      <div className="card grid settings-pane-card">
        <h2>License</h2>
        <p className="lede" style={{ margin: "0 0 12px" }}>
          Local models are yours; the Jarvis subscription is managed on the license page.
        </p>
        <div className="row">
          <Link className="btn" to="/license">
            Open license page
          </Link>
        </div>
      </div>

      <AutonomySection />

      <div className="card grid settings-pane-card">
        <h2>Agent profiles</h2>
        <p className="lede" style={{ margin: "0 0 12px" }}>
          A short interview for how a specialist should behave — mission, tone, what it may do,
          what needs your OK, and how much freedom it has. Not a server console.
        </p>
        <div className="row">
          <Link className="btn" to="/agents">
            Open agent interview
          </Link>
        </div>
      </div>

      <div className="card grid settings-pane-card">
        <h2>Advisor</h2>
        <p className="lede" style={{ margin: "0 0 12px" }}>
          When a local job is stuck, preview exactly what would leave this PC, then ask for
          recommendations. The advisor has no tools and cannot act. You keep execution.
        </p>
        <div className="row">
          <Link className="btn" to="/advisor">
            Open advisor
          </Link>
        </div>
      </div>

      <div className="card grid settings-pane-card">
        <h2>Trajectories</h2>
        <p className="lede" style={{ margin: "0 0 12px" }}>
          Import a Cursor transcript or record a finished Jarvis task. Imported records are
          evidence only — they do not grant capabilities or change policy. Skills stay on Memory.
        </p>
        <div className="row">
          <Link className="btn" to="/trajectories">
            Open trajectories
          </Link>
        </div>
      </div>

      <div className="card grid settings-pane-card">
        <h2>Coding isolation</h2>
        <p className="lede" style={{ margin: "0 0 12px" }}>
          Parallel coding tasks each get a Git worktree. Integrate is blocked until a verifier or
          you approve — nothing lands silently. Conflicts wait in Decision Inbox.
        </p>
        <div className="row">
          <Link className="btn" to="/coding">
            Open coding isolation
          </Link>
        </div>
      </div>

      <div className="card grid settings-pane-card">
        <h2>Core execution</h2>
        <p className="lede" style={{ margin: "0 0 12px" }}>
          How strictly Jarvis asks before risky tools. How long a job stays open, and whether Jarvis
          may start work on its own, is in Stay with a job &amp; Away Mode above. Model profile and vision
          are under Models / Inference.
        </p>
        <label>Ask before risky tools
          <select value={String(settings.autonomy || "interactive")} onChange={(e) => save({ autonomy: e.target.value })}>
            <option value="interactive">Interactive</option>
            <option value="trusted">Trusted</option>
            <option value="autonomous">Autonomous</option>
          </select>
        </label>
        <label>Execution mode
          <select
            value={String(settings.execution_mode || "balanced")}
            onChange={(e) => save({ execution_mode: e.target.value })}
          >
            <option value="fast">Fast</option>
            <option value="balanced">Balanced</option>
            <option value="reliable">Reliable</option>
          </select>
        </label>
        <label>Default timeout (seconds)
          <input
            type="number"
            value={Number(settings.default_timeout_seconds ?? 0)}
            onChange={(e) => save({ default_timeout_seconds: Number(e.target.value) })}
          />
        </label>
        <label>Retry limit
          <input
            type="number"
            value={Number(settings.retry_limit ?? 0)}
            onChange={(e) => save({ retry_limit: Number(e.target.value) })}
          />
        </label>
        <label>Allowed directories (one per line)
          <textarea
            className="field"
            rows={4}
            defaultValue={allowedDirs.join("\n")}
            onBlur={(e) =>
              save({
                allowed_directories: e.target.value
                  .split("\n")
                  .map((s) => s.trim())
                  .filter(Boolean),
              })
            }
          />
        </label>
        <label className="row">
          <input
            type="checkbox"
            checked={Boolean(browser.headless)}
            onChange={(e) => save({ browser_headless: e.target.checked })}
          />
          Headless browser
        </label>
        <label className="row">
          <input
            type="checkbox"
            checked={Boolean(settings.backup_enabled)}
            onChange={(e) => save({ backup_enabled: e.target.checked })}
          />
          Create backups before overwriting files
        </label>
      </div>

      <ComputerUsePermissions />

      <div className="card grid settings-pane-card">
        <h2>Self-development trial budget</h2>
        <p className="lede" style={{ margin: "0 0 12px" }}>
          Isolated worktrees never auto-merge. Paid workers stay off unless you set a spend or invocation limit above zero.{" "}
          <Link to="/system">System</Link> also shows self-dev status.
        </p>
        <label>Maximum duration (hours)
          <input
            type="number"
            value={Number(selfDev.max_duration_hours ?? 12)}
            onChange={(e) => save({ self_dev_max_duration_hours: Number(e.target.value) })}
          />
        </label>
        <label>Maximum paid spend (€)
          <input
            type="number"
            value={Number(selfDev.max_paid_spend_eur ?? 0)}
            onChange={(e) => save({ self_dev_max_paid_spend_eur: Number(e.target.value) })}
          />
        </label>
        <label>Maximum paid worker invocations
          <input
            type="number"
            value={Number(selfDev.max_paid_invocations ?? 0)}
            onChange={(e) => save({ self_dev_max_paid_invocations: Number(e.target.value) })}
          />
        </label>
        <label>Maximum consecutive failures
          <input
            type="number"
            value={Number(selfDev.max_consecutive_failures ?? 3)}
            onChange={(e) => save({ self_dev_max_consecutive_failures: Number(e.target.value) })}
          />
        </label>
        <label>Experimental Jarvis port
          <input
            type="number"
            value={Number(selfDev.experimental_port ?? 4781)}
            onChange={(e) => save({ self_dev_experimental_port: Number(e.target.value) })}
          />
        </label>
      </div>

      {queueStatus && (
        <div className="card grid settings-pane-card">
          <h2>Launch &amp; Task Queue</h2>
          <p className="lede">
            Queue directory: <code>{String(queueStatus.queue_directory ?? "")}</code>. Drop any <code>.json</code> or{" "}
            <code>.prompt</code> file to automatically run on launch or in background.
          </p>
          <div className="kv">
            <b>Pending files</b><span>{String(queueStatus.pending_count ?? 0)}</span>
            <b>Processed files</b><span>{(queueStatus.processed as unknown[])?.length || 0}</span>
            <b>Failed files</b><span>{(queueStatus.failed as unknown[])?.length || 0}</span>
          </div>
        </div>
      )}
    </>
  )
}
