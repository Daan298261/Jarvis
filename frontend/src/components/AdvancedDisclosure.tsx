import type { ReactNode } from "react"
import "./advanced-disclosure.css"

/** Collapsed power-control disclosure. The summary label is exactly "Advanced". */
export function AdvancedDisclosure({ children }: { children: ReactNode }) {
  return (
    <details className="portal-advanced">
      <summary>Advanced</summary>
      <div className="portal-advanced-body">{children}</div>
    </details>
  )
}
