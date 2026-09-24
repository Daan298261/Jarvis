import { useEffect, useRef } from "react"
import { hudStarfieldCount } from "../presence/galaxyPresence"

export type StarfieldMode = "cluster" | "sky"

type Particle = {
  x: number
  y: number
  vx: number
  vy: number
  homeX: number
  homeY: number
  clusterX: number
  clusterY: number
  skyX: number
  skyY: number
  size: number
  glow: number
  twinkle: number
  twinkleSpeed: number
  hue: number
}

type HudStarfieldProps = {
  mode: StarfieldMode
  pulseKey: string
  galaxy?: boolean
}

function hashSeed(i: number): number {
  const x = Math.sin(i * 12.9898 + 78.233) * 43758.5453
  return x - Math.floor(x)
}

function makeParticles(width: number, height: number, count: number): Particle[] {
  const cx = width * 0.5
  const cy = height * 0.42
  const particles: Particle[] = []
  for (let i = 0; i < count; i++) {
    const seed = hashSeed(i + 1)
    const seed2 = hashSeed(i + 97)
    const seed3 = hashSeed(i + 211)
    const angle = seed * Math.PI * 2
    const radius = (0.04 + seed2 * 0.22) * Math.min(width, height)
    const clusterX = cx + Math.cos(angle) * radius * (0.35 + seed3)
    const clusterY = cy + Math.sin(angle) * radius * 0.72
    const skyX = seed * width
    const skyY = seed2 * height
    const startX = clusterX
    const startY = clusterY
    particles.push({
      x: startX,
      y: startY,
      vx: 0,
      vy: 0,
      homeX: clusterX,
      homeY: clusterY,
      clusterX,
      clusterY,
      skyX,
      skyY,
      size: 0.6 + seed3 * 2.4,
      glow: 0.35 + seed * 0.65,
      twinkle: seed2 * Math.PI * 2,
      twinkleSpeed: 0.4 + seed3 * 1.4,
      hue: 186 + seed * 28,
    })
  }
  return particles
}

