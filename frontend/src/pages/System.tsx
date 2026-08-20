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
      {info?.capabilities && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2>Backends</h2>
          {(info.capabilities.all || []).map((item: any) => (
            <div className="toggle" key={item.id}>
              <div>
                <strong>{item.name}</strong>
                <div className="lede" style={{ margin: "4px 0 0" }}>{item.detail}</div>
              </div>
              <span className={`badge ${item.available ? "completed" : "queued"}`}>{item.status}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
