/** Small, authored motion cues consumed by the one shared particle stage. */
export type AvatarMotionProfile = {
  name: string
  period: number
  hover: number
  sway: number
  turn: number
  tilt: number
  flutter: number
  ripple: number
}

export const AVATAR_MOTION_PROFILES: Record<string, AvatarMotionProfile> = {
  anzu: { name: "stormbird hover", period: 5.8, hover: 0.034, sway: 0.016, turn: 0.018, tilt: 0.008, flutter: 0.022, ripple: 0 },
  mestor: { name: "measured nod", period: 8.4, hover: 0.010, sway: 0.004, turn: 0.016, tilt: 0.010, flutter: 0, ripple: 0 },
  nabu: { name: "curious owl tilt", period: 7.4, hover: 0.014, sway: 0.006, turn: 0.028, tilt: 0.030, flutter: 0.010, ripple: 0 },
  enki: { name: "water drift", period: 9.0, hover: 0.021, sway: 0.014, turn: 0.016, tilt: 0.006, flutter: 0, ripple: 0.018 },
  veles: { name: "serpent sway", period: 7.8, hover: 0.013, sway: 0.022, turn: 0.030, tilt: 0.010, flutter: 0, ripple: 0.010 },
  themis: { name: "balanced breath", period: 9.8, hover: 0.008, sway: 0.004, turn: 0.012, tilt: 0.004, flutter: 0, ripple: 0 },
  aegir: { name: "ocean swell", period: 8.8, hover: 0.027, sway: 0.016, turn: 0.022, tilt: 0.008, flutter: 0, ripple: 0.020 },
  bragi: { name: "lyrical nod", period: 6.4, hover: 0.015, sway: 0.009, turn: 0.022, tilt: 0.016, flutter: 0, ripple: 0.008 },
  hermes: { name: "messenger hover", period: 5.2, hover: 0.028, sway: 0.019, turn: 0.022, tilt: 0.014, flutter: 0.014, ripple: 0 },
  heimdall: { name: "watchful sweep", period: 10.6, hover: 0.008, sway: 0.004, turn: 0.035, tilt: 0.004, flutter: 0, ripple: 0 },
  eir: { name: "gentle breath", period: 10.2, hover: 0.013, sway: 0.009, turn: 0.012, tilt: 0.008, flutter: 0.006, ripple: 0 },
  maia: { name: "celestial float", period: 9.2, hover: 0.026, sway: 0.015, turn: 0.020, tilt: 0.012, flutter: 0.005, ripple: 0.008 },
  vulcan: { name: "forge pulse", period: 7.0, hover: 0.009, sway: 0.004, turn: 0.014, tilt: 0.006, flutter: 0, ripple: 0.006 },
  umi: { name: "deep tide", period: 11.4, hover: 0.021, sway: 0.012, turn: 0.018, tilt: 0.008, flutter: 0, ripple: 0.018 },
  humanoid: { name: "human breath", period: 8.2, hover: 0.012, sway: 0.004, turn: 0.014, tilt: 0.006, flutter: 0, ripple: 0 },
  humanoid_muscular: { name: "steady human breath", period: 9.2, hover: 0.010, sway: 0.003, turn: 0.010, tilt: 0.005, flutter: 0, ripple: 0 },
}

const SHAPE_PERSONAS: Record<string, string> = {
  stormbird: "anzu", command_facet: "mestor", memory_rings: "nabu", code_cube: "enki",
  serpent_orbit: "veles", twin_shield: "themis", ocean_swell: "aegir", waveform_letters: "bragi",
  comet_trail: "hermes", eye_radar: "heimdall", breath_leaf: "eir", star_social: "maia",
  forge_core: "vulcan", opus_tide: "umi", humanoid_bust: "humanoid",
}

export function avatarMotionProfile(shapeId: string): AvatarMotionProfile {
  const key = shapeId.replace(/^portrait_/, "").replace(/_(?:living_)?b$/, "")
  return AVATAR_MOTION_PROFILES[SHAPE_PERSONAS[key] ?? key] ?? AVATAR_MOTION_PROFILES.humanoid
}

export function sampleAvatarMotion(profile: AvatarMotionProfile, seconds: number, intensity: number, reduced: boolean) {
  const amount = reduced || !Number.isFinite(intensity) ? 0 : Math.max(0, Math.min(1, intensity))
  const t = Number.isFinite(seconds) ? seconds * Math.PI * 2 / profile.period : 0
  return {
    x: Math.sin(t * 0.71) * profile.sway * amount,
    y: Math.sin(t) * profile.hover * amount,
    yaw: Math.sin(t * 0.63) * profile.turn * amount,
    pitch: Math.sin(t * 0.87) * profile.tilt * amount * 0.4,
    roll: Math.sin(t * 0.79) * profile.tilt * amount,
    scale: 1 + Math.sin(t) * 0.006 * amount,
    flutter: Math.sin(t * 2) * profile.flutter * amount,
    ripple: Math.sin(t * 1.3) * profile.ripple * amount,
  }
}
