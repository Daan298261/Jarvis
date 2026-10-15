const HEXSTRIKE_SUITE_IDS = new Set([
  "hexstrike-suite",
  "hexstrike",
  "recommended-hexstrike-suite",
])

export function isHexStrikeSuiteProfile(profile) {
  if (HEXSTRIKE_SUITE_IDS.has(profile.name) || HEXSTRIKE_SUITE_IDS.has(profile.id)) return true
  if ((profile.provider || "").toLowerCase() === "hexstrike") return true
  return (profile.capability_tags || []).some(
    (tag) => tag === "suite:hexstrike" || tag === "hexstrike",
  )
}
