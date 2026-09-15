import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react"

type HudOverlayContextValue = {
  hexSuiteExpanded: boolean
  setHexSuiteExpanded: (expanded: boolean) => void
  /** Close other HUD chrome and show the Daybreak / HexStrike panel. */
  focusHexSuite: () => void
  /** Call when Admin, Help, Activity, System, or model menu opens. */
  dismissHexSuiteForOverlay: () => void
}

const HudOverlayContext = createContext<HudOverlayContextValue | null>(null)

export function HudOverlayProvider({ children }: { children: ReactNode }) {
  const [hexSuiteExpanded, setHexSuiteExpanded] = useState(true)

  const dismissHexSuiteForOverlay = useCallback(() => {
    setHexSuiteExpanded(false)
  }, [])

  const focusHexSuite = useCallback(() => {
    setHexSuiteExpanded(true)
  }, [])

  const value = useMemo(
    () => ({
      hexSuiteExpanded,
      setHexSuiteExpanded,
      focusHexSuite,
      dismissHexSuiteForOverlay,
    }),
    [hexSuiteExpanded, dismissHexSuiteForOverlay, focusHexSuite],
  )

  return <HudOverlayContext.Provider value={value}>{children}</HudOverlayContext.Provider>
}

export function useHudOverlay(): HudOverlayContextValue {
  const ctx = useContext(HudOverlayContext)
  if (!ctx) {
    throw new Error("useHudOverlay must be used within HudOverlayProvider")
  }
  return ctx
}
