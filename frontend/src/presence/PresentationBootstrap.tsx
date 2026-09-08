import { cloneElement, useEffect, useRef, useState, type ReactElement } from "react"
import { LEGACY_UI_MODE_CHANGED_EVENT, type UiMode } from "../hud/uiMode"
import {
  initializePresentation,
  PRESENTATION_CHANGED_EVENT,
  readPresentationBootstrap,
  updatePresentation,
} from "./presentationSettings"
import type { PresentationSettings, ShellMode } from "./presenceTypes"

type PresentationBootstrapProps = {
  children: ReactElement
}

export function PresentationBootstrap({ children }: PresentationBootstrapProps) {
  const shellRef = useRef<ShellMode>(readPresentationBootstrap().shell)
  const [shellRevision, setShellRevision] = useState(0)

  useEffect(() => {
    const onChanged = (event: Event) => {
      const detail = (event as CustomEvent<PresentationSettings>).detail
      if (!detail || detail.shell === shellRef.current) return
      shellRef.current = detail.shell
      setShellRevision((value) => value + 1)
    }
    const onLegacyModeChanged = (event: Event) => {
      const mode = (event as CustomEvent<UiMode>).detail
      if (mode !== "classic" && mode !== "hud") return
      updatePresentation({
        shell: mode,
        requestedPresence: mode === "classic" ? "none" : "neural",
      }).catch(() => undefined)
    }

    window.addEventListener(PRESENTATION_CHANGED_EVENT, onChanged)
    window.addEventListener(LEGACY_UI_MODE_CHANGED_EVENT, onLegacyModeChanged)
    initializePresentation().catch(() => undefined)
    return () => {
      window.removeEventListener(PRESENTATION_CHANGED_EVENT, onChanged)
      window.removeEventListener(LEGACY_UI_MODE_CHANGED_EVENT, onLegacyModeChanged)
    }
  }, [])

  return cloneElement(children, { key: shellRevision })
}
