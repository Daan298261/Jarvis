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
      {info?.jarvis_mcp && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2>Jarvis MCP for Cursor</h2>
          <p className="lede">{info.jarvis_mcp.detail}</p>
          <div className="lede"><code>{info.jarvis_mcp.command}</code></div>
        </div>
      )}
      {info?.cursor_acp && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2>Cursor ACP</h2>
          <div className="toggle">
            <div>
              <strong>{info.cursor_acp.command || "agent acp"}</strong>
              <div className="lede" style={{ margin: "4px 0 0" }}>{info.cursor_acp.detail}</div>
            </div>
            <span className={`badge ${info.cursor_acp.available ? "completed" : "queued"}`}>{info.cursor_acp.status}</span>
          </div>
        </div>
      )}
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
