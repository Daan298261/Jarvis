import { useEffect, useState } from "react"
import { api } from "../api"

type Snapshot = {
  tailscale: { available: boolean; message: string; endpoints: string[] }
  instructions: string[]
  connection: { endpoints?: string[]; router?: string; limitation?: string; phone_verified?: boolean; connection_mode?: string }
}

export function PhoneConnectionSetup({ onChanged }: { onChanged: () => Promise<void> }) {
  const [info, setInfo] = useState<Snapshot | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState("")
  const [remoteConsent, setRemoteConsent] = useState(false)
  const [routerConsent, setRouterConsent] = useState(false)
  const [publicHost, setPublicHost] = useState("")
  const [router, setRouter] = useState("")
  const [owned, setOwned] = useState(false)
  const [change, setChange] = useState(false)
  const [red, setRed] = useState(false)
  const [question, setQuestion] = useState("")
  const [approval, setApproval] = useState("")
  const [sshUser, setSshUser] = useState("root")
  const [sshIdentity, setSshIdentity] = useState("")
  const refresh = async () => setInfo(await api<Snapshot>("/api/mobile/manage/phone-setup"))
  useEffect(() => { void refresh().catch(() => undefined) }, [])

  async function configure(mode: "lan" | "public_forward" | "tailscale") {
    setBusy(true); setMessage("")
    try {
      await api("/api/mobile/manage/connection", { method: "POST", body: JSON.stringify({
        enabled: true, remote: mode !== "lan", connection_mode: mode, wan_method: "upnp",
        wan_public_host: publicHost.trim(),
      }) })
      await refresh(); await onChanged()
      setMessage(mode === "lan" ? "Remote access disabled. Remove any manual router forwarding yourself." :
        "Connection prepared. Scan the refreshed QR and verify from your phone with Wi-Fi off.")
    } catch (error) { setMessage(String(error)) } finally { setBusy(false) }
  }

  async function advice() {
    setBusy(true); setMessage("")
    try {
      if (approval) await api(`/api/mobile/manage/router-approval/${approval}`, { method: "DELETE" })
      const consent = await api<{ id: string }>("/api/mobile/manage/router-approval", { method: "POST",
        body: JSON.stringify({ router, owned, change_approved: change, red_model_approved: red }) })
      setApproval(consent.id)
      const result = await api<{ text: string }>("/api/mobile/manage/router-advice", { method: "POST",
        body: JSON.stringify({ router, approval_id: consent.id, question: question || "Help connect my phone.",
          use_red_model: red }) })
      setMessage(result.text)
    } catch (error) { setMessage(String(error)) } finally { setBusy(false) }
  }

  async function configureOwnedRouter() {
    setBusy(true); setMessage("")
    try {
      const consent = await api<{ id: string }>("/api/mobile/manage/router-approval", { method: "POST",
        body: JSON.stringify({ router, owned, change_approved: change, red_model_approved: false }) })
      setApproval(consent.id)
      await api("/api/mobile/manage/connection", { method: "POST", body: JSON.stringify({
        enabled: true, remote: true, connection_mode: "public_forward", wan_method: "gateway_ssh",
        gateway_host: router, gateway_user: sshUser, gateway_identity_file: sshIdentity,
        gateway_profile: "openwrt_uci", wan_public_host: publicHost.trim(), router_approval_id: consent.id,
      }) })
      await refresh(); await onChanged()
      setMessage("Router setup completed. Verify from your phone with Wi-Fi off. Disable remote access to remove ANZU's mapping.")
    } catch (error) { setMessage(String(error)) } finally { setBusy(false) }
  }

  return <section aria-label="Phone connection setup">
    <h3>Connect away from home</h3>
    <p>Existing router forwarding can connect your phone from another network. Tailscale is an alternative when forwarding is unavailable.</p>
    <label><input type="checkbox" checked={remoteConsent} onChange={e => setRemoteConsent(e.target.checked)} />
      Enable remote phone access through the authenticated companion gateway</label>
    <div className="row">
      <button className="btn" disabled={busy || !remoteConsent || !routerConsent} onClick={() => void configure("public_forward")}>Try router UPnP</button>
      <button className="btn secondary" disabled={busy || !remoteConsent} onClick={() => void configure("tailscale")}>Use Tailscale</button>
      <button className="btn secondary" disabled={busy} onClick={() => void configure("lan")}>LAN only / remove automatic mapping</button>
    </div>
    <label><input type="checkbox" checked={routerConsent} onChange={e => setRouterConsent(e.target.checked)} />
      I own/administer this router and approve an automatic TCP 4781 mapping to this PC</label>
    {info && <p role="status">{info.connection.phone_verified ? "Remote connection confirmed by your paired phone." :
      "Remote connection has not been confirmed by your phone."} {info.connection.limitation}</p>}
    {info && <p>{info.tailscale.message} <a href="https://tailscale.com/download" target="_blank" rel="noreferrer">Install Tailscale</a></p>}
    <details><summary>Manual port forwarding</summary>
      <ol>{info?.instructions.map(line => <li key={line}>{line}</li>)}</ol>
      <label>Public IPv4 or DNS name <input value={publicHost} onChange={e => setPublicHost(e.target.value)} placeholder="Your public address" /></label>
      <button className="btn secondary" disabled={busy || !remoteConsent || !routerConsent || !publicHost.trim()} onClick={() => void configure("public_forward")}>Apply address and refresh QR</button>
    </details>
    <details><summary>Help with my owned router</summary>
      <label>Router LAN IPv4 <input value={router} onChange={e => setRouter(e.target.value)} placeholder="192.168.1.1" /></label>
      <label><input type="checkbox" checked={owned} onChange={e => setOwned(e.target.checked)} />I own this router and may administer it</label>
      <label><input type="checkbox" checked={change} onChange={e => setChange(e.target.checked)} />I approve setup for forwarding TCP 4781 to this PC only</label>
      <label><input type="checkbox" checked={red} onChange={e => setRed(e.target.checked)} />Separately approve the red-team model for advice about this router and this setup task (30 minutes)</label>
      <label>What do you need help with? <input value={question} onChange={e => setQuestion(e.target.value)} /></label>
      <button className="btn secondary" disabled={busy || !owned || !change || !router} onClick={() => void advice()}>Get setup advice</button>
      <details><summary>Configure an owned OpenWrt router using SSH</summary>
        <p>Preview: create one named TCP 4781 forwarding rule to this PC. Other rules stay unchanged. This uses authenticated router administration and does not call a model.</p>
        <label>SSH username <input value={sshUser} onChange={e => setSshUser(e.target.value)} /></label>
        <label>SSH key file on this PC <input value={sshIdentity} onChange={e => setSshIdentity(e.target.value)} /></label>
        <label>Public IPv4 or DNS name <input value={publicHost} onChange={e => setPublicHost(e.target.value)} /></label>
        <button className="btn secondary" disabled={busy || !remoteConsent || !owned || !change || !router || !sshIdentity || !publicHost}
          onClick={() => void configureOwnedRouter()}>Apply the forwarding rule</button>
      </details>
      {approval && <button className="btn secondary" disabled={busy} onClick={() => {
        void api(`/api/mobile/manage/router-approval/${approval}`, { method: "DELETE" })
          .then(() => { setApproval(""); setRed(false); setMessage("Router and red-model approval revoked.") })
          .catch(error => setMessage(String(error)))
      }}>Revoke setup approval</button>}
    </details>
    {message && <p role="status" style={{ whiteSpace: "pre-wrap" }}>{message}</p>}
  </section>
}
