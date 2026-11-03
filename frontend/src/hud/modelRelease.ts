export type ReleaseModelResult = { model: string; backend: string; via: string; verified: boolean; error: string | null }
export type ReleaseSkipped = { model: string; reason: string }
export type ReleaseResult = {
  ok: boolean; refused?: boolean; reason?: string; released?: number; released_count?: number; failed?: number
  results: ReleaseModelResult[]; skipped?: ReleaseSkipped[]; keep_warm?: boolean; cancelled_tasks?: string[]
}
export type ReleaseNote = { tone: "ok" | "error"; text: string; lines?: string[] }

/** One line per model: what was released and verified, or why it was not. */
export function releaseLines(result: ReleaseResult): string[] {
  const cancelled = result.cancelled_tasks ?? []
  const head = cancelled.length ? [`Cancelled ${cancelled.length} running task${cancelled.length === 1 ? "" : "s"} (shown as cancelled in the task list).`] : []
  return head.concat((result.results ?? []).map((row) =>
    row.verified ? `Unloaded and verified: ${row.model}` : `Could not unload ${row.model}: ${row.error || "it is still loaded."}`))
}

/**
 * What the HUD tells the owner after Unload model. 200 = every model released and verified. 207 = partial: the body
 * names every model, and a partial result is never rendered as success. (409 and other refusals arrive as errors.)
 */
export function releaseNote(result: ReleaseResult): ReleaseNote {
  const rows = result.results ?? []
  const lines = releaseLines(result)
  const failed = rows.filter((row) => !row.verified).length
  const released = result.released ?? result.released_count ?? rows.filter((row) => row.verified).length
  if (!result.ok || failed > 0) {
    const total = released + (result.failed ?? failed)
    const summary = `Unload incomplete: ${released} of ${total} model${total === 1 ? "" : "s"} released.`
    return { tone: "error", text: result.reason ? `${summary} ${result.reason}` : summary, lines }
  }
  return { tone: "ok", text: `Unloaded ${released} model${released === 1 ? "" : "s"}. They load again on your next turn or a Load.`, lines }
}

/** 409 = refused, nothing touched. 502 (older backends) = a backend failed to release or could not be verified. */
export function failureNote(status: number | undefined, message: string): ReleaseNote {
  if (status === 502) return { tone: "error", text: `Unload incomplete: ${message || "a model is still loaded."}` }
  return { tone: "error", text: `Not unloaded: ${message || "the request was refused."}` }
}
