import { useEffect, useState } from "react"
import { api } from "../api"

type PermissionItem = {
  id: string
  group: string
  title: string
  detail: string
  persisted: string
  status: string
  gated?: string | null
  offensive?: boolean
  gate_unlocked?: boolean
}

type Snapshot = {
  permissions: PermissionItem[]
}

const GROUP_ORDER = ["computer", "network", "cyber", "blue", "red"]
const GROUP_LABELS: Record<string, string> = {
  computer: "Computer use",
  network: "Network",
  cyber: "HexStrike",
  blue: "Blue team",
  red: "Red team (flags only)",
}

export function ComputerUsePermissions() {
  const [items, setItems] = useState<PermissionItem[]>([])
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)

  async function load() {
    try {
      const data = await api<Snapshot>("/api/permissions")
      setItems(data.permissions || [])
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not load permissions.")
    }
  }

  useEffect(() => {
    void load()
  }, [])

  async function save(id: string, mode: string) {
    setBusy(true)
    setError("")
    try {
      const next = await api<PermissionItem>(`/api/permissions/${id}`, {
        method: "PUT",
        body: JSON.stringify({ mode }),
      })
      setItems((current) => current.map((item) => (item.id === id ? { ...item, ...next } : item)))
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not save that permission.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card grid" style={{ maxWidth: 760, marginTop: 16 }}>
      <h2>Computer use &amp; cyber permissions</h2>
      <p className="lede" style={{ margin: "0 0 12px" }}>
        ChatGPT-style defaults: Jarvis asks before using this PC, worker nodes, the internet, or the local
        network. Red flags never ship exploits — they stay denied unless the Red Team gate is unlocked.
      </p>
      {GROUP_ORDER.map((group) => (
        <section key={group}>
          <h3 style={{ margin: "12px 0 8px", fontSize: 13 }}>{GROUP_LABELS[group]}</h3>
          {items
            .filter((item) => item.group === group)
            .map((item) => (
              <label key={item.id} style={{ display: "block", marginBottom: 10 }}>
                {item.title}
                <select
                  value={item.persisted}
                  disabled={busy}
                  onChange={(event) => void save(item.id, event.target.value)}
                >
                  <option value="ask">Ask each time</option>
                  <option value="always">Always allow</option>
                  <option value="deny">Don&apos;t allow</option>
                </select>
                <span className="lede" style={{ display: "block", marginTop: 4 }}>
                  {item.detail}
                  {item.offensive ? " Flag only — no offensive tools." : ""}
                  {item.gated && !item.gate_unlocked ? ` Locked (${item.gated} gate).` : ""}
                </span>
              </label>
            ))}
        </section>
      ))}
      {error && <p className="lede">{error}</p>}
    </div>
  )
}
