/*
 * Derived from APEX-UI components/ApexOrb.jsx (MIT).
 * Copyright (c) 2026 Ruben Mouradian (Reznikov Engineering).
 * Adapted and rebranded for Jarvis. See frontend/third_party/APEX-UI/LICENSE.
 */

import "./apex-ui.css"

const GOLD = "#f5a623"
const GOLD_BRIGHT = "#ffd080"

export type JarvisOrbState = "idle" | "listening" | "thinking" | "speaking" | "alert"

type WaveformProps = { active: boolean; cx: number; cy: number; width?: number }

function Waveform({ active, cx, cy, width = 220 }: WaveformProps) {
  const barCount = 28
  const barW = 3
  const gap = (width - barCount * barW) / (barCount - 1)
  return (
    <g>
      {Array.from({ length: barCount }, (_, i) => {
        const x = cx - width / 2 + i * (barW + gap)
        const baseH = 3 + Math.abs(Math.sin(i * 0.6)) * 5
        const activeH = 8 + Math.abs(Math.sin(i * 0.8)) * 28
        return (
          <rect
            key={i}
            x={x}
            y={cy - (active ? activeH : baseH) / 2}
            width={barW}
            height={active ? activeH : baseH}
            rx={1.5}
            fill={GOLD}
            opacity={active ? 0.85 : 0.25}
            className={`jarvis-wavebar jarvis-wavebar-${i % 7}`}
          />
        )
      })}
    </g>
  )
}

type SoundWavesProps = { cx: number; cy: number; radius: number; active: boolean }

function SoundWaves({ cx, cy, radius, active }: SoundWavesProps) {
  return (
    <g>
      {[0, 1, 2, 3].map((i) => (
        <circle
          key={i}
          cx={cx}
          cy={cy}
          r={radius}
          stroke={GOLD}
          strokeWidth={active ? 1.5 : 0.8}
          fill="none"
          opacity={active ? 0.55 : 0.18}
          className={`jarvis-sound-wave jarvis-wave-${i}`}
          style={{ transformOrigin: `${cx}px ${cy}px` }}
        />
      ))}
    </g>
  )
}

type JarvisOrbProps = {
  state?: JarvisOrbState
  size?: number
  onClick?: () => void
  frameOnly?: boolean
}

