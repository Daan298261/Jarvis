import { Link } from "react-router-dom"
import { CompanionPairingPanel } from "../components/CompanionPairingPanel"

export function CompanionPairingPage() {
  return (
    <div>
      <h1>Pair phone</h1>
      <p className="lede">
        Generate a short-lived 6-digit code for the Android companion app. Regenerating invalidates any
        previous unclaimed code. Code and QR come from the desktop pairing service and stay in sync after you
        prepare the connection.{" "}
        <Link to="/phone">Phone (LAN PWA)</Link> uses a different flow;{" "}
        <Link to="/phone">companion home</Link> covers generic APK install and offline pair.
      </p>

      <div className="card grid" style={{ maxWidth: 560, marginTop: 16 }}>
        <h2>Companion pairing code</h2>
        <CompanionPairingPanel />
      </div>
    </div>
  )
}
