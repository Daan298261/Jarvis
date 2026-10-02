import { Link } from "react-router-dom"
import { MobileCompanionSetup } from "../pages/MobileCompanionSetup"

export function PhonePairingSettingsPane() {
  return (
    <div className="card grid settings-pane-card">
      <h2>Companion pairing</h2>
      <p className="lede" style={{ margin: "0 0 12px" }}>
        Prepare companion TLS 4781 (LAN, then UPnP / NAT-PMP / PCP / gateway SSH / reverse tunnel), then
        pair with a 6-digit code. Regenerating invalidates any previous unclaimed code.{" "}
        <Link to="/phone">Phone</Link> is the same Prepare connection flow plus the LAN PWA.
      </p>
      <MobileCompanionSetup />
    </div>
  )
}
