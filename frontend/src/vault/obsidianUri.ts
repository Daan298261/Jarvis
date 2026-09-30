/** Build official Obsidian URI for focus/open (vault name = folder basename). */

/** Official installer — used when Obsidian is missing (RFC-0107 install CTA). */
export const OBSIDIAN_DOWNLOAD_URL = "https://obsidian.md/download"

export function vaultFolderName(vaultPath: string): string {
  const parts = vaultPath.replace(/\\/g, "/").split("/").filter(Boolean)
  return parts[parts.length - 1] || "vault"
}

function pctEncode(input: string): string {
  return encodeURIComponent(input).replace(/[!'()*]/g, (c) =>
    `%${c.charCodeAt(0).toString(16).toUpperCase()}`,
  )
}

export function buildObsidianOpenUri(vaultPath: string, relPath?: string): string {
  const vault = pctEncode(vaultFolderName(vaultPath))
  if (!relPath?.trim()) {
    return `obsidian://open?vault=${vault}`
  }
  const file = relPath.trim().replace(/\\/g, "/").replace(/\.md$/i, "")
  return `obsidian://open?vault=${vault}&file=${pctEncode(file)}`
}
