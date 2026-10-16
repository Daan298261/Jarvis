import { Component, Suspense, type ReactNode } from "react"

class PageErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() { return { failed: true } }

  render() {
    if (this.state.failed) return <section className="card" role="alert">
      <p>This page could not open. Your navigation and other pages are still available.</p>
      <button className="btn" onClick={() => window.location.reload()}>Retry page</button>
    </section>
    return this.props.children
  }
}

export function PageBoundary({ children, pageKey }: { children: ReactNode; pageKey: string }) {
  return <PageErrorBoundary key={pageKey}>
    <Suspense fallback={<p role="status" aria-live="polite">Opening page…</p>}>
      {children}
    </Suspense>
  </PageErrorBoundary>
}
