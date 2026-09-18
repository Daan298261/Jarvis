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
  /** Expand or collapse the Daybreak / HexStrike operator panel. */
  toggleHexSuite: () => void
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

  const toggleHexSuite = useCallback(() => {
    setHexSuiteExpanded((expanded) => !expanded)
  }, [])

  const value = useMemo(
    () => ({
      hexSuiteExpanded,
      setHexSuiteExpanded,
      focusHexSuite,
      toggleHexSuite,
      dismissHexSuiteForOverlay,
    }),
    [hexSuiteExpanded, dismissHexSuiteForOverlay, focusHexSuite, toggleHexSuite],
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

export function useHudOverlayOptional(): HudOverlayContextValue | null {
  return useContext(HudOverlayContext)
}
