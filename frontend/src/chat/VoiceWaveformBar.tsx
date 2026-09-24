import { useEffect, useRef } from "react"
import { useNamedPersonas } from "../persona/namedPersonas"
import { readVoiceMeter, type VoiceMeterKind } from "../tts/voiceAnalyser"
import { voiceWaveformVisible } from "./voiceWaveformVisibility"
import "./voice-waveform.css"

type VoiceWaveformBarProps = {
  speaking: boolean
  listening: boolean
}

function drawSteady(ctx: CanvasRenderingContext2D, width: number, height: number, edge: string) {
  ctx.clearRect(0, 0, width, height)
  const y = height * 0.62
  const gradient = ctx.createLinearGradient(0, 0, width, 0)
  gradient.addColorStop(0, "rgba(90, 190, 220, 0.15)")
  gradient.addColorStop(0.5, "rgba(126, 214, 255, 0.85)")
  gradient.addColorStop(1, edge)
  ctx.strokeStyle = gradient
  ctx.lineWidth = 2
  ctx.beginPath()
  ctx.moveTo(8, y)
  ctx.lineTo(width - 8, y)
  ctx.stroke()
}

function drawSpectrum(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  bins: Uint8Array,
  edge: string,
) {
  ctx.clearRect(0, 0, width, height)
  const gradient = ctx.createLinearGradient(0, height, 0, 0)
  gradient.addColorStop(0, "rgba(90, 186, 214, 0.15)")
  gradient.addColorStop(0.55, "rgba(120, 214, 255, 0.72)")
  gradient.addColorStop(1, edge)
  ctx.fillStyle = gradient
  ctx.beginPath()
  const mid = height * 0.72
  ctx.moveTo(6, mid)
  const usable = Math.max(8, Math.floor(bins.length * 0.7))
  for (let i = 0; i < usable; i++) {
    const t = i / (usable - 1)
    const x = 6 + t * (width - 12)
    const amp = bins[i] / 255
    const y = mid - amp * (height * 0.58)
    if (i === 0) ctx.lineTo(x, y)
    else ctx.lineTo(x, y)
  }
  ctx.lineTo(width - 6, mid)
  ctx.closePath()
  ctx.fill()
}

function Ribbon({
  speaking,
  accent,
}: {
  speaking: boolean
  accent: string
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const expected: VoiceMeterKind = speaking ? "tts" : "mic"

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext("2d")
    if (!ctx) return
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    let frame = 0
    let disposed = false

    const paint = () => {
      if (disposed) return
      const rect = canvas.getBoundingClientRect()
      const width = Math.max(1, rect.width)
      const height = Math.max(1, rect.height)
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      if (canvas.width !== Math.floor(width * dpr) || canvas.height !== Math.floor(height * dpr)) {
        canvas.width = Math.floor(width * dpr)
        canvas.height = Math.floor(height * dpr)
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      const meter = readVoiceMeter()
      const live = meter.attached && meter.kind === expected && meter.bins
      if (!live || reduced || !meter.bins) drawSteady(ctx, width, height, accent)
      else drawSpectrum(ctx, width, height, meter.bins, accent)
      frame = window.requestAnimationFrame(paint)
    }
    frame = window.requestAnimationFrame(paint)
    return () => {
      disposed = true
      window.cancelAnimationFrame(frame)
    }
  }, [accent, expected])

  return (
    <canvas
      ref={canvasRef}
      className="voice-waveform-canvas"
      aria-hidden="true"
    />
  )
}

export function VoiceWaveformBar({ speaking, listening }: VoiceWaveformBarProps) {
  const personas = useNamedPersonas()
  if (!voiceWaveformVisible({ speaking, listening })) return null
  const accent = personas?.active?.appearance?.accent_color || "rgba(255, 168, 92, 0.9)"
  return (
    <div
      className="voice-waveform-bar"
      role="img"
      aria-label={speaking ? "Jarvis is speaking" : "Listening"}
    >
      <Ribbon speaking={speaking} accent={accent} />
    </div>
  )
}
