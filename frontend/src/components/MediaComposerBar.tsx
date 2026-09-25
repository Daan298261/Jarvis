import { useRef, type DragEvent } from "react"
import type { PendingMedia } from "../chat/useMediaUploads"

type Props = {
  items: PendingMedia[]
  onPick: (files: FileList | File[]) => void
  onRemove: (localId: string) => void
  disabled?: boolean
  className?: string
}

export function MediaComposerBar({ items, onPick, onRemove, disabled, className }: Props) {
  const inputRef = useRef<HTMLInputElement | null>(null)

  function onDrop(event: DragEvent) {
    event.preventDefault()
    if (disabled || !event.dataTransfer.files.length) return
    onPick(event.dataTransfer.files)
  }

  function onPaste(event: React.ClipboardEvent) {
    const files: File[] = []
    for (const item of event.clipboardData.items) {
      if (item.kind === "file") {
        const file = item.getAsFile()
        if (file) files.push(file)
      }
    }
    if (files.length) {
      event.preventDefault()
      onPick(files)
    }
  }

  return (
    <div
      className={className || "media-composer-bar"}
      onDragOver={(e) => e.preventDefault()}
      onDrop={onDrop}
      onPaste={onPaste}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        hidden
        accept="image/*,video/*,audio/*,.pdf,.txt,.zip,.doc,.docx"
        onChange={(e) => {
          if (e.target.files?.length) onPick(e.target.files)
          e.target.value = ""
        }}
      />
      <button
        type="button"
        className="btn secondary"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
      >
        Attach
      </button>
      {items.length > 0 && (
        <ul className="media-composer-list">
          {items.map((item) => (
            <li key={item.localId} className={`media-composer-item ${item.status}`}>
              <span className="media-composer-name">{item.name}</span>
              <span className="media-composer-meta">{item.kind}</span>
              {item.status === "uploading" && <span className="media-composer-progress">{item.progress}%</span>}
              {item.status === "error" && <span className="media-composer-error">{item.error}</span>}
              <button type="button" className="btn secondary" onClick={() => onRemove(item.localId)}>
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
