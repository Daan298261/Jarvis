import { Component, Suspense, type ReactNode } from "react"

class PageErrorBoundary extends Component<{ children: ReactNode; pageKey: string }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() { return { failed: true } }

  componentDidUpdate(previous: Readonly<{ children: ReactNode; pageKey: string }>) {
    if (previous.pageKey !== this.props.pageKey && this.state.failed) this.setState({ failed: false })
  }

  render() {
    if (this.state.failed) return <section className="card" role="alert">
      <p>This page could not open. Your navigation and other pages are still available.</p>
      <button className="btn" onClick={() => window.location.reload()}>Retry page</button>
    </section>
    return this.props.children
  }
}

export function PageBoundary({ children, pageKey }: { children: ReactNode; pageKey: string }) {
  return <PageErrorBoundary pageKey={pageKey}>
    <Suspense fallback={<p role="status" aria-live="polite">Opening page…</p>}>
      {children}
    </Suspense>
  </PageErrorBoundary>
}
