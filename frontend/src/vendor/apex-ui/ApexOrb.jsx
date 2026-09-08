"use client";

const GOLD = '#f5a623'
const GOLD_BRIGHT = '#ffd080'

function Waveform({ active, cx, cy, width = 220 }) {
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
          <rect key={i} x={x} y={cy - (active ? activeH : baseH) / 2}
            width={barW} height={active ? activeH : baseH}
            rx={1.5} fill={GOLD}
            opacity={active ? 0.85 : 0.25}
            className={`wavebar wavebar-${i % 7}`}
          />
        )
      })}
    </g>
  )
}

function OrbitDot({ cx, cy, r, angleDeg, size = 4 }) {
  const rad = (angleDeg * Math.PI) / 180
  const x = cx + r * Math.cos(rad)
  const y = cy + r * Math.sin(rad)
  return (
    <circle cx={x} cy={y} r={size} fill={GOLD}
      style={{ filter: `drop-shadow(0 0 ${size * 2}px ${GOLD})` }}
    />
  )
}

// Always-on sound wave rings — subtle idle, bright active
function SoundWaves({ cx, cy, R, active }) {
  const waves = [0, 1, 2, 3]
  return (
    <g>
      {waves.map(i => (
        <circle key={i} cx={cx} cy={cy} r={R}
          stroke={GOLD} strokeWidth={active ? 1.5 : 0.8} fill="none"
          opacity={active ? 0.55 : 0.18}
          className={`sound-wave wave-${i}`}
          style={{ transformOrigin: `${cx}px ${cy}px` }}
        />
      ))}
    </g>
  )
}

