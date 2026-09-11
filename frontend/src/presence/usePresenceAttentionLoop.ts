import { useEffect, useRef, type RefObject } from "react"
import type { PresentationSettings } from "./presenceTypes"
import {
  attentionCssTransform,
  createPresenceAttentionController,
} from "./presenceAttention"

type LoopOptions = {
  settings: PresentationSettings
  rootRef?: RefObject<HTMLElement | null>
  cssTargetRef?: RefObject<HTMLElement | null>
  cssScale?: number
}

function isReducedMotion(settings: PresentationSettings): boolean {
  if (settings.reducedMotion === "reduce") return true
  if (settings.reducedMotion === "full") return false
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches
}

export function usePresenceAttentionLoop({
  settings,
  rootRef,
  cssTargetRef,
  cssScale = 1,
}: LoopOptions): void {
  const settingsRef = useRef(settings)
  settingsRef.current = settings

  useEffect(() => {
    const controller = createPresenceAttentionController({
      getMode: () => settingsRef.current.attentionMode,
      getReducedMotion: () => isReducedMotion(settingsRef.current),
      anchor: () => rootRef?.current ?? null,
    })

    let frame = 0
    const tick = () => {
      frame = window.requestAnimationFrame(tick)
      const sample = controller.sample()
      const el = cssTargetRef?.current
      if (!el) return
      if (settingsRef.current.attentionMode === "off" || isReducedMotion(settingsRef.current)) {
        el.style.transform = "translate(-50%, -50%)"
        return
      }
      el.style.transform = attentionCssTransform(sample.x, sample.y, cssScale)
    }
    frame = window.requestAnimationFrame(tick)

    return () => {
      window.cancelAnimationFrame(frame)
      controller.dispose()
      const el = cssTargetRef?.current
      if (el) el.style.transform = "translate(-50%, -50%)"
    }
  }, [rootRef, cssTargetRef, cssScale])
}