export function HudStarfield({ mode, pulseKey, galaxy = false }: HudStarfieldProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const modeRef = useRef(mode)
  const galaxyRef = useRef(galaxy)
  const burstRef = useRef(0)
  const mouseRef = useRef({ x: 0.5, y: 0.45, active: false })
  const resizeRef = useRef<() => void>(() => undefined)

  useEffect(() => {
    modeRef.current = mode
  }, [mode])

  useEffect(() => {
    galaxyRef.current = galaxy
    resizeRef.current()
  }, [galaxy])

  useEffect(() => {
    burstRef.current = 1
  }, [pulseKey])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext("2d", { alpha: true })
    if (!ctx) return

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    const parent = canvas.parentElement
    let width = 1
    let height = 1
    let particles: Particle[] = []
    let frame = 0
    let disposed = false
    let last = performance.now()

    const resize = () => {
      const rect = (parent ?? canvas).getBoundingClientRect()
      width = Math.max(1, rect.width)
      height = Math.max(1, rect.height)
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5)
      canvas.width = Math.floor(width * dpr)
      canvas.height = Math.floor(height * dpr)
      canvas.style.width = `${width}px`
      canvas.style.height = `${height}px`
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      const count = hudStarfieldCount(width, height, reduced, galaxyRef.current)
      particles = makeParticles(width, height, count)
      resizeRef.current = resize
    }

    const onMove = (event: PointerEvent) => {
      mouseRef.current = {
        x: event.clientX / Math.max(1, window.innerWidth),
        y: event.clientY / Math.max(1, window.innerHeight),
        active: true,
      }
    }
    const onLeave = () => {
      mouseRef.current = { ...mouseRef.current, active: false }
    }

    const tick = (now: number) => {
      if (disposed) return
      const dt = Math.min(0.048, (now - last) / 1000)
      last = now
      burstRef.current = Math.max(0, burstRef.current - dt * 0.85)
      const sky = modeRef.current === "sky"
      const mouse = mouseRef.current
      const mx = mouse.x * width
      const my = mouse.y * height
      const attract = (mouse.active ? 1 : 0.35) * (sky ? 0.55 : 0.28)

      const galaxyOn = galaxyRef.current
      ctx.globalCompositeOperation = "source-over"
      if (galaxyOn) {
        ctx.fillStyle = "#010308"
        ctx.fillRect(0, 0, width, height)
      } else {
        ctx.clearRect(0, 0, width, height)
      }
      ctx.globalCompositeOperation = "lighter"

      for (const p of particles) {
        p.homeX = galaxyOn || sky ? p.skyX : p.clusterX
        p.homeY = galaxyOn || sky ? p.skyY : p.clusterY
        if (burstRef.current > 0.02) {
          const awayX = p.x - width * 0.5
          const awayY = p.y - height * 0.42
          const dist = Math.hypot(awayX, awayY) || 1
          const force = burstRef.current * 420
          p.vx += (awayX / dist) * force * dt
          p.vy += (awayY / dist) * force * dt
        }
        const toHomeX = p.homeX - p.x
        const toHomeY = p.homeY - p.y
        const settle = sky ? 1.15 : 2.4
        p.vx += toHomeX * settle * dt
        p.vy += toHomeY * settle * dt
        p.vx += (mx - p.x) * attract * dt
        p.vy += (my - p.y) * attract * dt
        p.vx *= sky ? 0.92 : 0.86
        p.vy *= sky ? 0.92 : 0.86
        if (!reduced) {
          p.x += p.vx * dt * 18
          p.y += p.vy * dt * 18
          p.twinkle += dt * p.twinkleSpeed
          if (galaxyOn) {
            if (p.x < -24) p.x += width + 48
            if (p.x > width + 24) p.x -= width + 48
            if (p.y < -24) p.y += height + 48
            if (p.y > height + 24) p.y -= height + 48
          }
        } else {
          p.x = p.homeX
          p.y = p.homeY
        }
        const tw = 0.55 + 0.45 * Math.sin(p.twinkle)
        const alpha = (galaxyOn ? 0.72 : sky ? 0.55 : 0.28) * p.glow * tw
        const radius = p.size * (galaxyOn ? 0.42 : sky ? 1.35 : 1.9)
        ctx.fillStyle = `hsla(${p.hue}, 92%, 70%, ${alpha * (galaxyOn ? 0.08 : 0.16)})`
        ctx.beginPath()
        ctx.arc(p.x, p.y, radius * (galaxyOn ? 2.1 : 5.2), 0, Math.PI * 2)
        ctx.fill()
        ctx.fillStyle = `hsla(${p.hue}, 100%, 82%, ${alpha})`
        ctx.beginPath()
        ctx.arc(p.x, p.y, radius, 0, Math.PI * 2)
        ctx.fill()
        ctx.fillStyle = `hsla(${p.hue}, 100%, 96%, ${alpha * 0.85})`
        ctx.beginPath()
        ctx.arc(p.x, p.y, Math.max(0.45, radius * 0.28), 0, Math.PI * 2)
        ctx.fill()
      }

      ctx.globalCompositeOperation = "source-over"
      frame = requestAnimationFrame(tick)
    }

    resize()
    window.addEventListener("pointermove", onMove, { passive: true })
    window.addEventListener("pointerleave", onLeave)
    window.addEventListener("resize", resize)
    frame = requestAnimationFrame(tick)
    return () => {
      disposed = true
      cancelAnimationFrame(frame)
      window.removeEventListener("pointermove", onMove)
      window.removeEventListener("pointerleave", onLeave)
      window.removeEventListener("resize", resize)
    }
  }, [])

  return <canvas ref={canvasRef} className="hud-starfield" aria-hidden />
}
