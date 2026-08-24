import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { api, getPrivateKey, setPrivateKey, type Task } from "../api"

export function PhonePage() {
  const navigate = useNavigate()
  const [info, setInfo] = useState<any>(null)
  const [prompt, setPrompt] = useState("")
  const [keyInput, setKeyInput] = useState(getPrivateKey())
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState("")
  const [recent, setRecent] = useState<Task[]>([])
  const standalone = typeof window !== "undefined" && window.matchMedia("(display-mode: standalone)").matches

  useEffect(() => {
    api<any>("/api/mobile").then(setInfo).catch(() => undefined)
    api<Task[]>("/api/tasks").then((tasks) => setRecent(tasks.slice(0, 6))).catch(() => undefined)
  }, [])

  function saveKey() {
    setPrivateKey(keyInput)
    setMsg("Private key saved on this phone.")
  }

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text)
      setMsg("Copied.")
    } catch {
      setMsg(text)
    }
  }

  async function submit() {
    if (!prompt.trim()) return
    setBusy(true)
    try {
      const created = await api<Task>("/api/tasks", { method: "POST", body: JSON.stringify({ prompt }) })
      setPrompt("")
      navigate(`/tasks/${created.id}`)
    } catch (err: any) {
      setMsg(err.message || "Could not start task")
    } finally {
      setBusy(false)
    }
  }

  const lan = info?.urls?.lan || []
  const phoneUrls = info?.urls?.lan_phone || []

  return (
    <div className="phone-page">
      <h1>Phone</h1>
      <p className="lede">Command Jarvis from Android over the LAN. This page is the installable client.</p>

      {msg && (
        <div className="card" style={{ marginBottom: 16, borderLeft: "4px solid var(--ok)", padding: "12px 16px" }}>
          {msg}
        </div>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <h2>Command</h2>
        <textarea
          className="command"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="What should Jarvis do on the PC?"
        />
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn" disabled={busy} onClick={submit}>Run on PC</button>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <h2>Private key</h2>
        <p className="lede">Required when LAN access is on. Paste it once; it stays in this browser.</p>
        <div className="row" style={{ marginTop: 8 }}>
          <input
            type="password"
            value={keyInput}
            placeholder="jarvis_pk_..."
            style={{ fontFamily: "monospace", flex: 1 }}
            onChange={(e) => setKeyInput(e.target.value)}
          />
          <button className="btn secondary" type="button" onClick={saveKey}>Save</button>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <h2>Pair this phone</h2>
        {!standalone && (
          <p className="lede">{info?.pairing?.install || "Add this page to the home screen from Chrome."}</p>
        )}
        {standalone && <p className="lede">Installed as an app on this device.</p>}
        <div className="kv">
          <b>LAN access</b><span>{info?.lan_access ? "on" : "off — enable in Settings on the PC"}</span>
          <b>Auth</b><span>{info?.auth_required || info?.lan_access ? "private key required" : "localhost only"}</span>
          <b>Key on server</b><span>{info?.has_key ? "yes" : "generate one in Settings"}</span>
        </div>
        <div style={{ marginTop: 12 }}>
          {(phoneUrls.length ? phoneUrls : [info?.urls?.phone]).filter(Boolean).map((url: string) => (
            <div className="row" key={url} style={{ marginTop: 8 }}>
              <code style={{ flex: 1, overflowWrap: "anywhere" }}>{url}</code>
              <button className="btn secondary" type="button" onClick={() => copy(url)}>Copy</button>
            </div>
          ))}
          {lan.length === 0 && (
            <p className="lede" style={{ marginTop: 10 }}>
              No LAN address detected from this process. On the PC, enable LAN access and open this page at the machine&apos;s IPv4 address, port {info?.bind_port || 4780}.
            </p>
          )}
        </div>
      </div>

      <div className="card">
        <h2>Recent tasks</h2>
        {recent.length === 0 && <p className="lede">No tasks yet.</p>}
        {recent.map((task) => (
          <button
            key={task.id}
            className="template-card"
            style={{ width: "100%", marginTop: 10 }}
            onClick={() => navigate(`/tasks/${task.id}`)}
          >
            <strong>{task.title}</strong>
            <p>{task.status} · {task.stage}</p>
          </button>
        ))}
      </div>
    </div>
  )
}
