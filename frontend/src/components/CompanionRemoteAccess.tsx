import { useCallback, useEffect, useState } from "react"
import { api } from "../api"
import {
  kindLabel,
  reachabilityLabel,
  remoteConnectionBody,
  remoteFormFromSnapshot,
  tailscaleGuide,
  type RemoteForm,
  type RemoteSnapshot,
} from "../companionRemote"

/** RFC-0215 remote (off-LAN) access controls, shared by the pairing panel and companion settings. */
export function CompanionRemoteAccess({ onChanged }: { onChanged?: () => void }) {
  const [snapshot, setSnapshot] = useState<RemoteSnapshot | null>(null)
  const [form, setForm] = useState<RemoteForm>(() => remoteFormFromSnapshot(null))
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState("")

  const load = useCallback(async () => {
    try {
      const next = await api<RemoteSnapshot>("/api/mobile/manage/connection")
      setSnapshot(next)
      setForm(remoteFormFromSnapshot(next))
    } catch (error) {
      setMsg(error instanceof Error ? error.message : String(error))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function apply(next: RemoteForm) {
    setBusy(true)
    setMsg(next.remote ? "Setting up remote access…" : "Turning remote access off…")
    try {
      const result = await api<RemoteSnapshot>("/api/mobile/manage/connection", {
        method: "POST",
        body: JSON.stringify(remoteConnectionBody(next)),
      })
      setSnapshot(result)
      setForm(remoteFormFromSnapshot(result))
      setMsg(next.remote ? "Remote access updated. Unused pairing codes were cancelled; a new one carries the new addresses." : "Remote access is off. Only phones on your home network can connect.")
      onChanged?.()
    } catch (error) {
      setMsg(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card companion-remote-access" style={{ marginTop: 12 }}>
      <label>
        <input
          type="checkbox"
          checked={form.remote}
          disabled={busy}
          onChange={(event) => void apply({ ...form, remote: event.target.checked })}
        />{" "}
        Allow pairing and use from outside my home network
      </label>
      <p className="companion-pairing-hint">
        Off by default. When on, the phone can reach ANZU over Tailscale (both devices signed in to the same
        Tailscale account). Nothing is opened on your router. The server fingerprint and per-phone keys still protect
        every connection.
      </p>

      {form.remote && (
        <>
          <h4>Tailscale</h4>
          <p className="companion-pairing-hint">{tailscaleGuide(snapshot?.tailscale)}</p>
          <label>
            <input
              type="checkbox"
              checked={form.tailscale}
              disabled={busy}
              onChange={(event) => void apply({ ...form, tailscale: event.target.checked })}
            />{" "}
            Use Tailscale addresses
          </label>
          <div className="row">
            <button className="btn secondary" type="button" disabled={busy} onClick={() => void load()}>
              Refresh
            </button>
          </div>

          {snapshot?.reachability && snapshot.reachability.length > 0 && (
            <ul className="companion-remote-reachability">
              {snapshot.reachability.map((item) => (
                <li key={item.url}>
                  {kindLabel(item.kind)}: <code>{item.url}</code> — {reachabilityLabel(item)}
                  {item.detail ? ` (${item.detail})` : ""}
                </li>
              ))}
            </ul>
          )}
          {snapshot?.exposure && <p className="companion-pairing-hint">{snapshot.exposure}</p>}
        </>
      )}
      {msg && <p className="companion-pairing-msg">{msg}</p>}
    </div>
  )
}
