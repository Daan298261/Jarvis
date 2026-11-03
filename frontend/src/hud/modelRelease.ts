export type ReleaseBackendResult = { backend: string; endpoint: string; running: boolean; released: string[]; ok: boolean; detail: string }
export type ReleaseResult = { ok: boolean; refused: boolean; reason: string; released_count?: number; results: ReleaseBackendResult[]; keep_warm?: boolean }
export type ReleaseNote = { tone: "ok" | "error"; text: string }

/** What the HUD tells the owner after Unload model: what was released, or why it was not. */
export function releaseNote(result: ReleaseResult): ReleaseNote {
  if (!result.ok) return failureNote(502, result.reason)
  const count = result.released_count ?? result.results.reduce((total, row) => total + row.released.length, 0)
  return { tone: "ok", text: `Unloaded ${count} model${count === 1 ? "" : "s"}. They load again on your next turn or a Load.` }
}

/** 409 = refused, nothing touched. 502 = a backend failed to release or could not be verified. */
export function failureNote(status: number | undefined, message: string): ReleaseNote {
  if (status === 502) return { tone: "error", text: `Unload incomplete: ${message || "a model is still loaded."}` }
  return { tone: "error", text: `Not unloaded: ${message || "the request was refused."}` }
}
