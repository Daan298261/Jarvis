import { useCallback, useRef, useState } from "react"
import { apiForm, getAuthUrl } from "../api"

export type MediaKind = "image" | "video" | "audio" | "file"

export type PendingMedia = {
  localId: string
  name: string
  kind: MediaKind
  progress: number
  status: "uploading" | "ready" | "error" | "cancelled"
  uploadId?: string
  error?: string
  abort?: () => void
}

const CHUNK_SIZE = 2 * 1024 * 1024

function detectKind(file: File): MediaKind {
  const type = (file.type || "").toLowerCase()
  const name = file.name.toLowerCase()
  if (type.startsWith("image/") || /\.(jpe?g|png|webp|heic|gif|bmp)$/.test(name)) return "image"
  if (type.startsWith("video/") || /\.(mp4|webm|mov|mkv)$/.test(name)) return "video"
  if (type.startsWith("audio/") || /\.(wav|mp3|m4a|ogg|flac)$/.test(name)) return "audio"
  return "file"
}

async function uploadChunked(
  file: File,
  kind: MediaKind,
  onProgress: (pct: number) => void,
  signal: AbortSignal,
): Promise<{ id: string }> {
  const uploadId = crypto.randomUUID()
  const total = Math.max(1, Math.ceil(file.size / CHUNK_SIZE))
  for (let index = 0; index < total; index += 1) {
    if (signal.aborted) throw new Error("Upload cancelled")
    const start = index * CHUNK_SIZE
    const blob = file.slice(start, start + CHUNK_SIZE)
    const headers: Record<string, string> = {
      "X-Filename": file.name,
      "Content-Type": file.type || "application/octet-stream",
      "X-Jarvis-Upload-Id": uploadId,
      "X-Jarvis-Chunk-Index": String(index),
      "X-Jarvis-Chunk-Total": String(total),
      "X-Jarvis-Upload-Kind": kind,
    }
    const key = localStorage.getItem("jarvis_private_key")
    if (key) headers["X-Jarvis-Key"] = key
    const response = await fetch(getAuthUrl("/api/media/uploads"), {
      method: "POST",
      headers,
      body: blob,
      signal,
    })
    if (!response.ok) {
      const text = await response.text()
      throw new Error(text || `Upload failed (${response.status})`)
    }
    const payload = await response.json()
    onProgress(Math.round(((index + 1) / total) * 100))
    if (payload.id) return { id: payload.id }
  }
  return { id: uploadId }
}

async function uploadSimple(file: File, kind: MediaKind, signal: AbortSignal): Promise<{ id: string }> {
  const form = new FormData()
  form.append("file", file, file.name)
  form.append("kind", kind)
  const controller = new AbortController()
  signal.addEventListener("abort", () => controller.abort())
  return apiForm<{ id: string }>("/api/media/uploads", form, { signal: controller.signal })
}

export function useMediaUploads() {
  const [items, setItems] = useState<PendingMedia[]>([])
  const aborts = useRef(new Map<string, AbortController>())

  const remove = useCallback((localId: string) => {
    const ctrl = aborts.current.get(localId)
    ctrl?.abort()
    aborts.current.delete(localId)
    setItems((current) => current.filter((item) => item.localId !== localId))
  }, [])

  const clear = useCallback(() => {
    for (const ctrl of aborts.current.values()) ctrl.abort()
    aborts.current.clear()
    setItems([])
  }, [])

  const uploadFiles = useCallback(async (files: FileList | File[]) => {
    const list = Array.from(files)
    for (const file of list) {
      const localId = crypto.randomUUID()
      const kind = detectKind(file)
      const controller = new AbortController()
      aborts.current.set(localId, controller)
      setItems((current) => [
        ...current,
        { localId, name: file.name, kind, progress: 0, status: "uploading" },
      ])
      try {
        const useChunks = kind === "video" || file.size > CHUNK_SIZE
        const result = useChunks
          ? await uploadChunked(file, kind, (pct) => {
              setItems((current) =>
                current.map((item) => (item.localId === localId ? { ...item, progress: pct } : item)),
              )
            }, controller.signal)
          : await uploadSimple(file, kind, controller.signal)
        setItems((current) =>
          current.map((item) =>
            item.localId === localId
              ? { ...item, status: "ready", progress: 100, uploadId: result.id }
              : item,
          ),
        )
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err)
        if (message.includes("cancelled") || message.includes("abort")) {
          setItems((current) => current.filter((item) => item.localId !== localId))
        } else {
          setItems((current) =>
            current.map((item) =>
              item.localId === localId ? { ...item, status: "error", error: message } : item,
            ),
          )
        }
      } finally {
        aborts.current.delete(localId)
      }
    }
  }, [])

  const readyIds = items.filter((item) => item.status === "ready" && item.uploadId).map((item) => item.uploadId!)

  return { items, uploadFiles, remove, clear, readyIds, hasUploading: items.some((item) => item.status === "uploading") }
}
