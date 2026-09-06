/**
 * Adapted from MARCCHERGGI/jarvis-home (MIT)
 * https://github.com/MARCCHERGGI/jarvis-home — ParticleOrb component
 *
 * JARVIS Spirit — Consciousness Resonance Field (shader orb).
 * Mood-driven animation replaces upstream ampBus / voice coupling.
 */

import { useEffect, useRef, useState } from "react"
import * as THREE from "three"
import type { OrbMood } from "./orbMood"

const SNOISE = /* glsl */ `
vec3 mod289(vec3 x){return x-floor(x*(1./289.))*289.;}
vec4 mod289(vec4 x){return x-floor(x*(1./289.))*289.;}
vec4 permute(vec4 x){return mod289(((x*34.)+1.)*x);}
vec4 taylorInvSqrt(vec4 r){return 1.79284291400159-.85373472095314*r;}
float snoise(vec3 v){
  const vec2 C=vec2(1./6.,1./3.);const vec4 D=vec4(0,.5,1,2);
  vec3 i=floor(v+dot(v,C.yyy)),x0=v-i+dot(i,C.xxx);
  vec3 g=step(x0.yzx,x0.xyz),l=1.-g,i1=min(g,l.zxy),i2=max(g,l.zxy);
  vec3 x1=x0-i1+C.xxx,x2=x0-i2+C.yyy,x3=x0-D.yyy;
  i=mod289(i);
  vec4 p=permute(permute(permute(i.z+vec4(0,i1.z,i2.z,1))+i.y+vec4(0,i1.y,i2.y,1))+i.x+vec4(0,i1.x,i2.x,1));
  float n_=.142857142857;vec3 ns=n_*D.wyz-D.xzx;
  vec4 j=p-49.*floor(p*ns.z*ns.z),x_=floor(j*ns.z),y_=floor(j-7.*x_);
  vec4 x=x_*ns.x+ns.yyyy,y=y_*ns.x+ns.yyyy,h=1.-abs(x)-abs(y);
  vec4 b0=vec4(x.xy,y.xy),b1=vec4(x.zw,y.zw),s0=floor(b0)*2.+1.,s1=floor(b1)*2.+1.;
  vec4 sh=-step(h,vec4(0)),a0=b0.xzyw+s0.xzyw*sh.xxyy,a1=b1.xzyw+s1.xzyw*sh.zzww;
  vec3 p0=vec3(a0.xy,h.x),p1=vec3(a0.zw,h.y),p2=vec3(a1.xy,h.z),p3=vec3(a1.zw,h.w);
  vec4 norm=taylorInvSqrt(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));
  p0*=norm.x;p1*=norm.y;p2*=norm.z;p3*=norm.w;
  vec4 m=max(.6-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.);
  m=m*m;return 42.*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));
}
`

function detectGpuTier(): "low" | "high" {
  try {
    const canvas = document.createElement("canvas")
    const gl = canvas.getContext("webgl")
    if (!gl) return "low"
    const debugInfo = gl.getExtension("WEBGL_debug_renderer_info")
    if (debugInfo) {
      const renderer = gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL) as string
      if (/swiftshader|llvmpipe|software|mesa/i.test(renderer)) return "low"
    }
    return "high"
  } catch {
    return "low"
  }
}

function moodTargets(mood: OrbMood, t: number): { amp: number; low: number; mid: number; high: number } {
  switch (mood) {
    case "listening":
      return {
        amp: 0.28 + Math.sin(t * 3.1) * 0.12,
        low: 0.22,
        mid: 0.18,
        high: 0.12,
      }
    case "thinking":
      return {
        amp: 0.2 + Math.sin(t * 2.4) * 0.09,
        low: 0.14,
        mid: 0.22,
        high: 0.06,
      }
    case "speaking":
      return {
        amp: 0.58 + Math.sin(t * 5.2) * 0.22,
        low: 0.42,
        mid: 0.5,
        high: 0.32,
      }
    case "alert":
      return {
        amp: 0.38 + Math.sin(t * 4.5) * 0.16,
        low: 0.24,
        mid: 0.28,
        high: 0.14,
      }
    default:
      return {
        amp: 0.09 + Math.sin(t * 0.9) * 0.04,
        low: 0.06,
        mid: 0.04,
        high: 0.03,
      }
  }
}

