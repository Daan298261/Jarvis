import { useCallback, useEffect, useState } from "react"
import {
  getSelectedRuntimeProfileId,
  listRuntimeProfiles,
  type RuntimeProfile,
} from "../api"

export const HEXSTRIKE_SHAPE_ID = "hex_aegis"
export const HEXSTRIKE_SUITE_IDS = new Set([
  "hexstrike-suite",
  "hexstrike",
  "recommended-hexstrike-suite",
])

export function isHexStrikeSuiteProfile(
  profile: Pick<RuntimeProfile, "id" | "name" | "provider" | "capability_tags">,
): boolean {
  if (HEXSTRIKE_SUITE_IDS.has(profile.name) || HEXSTRIKE_SUITE_IDS.has(profile.id)) return true
  if ((profile.provider || "").toLowerCase() === "hexstrike") return true
  return (profile.capability_tags || []).some(
    (tag) => tag === "suite:hexstrike" || tag === "hexstrike",
  )
}

export function profileIsHexStrike(profileId: string, profiles: RuntimeProfile[]): boolean {
  if (!profileId) return false
  if (HEXSTRIKE_SUITE_IDS.has(profileId)) return true
  const profile = profiles.find((item) => item.id === profileId || item.name === profileId)
  return profile ? isHexStrikeSuiteProfile(profile) : false
}

export function useHexStrikeSuiteActive(): {
  active: boolean
  profile: RuntimeProfile | null
  profiles: RuntimeProfile[]
} {
  const [profiles, setProfiles] = useState<RuntimeProfile[]>([])
  const [selectedId, setSelectedId] = useState(getSelectedRuntimeProfileId)

  const refresh = useCallback(async () => {
    try {
      const data = await listRuntimeProfiles()
      setProfiles(data.profiles || [])
    } catch {
      setProfiles([])
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    const onRuntimeChange = (event: Event) => {
      const detail = (event as CustomEvent<{ id?: string }>).detail
      setSelectedId(detail?.id ?? getSelectedRuntimeProfileId())
      void refresh()
    }
    window.addEventListener("jarvis:runtime-profile-changed", onRuntimeChange)
    return () => window.removeEventListener("jarvis:runtime-profile-changed", onRuntimeChange)
  }, [refresh])

  const profile =
    profiles.find((item) => item.id === selectedId || item.name === selectedId) || null
  const active = profileIsHexStrike(selectedId, profiles)

  return { active, profile, profiles }
}
