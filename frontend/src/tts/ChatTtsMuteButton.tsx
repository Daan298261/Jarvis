type ChatTtsMuteButtonProps = {
  enabled: boolean
  onToggle: (enabled: boolean) => void
  variant?: "classic" | "hud"
  className?: string
}

export function ChatTtsMuteButton({
  enabled,
  onToggle,
  variant = "classic",
  className = "",
}: ChatTtsMuteButtonProps) {
  const label = enabled ? "Mute speech" : "Unmute speech"
  const title = enabled
    ? "Mute spoken chat replies (text still shows)"
    : "Unmute spoken chat replies"

  if (variant === "hud") {
    return (
      <button
        type="button"
        className={`btn secondary hud-tts-mute${enabled ? "" : " muted"}${className ? ` ${className}` : ""}`}
        onClick={() => onToggle(!enabled)}
        title={title}
        aria-pressed={!enabled}
        aria-label={label}
      >
        {enabled ? "Speech on" : "Muted"}
      </button>
    )
  }

  return (
    <button
      type="button"
      className={`btn secondary chat-tts-mute${enabled ? "" : " muted"}${className ? ` ${className}` : ""}`}
      onClick={() => onToggle(!enabled)}
      title={title}
      aria-pressed={!enabled}
      aria-label={label}
    >
      {enabled ? "Speech on" : "Muted"}
    </button>
  )
}
