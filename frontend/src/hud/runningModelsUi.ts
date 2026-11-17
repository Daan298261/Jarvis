/** Pure helpers for the Available local models chooser (contrast/dismiss fixes). */

export function isUnavailableError(message: string): boolean {
  return /no longer available/i.test(message) || /server changed/i.test(message)
}

export function pruneUnavailableServers<T extends { id: string }>(
  servers: T[],
  rowId: string,
  message: string,
): T[] {
  if (!isUnavailableError(message)) return servers
  return servers.filter((row) => row.id !== rowId)
}

export function unansweredOfferIds(servers: { id: string; choice: string | null }[]): string[] {
  return servers.filter((row) => !row.choice).map((row) => row.id)
}
