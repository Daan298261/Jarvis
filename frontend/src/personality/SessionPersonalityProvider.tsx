import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react"
import {
  applySessionPersonalityDom,
  fetchSessionPersonality,
  readSessionPersonalityBootstrap,
  selectSessionPersonality,
  type SessionPersonalityId,
  type SessionPersonalityState,
} from "./sessionPersonality"

type SessionPersonalityContextValue = {
  state: SessionPersonalityState | null
  busy: boolean
  refresh: () => Promise<void>
  select: (id: SessionPersonalityId) => Promise<void>
}

const SessionPersonalityContext = createContext<SessionPersonalityContextValue | null>(null)

export function SessionPersonalityProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionPersonalityState | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const boot = readSessionPersonalityBootstrap()
    applySessionPersonalityDom(boot, boot)
    void fetchSessionPersonality()
      .then(setState)
      .catch(() => undefined)
  }, [])

  const refresh = useCallback(async () => {
    const next = await fetchSessionPersonality()
    setState(next)
  }, [])

  const select = useCallback(async (id: SessionPersonalityId) => {
    setBusy(true)
    try {
      const next = await selectSessionPersonality(id)
      setState(next)
    } finally {
      setBusy(false)
    }
  }, [])

  const value = useMemo(
    () => ({ state, busy, refresh, select }),
    [state, busy, refresh, select],
  )

  return <SessionPersonalityContext.Provider value={value}>{children}</SessionPersonalityContext.Provider>
}

export function useSessionPersonality(): SessionPersonalityContextValue {
  const ctx = useContext(SessionPersonalityContext)
  if (!ctx) {
    throw new Error("useSessionPersonality must be used within SessionPersonalityProvider")
  }
  return ctx
}

export function useSessionPersonalityOptional(): SessionPersonalityContextValue | null {
  return useContext(SessionPersonalityContext)
}
