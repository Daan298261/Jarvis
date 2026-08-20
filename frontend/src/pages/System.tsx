import { useEffect, useState } from "react"
import { api } from "../api"

export function SystemPage() {
  const [info, setInfo] = useState<any>(null)
  useEffect(() => { api("/api/system").then(setInfo) }, [])
  const hw = info?.hardware || {}
  return (
    <div>
      <h1>System</h1>
      <p className="lede">Detected hardware used to tune local inference.</p>
      <div className="grid cards">
        {Object.entries(hw).map(([key, value]) => (
          <div className="card" key={key}>
            <div className="lede" style={{ marginBottom: 6 }}>{key.replaceAll("_", " ")}</div>
            <strong>{String(value)}</strong>
          </div>
        ))}
      </div>
    </div>
  )
}
