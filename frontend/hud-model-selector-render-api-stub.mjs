// Real api.ts (for sortLmStudioProfiles and friends) with the network calls the HUD selector makes routed to the test.
export * from "./src/api.ts"
export const api = (...args) => globalThis.__hudModelApi.api(...args)
export const listRuntimeProfiles = (...args) => globalThis.__hudModelApi.listRuntimeProfiles(...args)
export const getLmStudioCatalog = (...args) => globalThis.__hudModelApi.getLmStudioCatalog(...args)
export const getSelectedRuntimeProfileId = () => globalThis.__hudModelApi.selectedId
export const getRuntimeProfile = (...args) => globalThis.__hudModelApi.getRuntimeProfile(...args)
