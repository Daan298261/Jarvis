import { useEffect, useRef, useState } from "react"
import { api, fetchAudio, getPrivateKey, setPrivateKey, type Task } from "../api"

type VoiceStatus = { stt_ready?: boolean; tts_ready?: boolean; detail?: string }

export function PhonePage() {
  const [info, setInfo] = useState<any>(null)
  const [prompt, setPrompt] = useState("")
  const [keyInput, setKeyInput] = useState(getPrivateKey())
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState("")
  const [recent, setRecent] = useState<Task[]>([])
  const [task, setTask] = useState<Task | null>(null)
  const [voice, setVoice] = useState<VoiceStatus | null>(null)
  const [speakResults, setSpeakResults] = useState(false)
  const spokenRef = useRef<string>("")
  const standalone = typeof window !== "undefined" && window.matchMedia("(display-mode: standalone)").matches

  async function refreshList() {
    try {
      const tasks = await api<Task[]>("/api/tasks")
      setRecent(tasks.slice(0, 8))
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    api<any>("/api/mobile").then(setInfo).catch(() => undefined)
    api<VoiceStatus>("/api/voice/status").then(setVoice).catch(() => undefined)
    refreshList()
  }, [])

  useEffect(() => {
    if (!task?.id) return
    let timer: number
    const load = async () => {
      try {
        const data = await api<Task>(`/api/tasks/${task.id}`)
        setTask(data)
      } catch {
        /* ignore */
      }
    }
    load()
    timer = window.setInterval(() => load().catch(() => undefined), 2000)
    return () => clearInterval(timer)
  }, [task?.id])

  useEffect(() => {
    if (!speakResults || !task || task.status !== "completed" || !task.result) return
    const key = `${task.id}:${task.result}`
    if (spokenRef.current === key) return
    spokenRef.current = key
    fetchAudio("/api/voice/speak", { method: "POST", body: JSON.stringify({ text: task.result.slice(0, 800) }) })
      .then((blob) => {
        const url = URL.createObjectURL(blob)
        const audio = new Audio(url)
        audio.onended = () => URL.revokeObjectURL(url)
        return audio.play()
      })
      .catch(() => undefined)
  }, [speakResults, task?.id, task?.status, task?.result])

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
      setTask(created)
      setMsg("Task started on the PC.")
      await refreshList()
    } catch (err: any) {
      setMsg(err.message || "Could not start task")
    } finally {
      setBusy(false)
    }
  }

  async function cancel() {
    if (!task) return
    try {
      await api(`/api/tasks/${task.id}/cancel`, { method: "POST" })
      setMsg("Cancel requested.")
    } catch (err: any) {
      setMsg(err.message || "Could not cancel")
    }
  }

  async function continueTask(extra?: string) {
    if (!task) return
    try {
      await api(`/api/tasks/${task.id}/continue`, {
        method: "POST",
        body: JSON.stringify({ prompt: extra || "Continue this." }),
      })
      setMsg("Continue sent.")
    } catch (err: any) {
      setMsg(err.message || "Could not continue")
    }
  }

  async function speakNow() {
    const text = (task?.result || task?.verification || "").slice(0, 800)
    if (!text) {
      setMsg("Nothing to speak yet.")
      return
    }
    try {
      const blob = await fetchAudio("/api/voice/speak", { method: "POST", body: JSON.stringify({ text }) })
      const url = URL.createObjectURL(blob)
      const audio = new Audio(url)
      audio.onended = () => URL.revokeObjectURL(url)
      await audio.play()
    } catch (err: any) {
      setMsg(err.message || "Could not speak")
    }
  }

  const lan = info?.urls?.lan || []
  const phoneUrls = info?.urls?.lan_phone || []
  const live = ["running", "queued", "waiting"].includes(task?.status || "")
  const events = (task?.events || []).slice(-8)

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
        <div className="row" style={{ marginTop: 12, flexWrap: "wrap" }}>
          <button className="btn" disabled={busy} onClick={submit}>Run on PC</button>
          <label className="lede" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={speakResults} onChange={(e) => setSpeakResults(e.target.checked)} />
            Speak results
          </label>
        </div>
        {voice?.detail && <p className="lede" style={{ marginTop: 8 }}>{voice.detail}</p>}
      </div>

      {task && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2>Live task</h2>
          <p className="lede">{task.title}</p>
          <div className="kv" style={{ marginTop: 8 }}>
            <b>Status</b><span>{task.status} · {task.stage}</span>
            <b>Action</b><span>{task.current_action || "—"}</span>
            <b>Tool</b><span>{task.current_tool || "—"}</span>
          </div>
          <div className="row" style={{ marginTop: 12, flexWrap: "wrap" }}>
            {live && <button className="btn secondary" type="button" onClick={cancel}>Cancel</button>}
            {!live && <button className="btn secondary" type="button" onClick={() => continueTask()}>Continue</button>}
            <button className="btn secondary" type="button" onClick={speakNow}>Speak</button>
          </div>
          {task.waiting_for_confirmation && (
            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn" type="button" onClick={() => api(`/api/tasks/${task.id}/continue`, { method: "POST", body: JSON.stringify({ approve: true }) })}>Approve</button>
              <button className="btn secondary" type="button" onClick={() => api(`/api/tasks/${task.id}/continue`, { method: "POST", body: JSON.stringify({ approve: false }) })}>Reject</button>
            </div>
          )}
          {task.result && <pre className="report" style={{ marginTop: 12 }}>{task.result}</pre>}
          {events.length > 0 && (
            <ul className="lede" style={{ marginTop: 12 }}>
              {events.map((event, index) => (
                <li key={`${event.created_at}-${index}`}>{event.title}</li>
              ))}
            </ul>
          )}
        </div>
      )}

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
        {recent.map((item) => (
          <button
            key={item.id}
            className="template-card"
            style={{ width: "100%", marginTop: 10 }}
            onClick={() => setTask(item)}
          >
            <strong>{item.title}</strong>
            <p>{item.status} · {item.stage}</p>
          </button>
        ))}
      </div>
    </div>
  )
}
