import type { ComponentType, MouseEventHandler } from "react"

export type ApexOrbState = "idle" | "listening" | "thinking" | "speaking"

declare const ApexOrb: ComponentType<{
  state?: ApexOrbState
  onRingClick?: MouseEventHandler<SVGCircleElement>
  variant?: "frame"
}>

export default ApexOrb
