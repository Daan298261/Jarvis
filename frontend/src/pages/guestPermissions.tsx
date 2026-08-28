import type { GuestEffectivePermissions } from "../api"

function formatExpiry(value: string | null | undefined): string {
  if (!value) return "Never"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

export function EffectivePermissionsView({
  perms,
  title = "Effective permissions",
}: {
  perms: GuestEffectivePermissions
  title?: string
}) {
  const grants = perms.grants || []
  const denied = perms.denied_capabilities || []
  const summary = perms.allowed_actions_summary || {}
  return (
    <div className="effective-panel">
      <h3 style={{ marginTop: 0 }}>{title}</h3>
      <p className="lede" style={{ margin: "0 0 12px" }}>
        Default is deny-all. Only the grants below are allowed. Files, terminal, tools, settings,
        and other admin surfaces stay closed.
      </p>
      <div className="kv" style={{ marginBottom: 12 }}>
        <b>Expires</b>
        <span>{formatExpiry(perms.expires_at)}</span>
        <b>Single use</b>
        <span>{perms.limits?.single_use ? "Yes" : "No"}</span>
        <b>Max sessions</b>
        <span>{perms.limits?.max_sessions ?? "Unlimited"}</span>
        <b>Max uses</b>
        <span>{perms.limits?.max_uses ?? "Unlimited"}</span>
      </div>
      {grants.length === 0 ? (
        <p className="lede" style={{ margin: "0 0 12px" }}>No resources granted. This guest can see nothing.</p>
      ) : (
        <ul className="grant-list">
          {grants.map((grant, index) => (
            <li key={`${grant.resource_type}:${grant.resource_id}:${index}`}>
              <strong>{grant.resource_type}</strong>
              {" "}
              <code>{grant.resource_id}</code>
              {" — "}
              {(grant.actions || []).join(", ") || "no actions"}
            </li>
          ))}
        </ul>
      )}
      {Object.keys(summary).length > 0 && (
        <div className="kv" style={{ marginBottom: 12 }}>
          {Object.entries(summary).map(([key, actions]) => (
            <span key={key} style={{ display: "contents" }}>
              <b>{key}</b>
              <span>{actions.join(", ")}</span>
            </span>
          ))}
        </div>
      )}
      <div className="denied-list" aria-label="Denied capabilities">
        {denied.map((cap) => (
          <span key={cap}>{cap}</span>
        ))}
      </div>
    </div>
  )
}
