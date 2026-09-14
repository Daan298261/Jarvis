import { Link, useLocation, useNavigate } from "react-router-dom"

type PortalNavProps = {
  variant?: "hud" | "classic"
}

export function PortalNav({ variant = "hud" }: PortalNavProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const onHome = location.pathname === "/" || location.pathname.startsWith("/tasks/")
  const showBack = !onHome && location.pathname !== "/setup"

  if (variant === "hud") {
    return (
      <div className="portal-nav hud-portal-nav">
        <Link to="/" className="portal-nav-home hud-icon-btn" title="Home (chat)" aria-label="Home">
          ⌂
        </Link>
        {showBack && (
          <button type="button" className="portal-nav-back hud-icon-btn" onClick={() => navigate(-1)} aria-label="Back">
            ← Back
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="portal-nav classic-portal-nav">
      <Link to="/" className="btn secondary portal-nav-home" title="Home (chat)">
        ⌂ Home
      </Link>
      {showBack && (
        <button type="button" className="btn secondary portal-nav-back" onClick={() => navigate(-1)}>
          ← Back
        </button>
      )}
    </div>
  )
}
