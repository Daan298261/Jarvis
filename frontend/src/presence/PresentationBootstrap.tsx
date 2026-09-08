import { cloneElement, useEffect, useRef, useState, type ReactElement } from "react"
import {
  initializePresentation,
  PRESENTATION_CHANGED_EVENT,
  readPresentationBootstrap,
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

    window.addEventListener(PRESENTATION_CHANGED_EVENT, onChanged)
    initializePresentation().catch(() => undefined)
    return () => window.removeEventListener(PRESENTATION_CHANGED_EVENT, onChanged)
  }, [])

  return cloneElement(children, { key: shellRevision })
}
