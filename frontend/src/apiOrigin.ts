/** Local FastAPI listener used by the desktop installer and Tauri shell. */
export const JARVIS_LOCAL_API_ORIGIN = "http://127.0.0.1:4780"

const LOCAL_API_PORTS = new Set(["", "4780", "5173"])

function hostnameOf(origin: string): string {
  try {
    return new URL(origin).hostname.toLowerCase()
  } catch {
    return ""
  }
}

function portOf(origin: string): string {
  try {
    return new URL(origin).port
  } catch {
    return ""
  }
}

function protocolOf(origin: string): string {
  try {
    return new URL(origin).protocol.toLowerCase()
  } catch {
    return ""
  }
}

/**
 * Same-origin FastAPI (4780) and Vite (5173 + /api proxy) keep relative URLs.
 * Tauri 2 serves the SPA from https://tauri.localhost, so `/api` never reaches
 * the backend — every menu then dies with TypeError: Failed to fetch.
 */
export function jarvisApiBase(origin: string = typeof window === "undefined" ? "" : window.location.origin): string {
  if (!origin) return ""
  const protocol = protocolOf(origin)
  const host = hostnameOf(origin)
  const port = portOf(origin)
  if (protocol === "http:" || protocol === "https:") {
    const loopback = host === "127.0.0.1" || host === "localhost" || host === "[::1]" || host === "::1"
    if (loopback && LOCAL_API_PORTS.has(port)) return ""
    if (host === "tauri.localhost" || host === "asset.localhost" || host.endsWith(".tauri.localhost")) {
      return JARVIS_LOCAL_API_ORIGIN
    }
    return ""
  }
  return JARVIS_LOCAL_API_ORIGIN
}

export function jarvisApiUrl(path: string, origin?: string): string {
  if (/^https?:\/\//i.test(path) || path.startsWith("ws://") || path.startsWith("wss://")) {
    return path
  }
  const prefix = path.startsWith("/") ? path : `/${path}`
  const base = jarvisApiBase(origin ?? (typeof window === "undefined" ? "" : window.location.origin))
  return base ? `${base}${prefix}` : prefix
}
