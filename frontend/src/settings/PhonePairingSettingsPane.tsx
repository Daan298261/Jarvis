import { Link } from "react-router-dom"
import { CompanionPairingPanel } from "../components/CompanionPairingPanel"

export function PhonePairingSettingsPane() {
  return (
    <div className="card grid settings-pane-card">
      <h2>Companion pairing</h2>
      <p className="lede" style={{ margin: "0 0 12px" }}>
        Generate a short-lived 6-digit code for the Android companion app. Regenerating invalidates any
        previous unclaimed code. Code and QR come from the desktop pairing service and stay in sync after you
        prepare the connection.{" "}
        <Link to="/phone">Phone (LAN PWA)</Link> uses a different flow;{" "}
        <Link to="/phone">companion home</Link> covers generic APK install and offline pair.
      </p>
      <CompanionPairingPanel />
    </div>
  )
}