export function JarvisOrb({ state = "idle", size = 520, onClick, frameOnly = false }: JarvisOrbProps) {
  const width = 900
  const height = 520
  const cx = width / 2
  const cy = frameOnly ? height / 2 : height / 2 - 20
  const radius = 155
  const outer = [178, 194, 212, 230, 250]
  const active = state !== "idle"
  const listening = state === "listening"
  const thinking = state === "thinking"
  const label = listening
    ? "LISTENING"
    : state === "speaking"
      ? "SPEAKING"
      : thinking
        ? "PROCESSING"
        : state === "alert"
          ? "ATTENTION"
          : "STANDBY"

  return (
    <button
      type="button"
      className="jarvis-apex-orb-button"
      data-state={state}
      onClick={onClick}
      aria-label={`Jarvis core: ${label.toLowerCase()}`}
      style={{ width: size, height: size * (height / width) }}
    >
      <div className="jarvis-apex-orb-wrap" data-state={state}>
        <svg width="100%" height="100%" viewBox={`0 0 ${width} ${height}`} fill="none" role="img" aria-hidden="true">
          <defs>
            <radialGradient id="jarvisRingFill" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor={GOLD} stopOpacity="0" />
              <stop offset="70%" stopColor={GOLD} stopOpacity="0.04" />
              <stop offset="88%" stopColor={GOLD} stopOpacity="0.18" />
              <stop offset="100%" stopColor={GOLD_BRIGHT} stopOpacity="0.5" />
            </radialGradient>
            <radialGradient id="jarvisAmbient" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor={GOLD} stopOpacity="0.08" />
              <stop offset="100%" stopColor={GOLD} stopOpacity="0" />
            </radialGradient>
            <filter id="jarvisRingBlur" x="-40%" y="-40%" width="180%" height="180%">
              <feGaussianBlur stdDeviation="7" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
            <filter id="jarvisTextBlur" x="-30%" y="-80%" width="160%" height="260%">
              <feGaussianBlur stdDeviation="5" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          <ellipse cx={cx} cy={cy} rx={radius + 130} ry={radius + 90} fill="url(#jarvisAmbient)" className="jarvis-orb-ambient" />

          {outer.map((r, i) => (
            <circle
              key={r}
              cx={cx}
              cy={cy}
              r={r}
              stroke={GOLD}
              strokeWidth={i === 0 ? 0.8 : 0.4}
              strokeOpacity={0.15 - i * 0.02}
              fill="none"
              strokeDasharray={i % 2 ? "3 7" : "none"}
            />
          ))}

          <line x1={cx} y1={cy - outer[4] - 10} x2={cx} y2={cy - outer[4] + 10} stroke={GOLD} strokeWidth="1" opacity="0.3" />
          <line x1={cx} y1={cy + outer[4] - 10} x2={cx} y2={cy + outer[4] + 10} stroke={GOLD} strokeWidth="1" opacity="0.3" />

          <SoundWaves cx={cx} cy={cy} radius={radius} active={active || listening} />

          {thinking && (
            <circle
              cx={cx}
              cy={cy}
              r={radius + 22}
              stroke={GOLD}
              strokeWidth="1"
              strokeOpacity="0.45"
              strokeDasharray="8 14"
              fill="none"
              className="jarvis-orbit-cw"
              style={{ transformOrigin: `${cx}px ${cy}px` }}
            />
          )}

          <circle cx={cx} cy={cy} r={radius} fill="url(#jarvisRingFill)" className="jarvis-ring-breathe" />
          <circle cx={cx} cy={cy} r={radius} stroke={GOLD} strokeWidth="18" strokeOpacity="0.08" fill="none" filter="url(#jarvisRingBlur)" className="jarvis-ring-glow" />
          <circle cx={cx} cy={cy} r={radius} stroke={GOLD} strokeWidth="6" strokeOpacity="0.4" fill="none" filter="url(#jarvisRingBlur)" />
          <circle cx={cx} cy={cy} r={radius} stroke={GOLD_BRIGHT} strokeWidth="2.5" strokeOpacity="0.95" fill="none" className="jarvis-ring-bright" />

          <circle cx={cx} cy={cy} r={radius * 0.58} stroke={GOLD} strokeWidth="1.5" strokeOpacity={active ? 0.45 : 0.15} fill="none" strokeDasharray="55 25" className="jarvis-orbit-cw" style={{ transformOrigin: `${cx}px ${cy}px` }} />
          <circle cx={cx} cy={cy} r={radius * 0.35} stroke={GOLD} strokeWidth="1" strokeOpacity={active ? 0.3 : 0.1} fill="none" strokeDasharray="28 18" className="jarvis-orbit-ccw" style={{ transformOrigin: `${cx}px ${cy}px` }} />

          {!frameOnly && (
            <g>
              <line x1={cx - radius - 90} y1={cy} x2={cx - radius + 15} y2={cy} stroke={GOLD} strokeWidth="1" opacity={active ? 0.55 : 0.15} strokeDasharray="4 3" />
              <line x1={cx + radius - 15} y1={cy} x2={cx + radius + 90} y2={cy} stroke={GOLD} strokeWidth="1" opacity={active ? 0.55 : 0.15} strokeDasharray="4 3" />
              <Waveform active={active} cx={cx} cy={cy} width={200} />
              <circle cx={cx} cy={cy} r={20} stroke={GOLD} strokeWidth="1.5" strokeOpacity="0.7" fill="#030200" filter="url(#jarvisRingBlur)" className="jarvis-center-ring" />
              <circle cx={cx} cy={cy} r={6} fill={GOLD_BRIGHT} opacity="0.95" className="jarvis-center" style={{ filter: `drop-shadow(0 0 10px ${GOLD})` }} />
              <text x={cx} y={cy + radius * 0.52} textAnchor="middle" fill={GOLD} fontSize="12" fontFamily="Inter, monospace" fontWeight="400" letterSpacing="0.28em" opacity="0.55" filter="url(#jarvisTextBlur)">{label}</text>
              {[0, 1, 2].map((i) => (
                <circle key={i} cx={cx + (i - 1) * 12} cy={cy + radius * 0.52 + 18} r={2.5} fill={GOLD} className={`jarvis-dot-blink jarvis-blink-${i}`} />
              ))}
            </g>
          )}
        </svg>
      </div>
    </button>
  )
}
