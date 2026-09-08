import type { ComponentType } from "react"

export type ApexRosterEntry = [
  key: string,
  label: string,
  layer: "consultant" | "doer" | "tool",
  x: number,
  y: number,
  live: boolean,
  bend: number,
  radius: number,
]

export type ApexSelection = { name: string; key: string; color: string }

declare const ReasoningWeb: ComponentType<{
  state?: "standby" | "listening" | "processing" | "reasoning" | "speaking"
  trace?: unknown
  mode?: "full" | "mini"
  coreless?: boolean
  onSelect?: ((selection: ApexSelection) => void) | null
  light?: boolean
  roster?: ApexRosterEntry[] | null
  anchor?: [number, number] | null
  viewBox?: string | null
  traces?: boolean
}>

export default ReasoningWeb
