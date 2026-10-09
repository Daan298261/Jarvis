import { useEffect, useId, useRef, useState, type HTMLAttributes, type ReactNode } from "react"
import "./collapsible-section.css"

export function CollapsibleSection({ title, storageKey, children, className = "", ...props }: Omit<HTMLAttributes<HTMLElement>, "title"> & { title: ReactNode; storageKey: string }) {
  const id = useId()
  const section = useRef<HTMLElement>(null)
  const [open, setOpen] = useState(() => {
    try { return localStorage.getItem(`anzu.disclosure.${storageKey}`) === "open" } catch { return false }
  })
  useEffect(() => {
    function revealHash() {
      let target: HTMLElement | null = null
      try { target = document.getElementById(decodeURIComponent(window.location.hash.slice(1))) } catch { return }
      if (target && section.current?.contains(target)) setOpen(true)
    }
    revealHash()
    window.addEventListener("hashchange", revealHash)
    return () => window.removeEventListener("hashchange", revealHash)
  }, [])
  function toggle() {
    const next = !open
    setOpen(next)
    try { localStorage.setItem(`anzu.disclosure.${storageKey}`, next ? "open" : "closed") } catch { /* Storage is optional. */ }
  }
  return (
    <section aria-labelledby={`${id}-title`} {...props} ref={section} className={`collapsible-section ${className}`}>
      <button type="button" className="collapsible-section-toggle" aria-expanded={open} aria-controls={id} onClick={toggle}>
        <span aria-hidden="true">{open ? "▾" : "▸"}</span>
        <span id={`${id}-title`}>{title}</span>
      </button>
      <div id={id} className="collapsible-section-body" hidden={!open}>{children}</div>
    </section>
  )
}
