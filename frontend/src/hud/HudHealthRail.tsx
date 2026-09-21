import { Link } from "react-router-dom"
import type { AwayModeState, LicenseStatus, SwarmNode } from "../api"
import { HudLmStudioCatalog } from "../lmstudio/HudLmStudioCatalog"
import { SETUP_PROBLEM_WORKING } from "../setup/ownerFacing"
import type { HealthIssue } from "./systemHealth"

const LICENSE_SETUP_FAIL = new Set([
  "tamper_detected",
  "invalid_signature",
  "expired",
  "cluster_mismatch",
  "unlicensed",
])

type HudHealthRailProps = {
  model: { loaded?: boolean; loading?: boolean; active_model?: string; last_error?: string } | null
  license: LicenseStatus | null
  away: AwayModeState | null
  swarmNodes: SwarmNode[]
  decisionInboxCount: number
  systemDegraded: boolean
  healthIssues?: HealthIssue[]
}

function licenseTone(status: LicenseStatus | null): "ok" | "warn" | "bad" {
  const validation = status?.validation
  const code = String(validation?.status || status?.last_status || "").toLowerCase()
  if (["active", "valid", "grace"].includes(code)) return code === "grace" ? "warn" : "ok"
  if (!status?.lease_present && code === "unlicensed") return "warn"
  if (LICENSE_SETUP_FAIL.has(code) && code !== "unlicensed") return "bad"
  return "warn"
}

export function HudHealthRail({
  model,
  license,
  away,
  swarmNodes,
  decisionInboxCount,
  systemDegraded,
  healthIssues = [],
}: HudHealthRailProps) {
  const onlineNodes = swarmNodes.filter((n) => String(n.status).toLowerCase() === "online").length
  const licTone = licenseTone(license)
  const modelTone = model?.loaded ? "ok" : model?.loading ? "warn" : model?.last_error ? "bad" : "warn"
  const licenseCode = String(license?.validation?.status || license?.last_status || "").toLowerCase()
  const licenseSetupFail = LICENSE_SETUP_FAIL.has(licenseCode)

  return (
    <aside className="hud-rail hud-rail-right" aria-label="System health">
      <div className="hud-rail-head">HEALTH</div>
      <div className="hud-cards">
        <HealthCard
          title="Runtime"
          tone={modelTone}
          value={model?.loaded ? "Model ready" : model?.loading ? "Starting model" : "Model off"}
          detail={model?.active_model || model?.last_error || "Local inference on this PC"}
          href="/model"
        />
        <HealthCard
          title="License"
          tone={licTone}
          value={licenseSetupFail ? "Setup problem" : license?.validation?.status || license?.last_status || "Unknown"}
          detail={
            licenseSetupFail
              ? SETUP_PROBLEM_WORKING
              : license?.validation?.message || license?.last_message || "Local-first entitlement check"
          }
          href="/license"
        />
        <HealthCard
          title="Swarm"
          tone={swarmNodes.length === 0 ? "warn" : onlineNodes === swarmNodes.length ? "ok" : "warn"}
          value={`${onlineNodes}/${swarmNodes.length || 1} online`}
          detail={swarmNodes.length ? "Cluster nodes from /api/swarm" : "Local node only"}
          href="/swarm"
        />
        <HealthCard
          title="Decision inbox"
          tone={decisionInboxCount > 0 ? "warn" : "ok"}
          value={decisionInboxCount > 0 ? `${decisionInboxCount} open` : "Clear"}
          detail="Coding decisions awaiting review"
          href="/coding"
        />
        <HealthCard
          title="Away Mode"
          tone={away?.enabled ? "warn" : "ok"}
          value={away?.enabled ? "Enabled" : "Off"}
          detail={
            away?.enabled
              ? away.pause_proactivity
                ? "New proactive work paused"
                : "Proactivity may continue"
              : "Normal autonomy"
          }
          href="/settings/advanced"
        />
        {systemDegraded && (
          <HealthCard
            title="Status"
            tone="bad"
            value="Degraded"
            detail={healthIssues[0]?.detail || SETUP_PROBLEM_WORKING}
            href={healthIssues[0]?.href || "/system"}
          />
        )}
      </div>
      <div className="hud-catalog-panel">
        <HudLmStudioCatalog />
      </div>
    </aside>
  )
}

function HealthCard({
  title,
  value,
  detail,
  tone,
  href,
}: {
  title: string
  value: string
  detail: string
  tone: "ok" | "warn" | "bad"
  href: string
}) {
  return (
    <Link to={href} className={`hud-card tone-${tone}`}>
      <div className="hud-card-title">{title}</div>
      <div className="hud-card-value">{value}</div>
      <div className="hud-card-detail">{detail}</div>
    </Link>
  )
}
