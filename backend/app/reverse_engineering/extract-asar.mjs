import { pathToFileURL } from "node:url"
import fs from "node:fs"
import path from "node:path"

const [modulePath, source, destination] = process.argv.slice(2)
const asar = await import(pathToFileURL(modulePath).href)
const entries = asar.listPackage(source)
if (entries.length > 50000) throw new Error("ASAR exceeds file-count limit")
const files = [], skipped = []
let total = 0
for (const entry of entries) {
  const name = entry.replace(/^[/\\]+/, "").replaceAll("\\", "/")
  if (name.split("/").includes("..") || name.includes(":")) throw new Error("Unsafe ASAR entry")
  const info = asar.statFile(source, name, false)
  if (info.files) continue
  if (info.link || info.unpacked) { skipped.push(name); continue }
  total += info.size ?? 0
  if (total > 8 * 1024 ** 3) throw new Error("ASAR exceeds expanded-size limit")
  const target = path.resolve(destination, name)
  if (!target.startsWith(path.resolve(destination) + path.sep)) throw new Error("ASAR path escapes destination")
  fs.mkdirSync(path.dirname(target), { recursive: true })
  fs.writeFileSync(target, asar.extractFile(source, name))
  files.push(name)
}
process.stdout.write(JSON.stringify({ files, skipped_link_or_unpacked_entries: skipped }))