export default function ApexOrb({ state = 'idle', onRingClick, variant }) {
  const frameOnly = variant === 'frame'
  const W = 900, H = 520
  const cx = W / 2, cy = frameOnly ? H / 2 : H / 2 - 20
  const R = 155
  const OUTER = [178, 194, 212, 230, 250]

  const isActive    = state !== 'idle'
  const isListening = state === 'listening'
  const isSpeaking  = state === 'speaking'
  const isThinking  = state === 'thinking'
  const label = isListening ? 'LISTENING' : isSpeaking ? 'SPEAKING' : isThinking ? 'PROCESSING' : 'STANDBY'

  return (
    <div className="apex-orb-wrap" data-state={state} style={{ width: W, height: H }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} fill="none">
        <defs>
          <radialGradient id="ringFill" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor={GOLD} stopOpacity="0"/>
            <stop offset="70%" stopColor={GOLD} stopOpacity="0.04"/>
            <stop offset="88%" stopColor={GOLD} stopOpacity="0.18"/>
            <stop offset="100%" stopColor={GOLD_BRIGHT} stopOpacity="0.5"/>
          </radialGradient>
          <radialGradient id="ambBg" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor={GOLD} stopOpacity="0.08"/>
            <stop offset="100%" stopColor={GOLD} stopOpacity="0"/>
          </radialGradient>
          <filter id="ringBlur" x="-40%" y="-40%" width="180%" height="180%">
            <feGaussianBlur stdDeviation="7" result="b"/>
            <feMerge><feMergeNode in="b"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
          <filter id="dotF" x="-300%" y="-300%" width="700%" height="700%">
            <feGaussianBlur stdDeviation="4"/>
          </filter>
          <filter id="txtF" x="-30%" y="-80%" width="160%" height="260%">
            <feGaussianBlur stdDeviation="5" result="b"/>
            <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
          <filter id="gndF" x="-100%" y="-400%" width="300%" height="800%">
            <feGaussianBlur stdDeviation="20"/>
          </filter>
        </defs>

        <ellipse cx={cx} cy={cy} rx={R+130} ry={R+90}
          fill="url(#ambBg)" className="orb-ambient"/>

        {OUTER.map((r, i) => (
          <circle key={r} cx={cx} cy={cy} r={r}
            stroke={GOLD} strokeWidth={i === 0 ? 0.8 : 0.4}
            strokeOpacity={0.15 - i * 0.02} fill="none"
            strokeDasharray={i % 2 ? '3 7' : 'none'}
          />
        ))}

        <line x1={cx} y1={cy-OUTER[4]-10} x2={cx} y2={cy-OUTER[4]+10}
          stroke={GOLD} strokeWidth="1" opacity="0.3"/>
        <line x1={cx} y1={cy+OUTER[4]-10} x2={cx} y2={cy+OUTER[4]+10}
          stroke={GOLD} strokeWidth="1" opacity="0.3"/>

        <SoundWaves cx={cx} cy={cy} R={R} active={isActive || isListening}/>

        {isThinking && (
          <circle cx={cx} cy={cy} r={R+22} stroke={GOLD} strokeWidth="1"
            strokeOpacity="0.45" strokeDasharray="8 14" fill="none"
            className="orb-orbit-cw" style={{transformOrigin:`${cx}px ${cy}px`}}/>
        )}

        <circle cx={cx} cy={cy} r={R} fill="url(#ringFill)" className="orb-ring-breathe"/>
        <circle cx={cx} cy={cy} r={R} stroke={GOLD} strokeWidth="18"
          strokeOpacity="0.08" fill="none" filter="url(#ringBlur)" className="orb-ring-glow"/>
        <circle cx={cx} cy={cy} r={R} stroke={GOLD} strokeWidth="6"
          strokeOpacity="0.4" fill="none" filter="url(#ringBlur)"/>
        <circle cx={cx} cy={cy} r={R} stroke={GOLD_BRIGHT} strokeWidth="2.5"
          strokeOpacity="0.95" fill="none" className="orb-ring-bright"/>

        <circle cx={cx} cy={cy} r={R*0.58} stroke={GOLD} strokeWidth="1.5"
          strokeOpacity={isActive ? 0.45 : 0.15} fill="none" strokeDasharray="55 25"
          className="orb-orbit-cw" style={{transformOrigin:`${cx}px ${cy}px`}}/>
        <circle cx={cx} cy={cy} r={R*0.35} stroke={GOLD} strokeWidth="1"
          strokeOpacity={isActive ? 0.3 : 0.1} fill="none" strokeDasharray="28 18"
          className="orb-orbit-ccw" style={{transformOrigin:`${cx}px ${cy}px`}}/>

        {!frameOnly && (
          <g>
            <line x1={cx-R-90} y1={cy} x2={cx-R+15} y2={cy}
              stroke={GOLD} strokeWidth="1" opacity={isActive?0.55:0.15} strokeDasharray="4 3"/>
            <line x1={cx+R-15} y1={cy} x2={cx+R+90} y2={cy}
              stroke={GOLD} strokeWidth="1" opacity={isActive?0.55:0.15} strokeDasharray="4 3"/>

            <Waveform active={isActive} cx={cx} cy={cy} width={200}/>

            <circle cx={cx} cy={cy} r={20} stroke={GOLD} strokeWidth="1.5"
              strokeOpacity="0.7" fill="#030200" filter="url(#ringBlur)"
              className="orb-center-ring"/>
            <circle cx={cx} cy={cy} r={6} fill={GOLD_BRIGHT} opacity="0.95"
              className="orb-center" style={{filter:`drop-shadow(0 0 10px ${GOLD})`}}/>

            <text x={cx} y={cy + R*0.52} textAnchor="middle"
              fill={GOLD} fontSize="12" fontFamily="'Inter',monospace"
              fontWeight="400" letterSpacing="0.28em" opacity="0.55"
              filter="url(#txtF)">
              {label}
            </text>

            {[0,1,2].map(i => (
              <circle key={i} cx={cx+(i-1)*12} cy={cy+R*0.52+18}
                r={2.5} fill={GOLD}
                className={`orb-dot-blink blink-${i}`}/>
            ))}
          </g>
        )}

        {onRingClick && (
          <circle
            cx={cx} cy={cy} r={R + 20}
            fill="transparent"
            style={{ cursor: 'pointer', pointerEvents: 'all' }}
            onClick={onRingClick}
          />
        )}

        {!frameOnly && (
          <g>
            <ellipse cx={cx} cy={H-8} rx={70} ry={10}
              fill={GOLD} opacity={isActive?0.3:0.12}
              filter="url(#gndF)" className="orb-ambient"/>
            <line x1={cx} y1={cy+R+6} x2={cx} y2={H-10}
              stroke={GOLD} strokeWidth="1"
              opacity={isActive?0.28:0.1} strokeDasharray="3 5"/>
            {[35,60,85].map((rx,i) => (
              <ellipse key={i} cx={cx} cy={H-14} rx={rx} ry={rx*0.16}
                stroke={GOLD} strokeWidth="0.5"
                strokeOpacity={0.12-i*0.03} fill="none"/>
            ))}
          </g>
        )}
      </svg>
    </div>
  )
}