type ParticleOrbProps = {
  mood?: OrbMood
  size?: number
}

export function ParticleOrb({ mood = "idle", size = 420 }: ParticleOrbProps) {
  const mountRef = useRef<HTMLDivElement>(null)
  const moodRef = useRef(mood)
  const [reducedMotion, setReducedMotion] = useState(false)
  const [gpuTier] = useState(detectGpuTier)

  useEffect(() => {
    moodRef.current = mood
  }, [mood])

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)")
    const update = () => setReducedMotion(mq.matches)
    update()
    mq.addEventListener("change", update)
    return () => mq.removeEventListener("change", update)
  }, [])

  useEffect(() => {
    if (reducedMotion) return
    const mount = mountRef.current
    if (!mount) return

    const displaySize = gpuTier === "low" ? Math.round(size * 0.72) : size
    const internalSize = Math.round(displaySize * 0.48)
    const renderer = new THREE.WebGLRenderer({
      antialias: false,
      alpha: true,
      powerPreference: gpuTier === "low" ? "low-power" : "high-performance",
    })
    renderer.setPixelRatio(1)
    renderer.setSize(internalSize, internalSize)
    renderer.setClearColor(0x000000, 0)
    renderer.outputColorSpace = THREE.SRGBColorSpace
    mount.appendChild(renderer.domElement)
    renderer.domElement.style.width = `${displaySize}px`
    renderer.domElement.style.height = `${displaySize}px`

    const scene = new THREE.Scene()
    const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1)

    const mat = new THREE.ShaderMaterial({
      uniforms: {
        uNoiseTime: { value: 0 },
        uAmp: { value: 0 },
        uAmpFast: { value: 0 },
        uBandLow: { value: 0 },
        uBandMid: { value: 0 },
        uBandHigh: { value: 0 },
        uWaveSeed: { value: 0 },
        uMomentum: { value: 0 },
        uMorph: { value: 0 },
      },
      vertexShader: /* glsl */ `
        varying vec2 vUv;
        void main() {
          vUv = uv * 2.0 - 1.0;
          gl_Position = vec4(position.xy, 0.0, 1.0);
        }
      `,
      fragmentShader:
        SNOISE +
        /* glsl */ `
        precision mediump float;
        varying vec2 vUv;
        uniform float uNoiseTime;
        uniform float uAmp;
        uniform float uAmpFast;
        uniform float uBandLow;
        uniform float uBandMid;
        uniform float uBandHigh;
        uniform float uWaveSeed;
        uniform float uMomentum;
        uniform float uMorph;

        mat2 rot2(float a) { float c = cos(a), s = sin(a); return mat2(c, -s, s, c); }

        vec3 hashAxis(float s) {
          float a = fract(sin(s * 12.9898) * 43758.5453);
          float b = fract(sin(s * 78.233)  * 43758.5453);
          float th = a * 6.2831853;
          float ph = acos(2.0 * b - 1.0);
          return vec3(sin(ph) * cos(th), cos(ph), sin(ph) * sin(th));
        }

        void main() {
          vec2 p = vUv;
          float r = length(p);
          if (r > 1.02) discard;

          float z2 = max(0.0, 1.0 - r * r);
          float z  = sqrt(z2);
          vec3 N   = vec3(p.x, p.y, z);

          float wob = uAmp * 0.18;
          float ry = uNoiseTime * 0.60 + sin(uNoiseTime * 3.3) * wob + uMomentum * 0.12;
          float rx = uNoiseTime * 0.26 + cos(uNoiseTime * 4.1) * wob * 0.7 + uMomentum * 0.05;
          vec3 rN = N;
          rN.xz = rot2(ry) * rN.xz;
          rN.yz = rot2(rx) * rN.yz;

          float lon = atan(rN.x, rN.z);
          float lat = asin(clamp(rN.y, -1.0, 1.0));

          vec3 deepCoord = rN * 1.8;
          float deep1 = snoise(deepCoord + vec3(uNoiseTime * 0.35, 0.0, 0.0));
          float deep2 = snoise(deepCoord * 2.1 + vec3(0.0, uNoiseTime * 0.42, 0.0)) * 0.5;
          float deepPlasma = clamp((deep1 + deep2) * 0.6 + 0.5, 0.0, 1.0);
          deepPlasma *= 0.7 + uBandLow * 0.9;

          vec3 surfCoord = rN * 3.6;
          float surf = snoise(surfCoord + vec3(uNoiseTime * 1.15, 0.0, 0.0));
          float surfPlasma = smoothstep(-0.2, 0.7, surf) * uAmp;

          float meridMajor = pow(abs(sin(lon * 6.0)), 56.0);
          float meridMinor = pow(abs(sin(lon * 18.0)), 80.0) * 0.35;
          float latMajor   = pow(abs(sin(lat * 5.0)), 44.0);
          float latMinor   = pow(abs(sin(lat * 14.0)), 80.0) * 0.28;
          float grid = max(meridMajor, max(meridMinor, max(latMajor * 0.85, latMinor)));
          grid *= pow(z, 0.4);

          float equatorThickness = 0.012 + uBandMid * 0.035;
          float equator = 1.0 - smoothstep(0.0, equatorThickness, abs(lat));
          equator *= pow(z, 0.35);

          float polarMask = smoothstep(0.78, 0.92, abs(rN.y));
          float polarRings = pow(abs(sin(abs(rN.y) * 38.0)), 60.0) * polarMask;

          float fresnel = pow(1.0 - z, 2.4);
          float shell = smoothstep(0.965, 0.995, r) * (1.0 - smoothstep(0.995, 1.015, r));

          float filament = 0.0;
          if (uAmp > 0.03) {
            float fw1 = sin(lon * 3.0 + lat * 2.0 + uNoiseTime * 3.4)
                      * sin(lat * 5.0 - uNoiseTime * 2.1);
            float fw2 = sin(lon * 7.0 - lat * 4.5 - uNoiseTime * 5.2)
                      * cos(lat * 3.0 + uNoiseTime * 3.8);
            float fw  = max(smoothstep(0.82, 1.0, fw1), smoothstep(0.88, 1.0, fw2) * 0.75);
            filament = fw * uAmpFast;
          }

          vec2 hx = vec2(lon * 4.2, lat * 4.4);
          hx.x += step(1.0, mod(hx.y, 2.0)) * 0.5;
          vec2 hxF = fract(hx) - 0.5;
          float hxD = max(abs(hxF.x), abs(hxF.y) * 1.1547);
          float hex = smoothstep(0.42, 0.46, hxD) * pow(z, 0.55) * 0.5;

          vec3 waveAxis = hashAxis(uWaveSeed);
          float axisDot = dot(rN, waveAxis);
          float sweep   = sin(uNoiseTime * 4.0);
          float ringPos = abs(axisDot - sweep);
          float wave1 = 1.0 - smoothstep(0.0, 0.025, ringPos);
          vec3 waveAxis2 = hashAxis(uWaveSeed + 0.37);
          float axisDot2 = dot(rN, waveAxis2);
          float ringPos2 = abs(axisDot2 - cos(uNoiseTime * 3.5));
          float wave2 = (1.0 - smoothstep(0.0, 0.025, ringPos2)) * 0.7;
          float speakWave = (wave1 + wave2) * uAmpFast * (0.7 + uBandMid * 0.6);
          speakWave *= pow(z, 0.3);

          float speckleN = snoise(rN * 14.0 + vec3(uNoiseTime * 6.0, 0.0, 0.0));
          float speckle = smoothstep(0.55, 0.85, speckleN);
          speckle *= uBandHigh * pow(z, 0.5);

          float pupilR  = 0.10 + uAmp * 0.07;
          float irisR   = 0.26 + uAmp * 0.05;
          float pupil   = 1.0 - smoothstep(pupilR * 0.6, pupilR, r);
          float iris    = smoothstep(irisR, pupilR, r) * (1.0 - pupil);
          float irisBlades = pow(abs(sin(atan(p.y, p.x) * 14.0)), 4.0) * iris * 0.4;

          vec3 armN = rN;
          armN.xz = rot2(-0.4) * armN.xz;
          float armLon = atan(armN.x, armN.z);
          float armLat = asin(clamp(armN.y, -1.0, 1.0));
          float armHexX = armLon * 2.6;
          float armHexY = armLat * 2.6;
          armHexX += step(1.0, mod(armHexY, 2.0)) * 0.5;
          vec2 armF = fract(vec2(armHexX, armHexY)) - 0.5;
          float armD = max(abs(armF.x), abs(armF.y) * 1.1547);
          float armature = smoothstep(0.42, 0.47, armD) * pow(z, 1.4) * 0.35;

          vec3 voidCol  = vec3(0.010, 0.025, 0.095);
          vec3 plasma   = vec3(0.040, 0.155, 0.410);
          vec3 cyan     = vec3(0.210, 0.520, 0.880);
          vec3 frost    = vec3(0.620, 0.870, 1.000);
          vec3 lineCol  = vec3(0.200, 0.500, 0.850);
          vec3 arcCol   = vec3(0.400, 0.800, 1.000);
          vec3 warmLow  = vec3(0.320, 0.420, 0.780);
          vec3 speckC   = vec3(0.700, 0.900, 1.000);

          float breath = 0.55 - uAmp * 0.18 + sin(uNoiseTime * 7.0) * 0.06 * uAmp;
          vec3 col = mix(voidCol, plasma, pow(z, breath));
          col = mix(col, warmLow, uBandLow * 0.18);
          col = mix(col, cyan,    deepPlasma * 0.32);
          col = mix(col, cyan,    surfPlasma * 0.42);
          col -= vec3(0.020, 0.030, 0.050) * armature;
          col = mix(col, lineCol, grid       * 0.55);
          col = mix(col, lineCol, equator    * 0.75);
          col = mix(col, lineCol, polarRings * 0.45);
          col -= vec3(0.015, 0.025, 0.040) * hex;
          col = mix(col, frost,   fresnel    * 0.48);
          col += frost  * shell     * 0.45;
          col += arcCol * filament  * 0.55;
          col += arcCol * speakWave * 0.60;
          col += speckC * speckle   * 0.55;
          col *= (1.0 - pupil * 0.85);
          col *= (1.0 - iris * 0.25);
          col += vec3(0.20, 0.45, 0.78) * irisBlades;

          float alpha = 0.18
                      + fresnel    * 0.60
                      + deepPlasma * 0.22
                      + grid       * 0.45
                      + equator    * 0.55
                      + polarRings * 0.35
                      + surfPlasma * 0.30
                      + shell      * 0.75
                      + filament   * 0.50
                      + speakWave  * 0.55
                      + speckle    * 0.35
                      + hex        * 0.10
                      + armature   * 0.12
                      + iris       * 0.15
                      + pupil      * 0.35;
          alpha = clamp(alpha, 0.0, 1.0);

          col   *= uMorph;
          alpha *= uMorph;
          gl_FragColor = vec4(col, alpha);
        }
      `,
      transparent: true,
      blending: THREE.NormalBlending,
      depthWrite: false,
      depthTest: false,
    })

    const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat)
    scene.add(quad)

    let raf = 0
    const clock = new THREE.Clock()
    let morphCurrent = 0
    let smoothAmp = 0
    let fastAmp = 0
    let bandLow = 0
    let bandMid = 0
    let bandHigh = 0
    let noiseTime = 0
    let momentum = 0
    let waveSeed = 1
    let prevFastAmp = 0
    let silenceTimer = 0
    let lastRenderT = 0
    let visible = document.visibilityState !== "hidden"
    const IDLE_FRAME_MS = gpuTier === "low" ? 50 : 33
    const ACTIVE_FRAME_MS = gpuTier === "low" ? 33 : 16

    const onVisibility = () => {
      visible = document.visibilityState !== "hidden"
    }
    document.addEventListener("visibilitychange", onVisibility)

    const tick = () => {
      const dt = clock.getDelta()
      const t = clock.elapsedTime
      const targets = moodTargets(moodRef.current, t)
      const rawAmp = targets.amp

      smoothAmp += (rawAmp - smoothAmp) * (rawAmp > smoothAmp ? 0.55 : 0.35)
      fastAmp += (rawAmp - fastAmp) * (rawAmp > fastAmp ? 0.85 : 0.25)

      const rawLow = targets.low
      const rawMid = targets.mid
      const rawHigh = targets.high
      bandLow += (rawLow - bandLow) * (rawLow > bandLow ? 0.5 : 0.3)
      bandMid += (rawMid - bandMid) * (rawMid > bandMid ? 0.55 : 0.32)
      bandHigh += (rawHigh - bandHigh) * (rawHigh > bandHigh ? 0.8 : 0.28)

      const dAmp = fastAmp - prevFastAmp
      prevFastAmp = fastAmp
      silenceTimer = rawAmp < 0.05 ? silenceTimer + dt : 0
      if (dAmp > 0.1 && smoothAmp > 0.15 && silenceTimer === 0) {
        waveSeed = Math.random() * 1000 + 1
      }

      noiseTime += dt * Math.max(smoothAmp, 0.12) * 2.3
      momentum += dt * smoothAmp * 0.08

      morphCurrent += (1 - morphCurrent) * 0.028
      morphCurrent = Math.max(0, Math.min(1, morphCurrent))

      mat.uniforms.uNoiseTime.value = noiseTime
      mat.uniforms.uAmp.value = smoothAmp
      mat.uniforms.uAmpFast.value = fastAmp
      mat.uniforms.uBandLow.value = bandLow
      mat.uniforms.uBandMid.value = bandMid
      mat.uniforms.uBandHigh.value = bandHigh
      mat.uniforms.uWaveSeed.value = waveSeed
      mat.uniforms.uMomentum.value = momentum
      mat.uniforms.uMorph.value = morphCurrent

      const nowMs = performance.now()
      const isAnimating = smoothAmp > 0.015 || fastAmp > 0.015
      const frameBudget = isAnimating ? ACTIVE_FRAME_MS : IDLE_FRAME_MS
      if (visible && morphCurrent > 0.001 && nowMs - lastRenderT >= frameBudget) {
        renderer.render(scene, camera)
        lastRenderT = nowMs
      }
      raf = requestAnimationFrame(tick)
    }
    tick()

    return () => {
      document.removeEventListener("visibilitychange", onVisibility)
      cancelAnimationFrame(raf)
      renderer.dispose()
      mat.dispose()
      quad.geometry.dispose()
      mount.removeChild(renderer.domElement)
    }
  }, [reducedMotion, size, gpuTier])

  if (reducedMotion) {
    return (
      <div
        className="hud-orb-static"
        style={{ width: size, height: size }}
        aria-hidden
      />
    )
  }

  return (
    <div
      ref={mountRef}
      className={`hud-orb-canvas${mood === "alert" ? " hud-orb-alert" : ""}`}
      style={{ width: size, height: size, position: "relative", background: "transparent" }}
    />
  )
}
