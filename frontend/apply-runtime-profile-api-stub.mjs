/** Test double for ../api used by applyRuntimeProfile + hexstrikeAutostart. */

const state = {
  permissionStatus: "ask",
  permissionError: null,
  profile: {
    id: "hexstrike-suite",
    name: "hexstrike-suite",
    label: "HexStrike",
    provider: "hexstrike",
    capability_tags: ["suite:hexstrike"],
  },
  startCalls: 0,
  stopCalls: 0,
  activateCalls: 0,
  selectedId: "",
  selectedMode: "",
  events: [],
  unloadCalls: 0,
  unloadError: null,
  unloadSnapshot: { loaded: false, loading: false, manually_unloaded: true, active_model: null },
}

export function __resetApiStub(overrides = {}) {
  state.permissionStatus = overrides.permissionStatus ?? "ask"
  state.permissionError = overrides.permissionError ?? null
  state.profile = overrides.profile ?? {
    id: "hexstrike-suite",
    name: "hexstrike-suite",
    label: "HexStrike",
    provider: "hexstrike",
    capability_tags: ["suite:hexstrike"],
  }
  state.startCalls = 0
  state.stopCalls = 0
  state.activateCalls = 0
  state.selectedId = ""
  state.selectedMode = ""
  state.events = []
  state.unloadCalls = 0
  state.unloadError = overrides.unloadError ?? null
  state.unloadSnapshot = overrides.unloadSnapshot ?? { loaded: false, loading: false, manually_unloaded: true, active_model: null }
}

export function __apiStubState() {
  return state
}

export class ApiError extends Error {
  constructor(status, message, body = null) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.body = body
  }
}

export function isApiError(err) {
  return err instanceof ApiError
}

export async function api(path, init) {
  if (path === "/api/model/unload" && init?.method === "POST") {
    state.unloadCalls += 1
    if (state.unloadError) throw state.unloadError
    return state.unloadSnapshot
  }
  if (path === "/api/permissions/cyber.hexstrike") {
    if (state.permissionError) throw state.permissionError
    return { id: "cyber.hexstrike", status: state.permissionStatus }
  }
  throw new Error(`unexpected api ${init?.method || "GET"} ${path}`)
}

export async function getRuntimeProfile(profileId) {
  if (profileId === state.profile.id || profileId === state.profile.name) {
    return { ...state.profile }
  }
  return {
    id: profileId,
    name: profileId,
    label: profileId,
    provider: "llamacpp",
    capability_tags: [],
  }
}

export async function startHexStrike() {
  state.startCalls += 1
  return { suite: "hexstrike", running: true }
}

export async function stopHexStrike() {
  state.stopCalls += 1
  return { suite: "hexstrike", running: false }
}

export async function activateRuntimeProfile(profileId) {
  state.activateCalls += 1
  return {
    ok: true,
    profile: { id: profileId, name: profileId, label: profileId, provider: "llamacpp" },
    load: { loaded: true, loading: false },
  }
}

export function setSelectedRuntimeProfileId(id) {
  state.selectedId = id
}

export function setSelectedRuntimeMode(mode) {
  state.selectedMode = mode
}

export async function selectLmStudioProfile() {
  throw new Error("not used in these tests")
}

export async function selectDiscoveredGguf() {
  throw new Error("not used in these tests")
}
