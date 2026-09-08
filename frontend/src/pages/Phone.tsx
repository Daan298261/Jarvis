import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { api, apiForm, fetchAudio, getAuthUrl, getPrivateKey, setPrivateKey, type Task } from "../api"

type VoiceStatus = { stt_ready?: boolean; tts_ready?: boolean; detail?: string }
type PairingResult = { urls: string[]; expires_in_seconds: number }

type MobileInfo = {
  lan_access?: boolean
  auth_required?: boolean
  has_key?: boolean
  bind_port?: number
  urls?: { lan?: string[]; lan_phone?: string[]; phone?: string }
  pairing?: { install?: string; auth?: string; lan?: string }
  package?: { apk_ready?: boolean; apk_download?: string; pwa_ready?: boolean; build_script?: string }
}

export function PhonePage() {
  const navigate = useNavigate()
  const [info, setInfo] = useState<MobileInfo | null>(null)
  const [prompt, setPrompt] = useState("")
  const [keyInput, setKeyInput] = useState(getPrivateKey())
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState("")
  const [pairUrl, setPairUrl] = useState("")
  const [recent, setRecent] = useState<Task[]>([])
  const [active, setActive] = useState<Task | null>(null)
  const [voice, setVoice] = useState<VoiceStatus | null>(null)
  const [recording, setRecording] = useState(false)
  const [speakResults, setSpeakResults] = useState(false)
  const [apkBuilding, setApkBuilding] = useState(false)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const spokenRef = useRef<string>("")
  const standalone = typeof window !== "undefined" && window.matchMedia("(display-mode: standalone)").matches

  async function refreshMobile() {
    const next = await api<MobileInfo>("/api/mobile")
    setInfo(next)
    if (next.package?.apk_ready) setApkBuilding(false)
    return next
  }

  async function refreshLists(preferredId?: string) {
    const tasks = await api<Task[]>("/api/tasks").catch(() => [] as Task[])
    setRecent(tasks.slice(0, 8))
    const running = tasks.find((task) => ["running", "queued", "waiting"].includes(task.status))
    const chosen = (preferredId && tasks.find((task) => task.id === preferredId)) || running || tasks[0] || null
    if (chosen) {
      const detail = await api<Task>(`/api/tasks/${chosen.id}`).catch(() => chosen)
      setActive(detail)
    } else {
      setActive(null)
    }
  }

  useEffect(() => {
    refreshMobile().catch(() => undefined)
    api<VoiceStatus>("/api/voice/status").then(setVoice).catch(() => undefined)
    refreshLists().catch(() => undefined)

    const token = new URLSearchParams(window.location.search).get("pair_token")
    if (token) {
      api<{ ok: boolean; private_key: string }>("/api/mobile/pair/exchange", {
        method: "POST",
        body: JSON.stringify({ token }),
      })
        .then((result) => {
          setPrivateKey(result.private_key)
          setKeyInput(result.private_key)
          setMsg("This phone is paired with Jarvis. The pairing link has been consumed.")
          const clean = new URL(window.location.href)
          clean.searchParams.delete("pair_token")
          window.history.replaceState({}, "", `${clean.pathname}${clean.search}${clean.hash}`)
          return refreshMobile()
        })
        .catch((err) => setMsg(err instanceof Error ? err.message : "Pairing failed"))
    }
  }, [])

  useEffect(() => {
    if (!apkBuilding) return
    const timer = window.setInterval(() => refreshMobile().catch(() => undefined), 3000)
    return () => window.clearInterval(timer)
  }, [apkBuilding])

  useEffect(() => {
    if (!active?.id || !["running", "queued", "waiting"].includes(active.status)) return
    const timer = window.setInterval(() => {
      api<Task>(`/api/tasks/${active.id}`).then(setActive).catch(() => undefined)
    }, 2000)
    return () => window.clearInterval(timer)
  }, [active?.id, active?.status])

  useEffect(() => {
    if (!speakResults || !active || active.status !== "completed" || !active.result) return
    const key = `${active.id}:${active.result}`
    if (spokenRef.current === key) return
    spokenRef.current = key
    fetchAudio("/api/voice/speak", { method: "POST", body: JSON.stringify({ text: active.result.slice(0, 800) }) })
      .then((blob) => {
        const url = URL.createObjectURL(blob)
        const audio = new Audio(url)
        audio.onended = () => URL.revokeObjectURL(url)
        return audio.play()
      })
      .catch(() => undefined)
  }, [speakResults, active?.id, active?.status, active?.result])

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

  async function share(text: string) {
    if (navigator.share) {
      try {
        await navigator.share({ title: "Pair Jarvis phone", text, url: text })
        return
      } catch {
        // Fall through to clipboard.
      }
    }
    await copy(text)
  }

  async function createPairing() {
    setBusy(true)
    try {
      const result = await api<PairingResult>("/api/mobile/pairing", { method: "POST", body: "{}" })
      const url = result.urls?.[0] || ""
      setPairUrl(url)
      if (url) {
        await copy(url)
        setMsg(`One-time pairing link copied. It expires in ${Math.round(result.expires_in_seconds / 60)} minutes.`)
      } else {
        setMsg("Jarvis could not determine a LAN address. Enable LAN access or Tailscale first.")
      }
      await refreshMobile()
    } catch (err: any) {
      setMsg(err.message || "Could not create pairing link")
    } finally {
      setBusy(false)
    }
  }

  async function buildApk(installTools = false) {
    setBusy(true)
    try {
      await api("/api/mobile/apk/build", {
        method: "POST",
        body: JSON.stringify({ install_build_tools: installTools }),
      })
      setApkBuilding(true)
      setMsg("Android build started on the PC. Jarvis will expose the APK here when it is ready.")
    } catch (err: any) {
      setMsg(err.message || "Could not start Android build")
    } finally {
      setBusy(false)
    }
  }

  async function submit() {
    if (!prompt.trim()) return
    setBusy(true)
    try {
      const created = await api<Task>("/api/tasks", { method: "POST", body: JSON.stringify({ prompt }) })
      setPrompt("")
      await refreshLists(created.id)
      setMsg("Task started on the PC.")
    } catch (err: any) {
      setMsg(err.message || "Could not start task")
    } finally {
      setBusy(false)
    }
  }

  async function cancelActive() {
    if (!active) return
    await api(`/api/tasks/${active.id}/cancel`, { method: "POST" }).catch(() => undefined)
    await refreshLists(active.id)
  }

  async function continueActive() {
    if (!active) return
    await api(`/api/tasks/${active.id}/continue`, { method: "POST", body: JSON.stringify({ prompt: "Continue this." }) }).catch(() => undefined)
    await refreshLists(active.id)
  }

  async function speakNow() {
    const text = (active?.result || active?.verification || "").slice(0, 800)
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

  async function toggleRecord() {
    if (recording) {
      recorderRef.current?.stop()
      return
    }
    if (!voice?.stt_ready) {
      setMsg(voice?.detail || "Local speech recognition is not installed. Type the command instead.")
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const recorder = new MediaRecorder(stream)
      chunksRef.current = []
      recorder.ondataavailable = (event) => { if (event.data.size) chunksRef.current.push(event.data) }
      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop())
        setRecording(false)
        setBusy(true)
        try {
          const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" })
          const body = new FormData()
          body.append("audio", blob, "phone.webm")
          const created = await apiForm<Task>("/api/voice/listen", body)
          await refreshLists((created as any).task_id || (created as any).id)
          setMsg("Voice command sent to the PC.")
        } catch (err: any) {
          setMsg(err.message || "Voice command failed")
        } finally {
          setBusy(false)
        }
      }
      recorderRef.current = recorder
      recorder.start()
      setRecording(true)
    } catch (err: any) {
      setMsg(err.message || "Microphone is not available")
    }
  }

  const lan = info?.urls?.lan || []
  const phoneUrls = info?.urls?.lan_phone || []
  const live = active && ["running", "queued", "waiting"].includes(active.status)
  const events = (active?.events || []).slice(-8)

  return (
    <div className="phone-page">
      <h1>Phone</h1>
      <p className="lede">Pair Android with Jarvis once. LAN works directly; Tailscale is the recommended remote path without public router forwarding.</p>

      {msg && <div className="card" style={{ marginBottom: 16, borderLeft: "4px solid var(--ok)", padding: "12px 16px" }}>{msg}</div>}

      <div className="card" style={{ marginBottom: 16 }}>
        <h2>Pair / install</h2>
        <p className="lede">The one-time link does not contain your permanent Jarvis key. It expires after ten minutes and works once.</p>
        <div className="row" style={{ marginTop: 10, flexWrap: "wrap" }}>
          <button className="btn" type="button" disabled={busy} onClick={createPairing}>Create pairing link</button>
          {pairUrl && <button className="btn secondary" type="button" onClick={() => share(pairUrl)}>Share to phone</button>}
          {info?.package?.apk_ready ? (
            <a className="btn secondary" href={getAuthUrl(info.package.apk_download || "/api/mobile/apk")}>Download APK</a>
          ) : (
            <button className="btn secondary" type="button" disabled={busy || apkBuilding} onClick={() => buildApk(false)}>
              {apkBuilding ? "Building APK…" : "Build pre-paired APK"}
            </button>
          )}
        </div>
        {pairUrl && <code style={{ display: "block", marginTop: 12, overflowWrap: "anywhere" }}>{pairUrl}</code>}
        {!info?.package?.apk_ready && (
          <p className="lede" style={{ marginTop: 10 }}>
            APK building needs Android/JDK build tools. If they are missing, use the installable Phone PWA immediately, or run the generated build script with its build-tools option.
          </p>
        )}
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <h2>Command</h2>
        <textarea className="command" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="What should Jarvis do on the PC?" />
        <div className="row" style={{ marginTop: 12, flexWrap: "wrap" }}>
          <button className="btn" disabled={busy} onClick={submit}>Run on PC</button>
          <button className="btn secondary" disabled={busy} type="button" onClick={toggleRecord}>{recording ? "Stop" : "Speak"}</button>
          <label className="lede" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={speakResults} onChange={(e) => setSpeakResults(e.target.checked)} /> Speak results
          </label>
        </div>
        {voice?.detail && <p className="lede" style={{ marginTop: 8 }}>{voice.detail}</p>}
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <h2>Live task</h2>
        {active ? (
          <>
            <div className="kv">
              <b>Task</b><span>{active.title}</span>
              <b>Status</b><span className={`badge ${active.status}`}>{active.status}</span>
              <b>Stage</b><span>{active.stage || "—"}</span>
              <b>Action</b><span>{active.current_action || "—"}</span>
              <b>Tool</b><span>{active.current_tool || "—"}</span>
              <b>Verified</b><span>{active.verification ? "yes" : "pending"}</span>
            </div>
            {active.result && <div className="report" style={{ marginTop: 12 }}>{active.result.slice(0, 600)}</div>}
            {active.error && <p className="lede" style={{ marginTop: 12 }}>{active.error}</p>}
            {events.length > 0 && <ul className="lede" style={{ marginTop: 12 }}>{events.map((event, index) => <li key={`${event.created_at}-${index}`}>{event.title}</li>)}</ul>}
            <div className="row" style={{ marginTop: 12, flexWrap: "wrap" }}>
              {live && <button className="btn secondary" type="button" onClick={cancelActive}>Cancel</button>}
              {!live && <button className="btn secondary" type="button" onClick={continueActive}>Continue</button>}
              <button className="btn secondary" type="button" onClick={speakNow}>Speak result</button>
              <button className="btn secondary" type="button" onClick={() => navigate(`/tasks/${active.id}`)}>Open on PC layout</button>
            </div>
            {active.waiting_for_confirmation && (
              <div className="row" style={{ marginTop: 12 }}>
                <button className="btn" type="button" onClick={() => api(`/api/tasks/${active.id}/continue`, { method: "POST", body: JSON.stringify({ approve: true }) })}>Approve</button>
                <button className="btn secondary" type="button" onClick={() => api(`/api/tasks/${active.id}/continue`, { method: "POST", body: JSON.stringify({ approve: false }) })}>Reject</button>
              </div>
            )}
          </>
        ) : <p className="lede">No task yet. Send a command above.</p>}
      </div>

      <details className="card" style={{ marginBottom: 16 }}>
        <summary>Advanced: private key</summary>
        <p className="lede">Normally the one-time pairing link handles this automatically.</p>
        <div className="row" style={{ marginTop: 8 }}>
          <input type="password" value={keyInput} placeholder="jarvis_pk_..." style={{ fontFamily: "monospace", flex: 1 }} onChange={(e) => setKeyInput(e.target.value)} />
          <button className="btn secondary" type="button" onClick={saveKey}>Save</button>
        </div>
      </details>

      <div className="card" style={{ marginBottom: 16 }}>
        <h2>Network</h2>
        {!standalone && <p className="lede">{info?.pairing?.install || "Add this page to the home screen from Chrome."}</p>}
        {standalone && <p className="lede">Installed as an app on this device.</p>}
        <div className="kv">
          <b>LAN access</b><span>{info?.lan_access ? "on" : "off — onboarding/mobile setup can enable it"}</span>
          <b>Auth</b><span>{info?.auth_required || info?.lan_access ? "private key required" : "localhost only"}</span>
          <b>Key on server</b><span>{info?.has_key ? "yes" : "created automatically when you pair"}</span>
          <b>Remote access</b><span>Tailscale recommended · no public router port required</span>
        </div>
        <div style={{ marginTop: 12 }}>
          {(phoneUrls.length ? phoneUrls : [info?.urls?.phone]).filter(Boolean).map((url: string) => (
            <div className="row" key={url} style={{ marginTop: 8 }}>
              <code style={{ flex: 1, overflowWrap: "anywhere" }}>{url}</code>
              <button className="btn secondary" type="button" onClick={() => copy(url)}>Copy</button>
            </div>
          ))}
          {lan.length === 0 && <p className="lede" style={{ marginTop: 10 }}>No LAN address detected yet. Enable LAN access or configure Tailscale on the PC.</p>}
        </div>
      </div>

      <div className="card">
        <h2>Recent tasks</h2>
        {recent.length === 0 && <p className="lede">No tasks yet.</p>}
        {recent.map((task) => (
          <button key={task.id} className="template-card" style={{ width: "100%", marginTop: 10 }} onClick={() => { setActive(task); refreshLists(task.id).catch(() => undefined) }}>
            <strong>{task.title}</strong><p>{task.status} · {task.stage}</p>
          </button>
        ))}
      </div>
    </div>
  )
}
