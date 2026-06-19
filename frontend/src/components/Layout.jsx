import { Link, useLocation } from 'react-router-dom'
import { useState, useEffect } from 'react'
import {
  LayoutDashboard,
  Search,
  Bell,
  BellRing,
  LogOut,
  Users,
  Menu,
  X,
} from 'lucide-react'
import clsx from 'clsx'
import { auth as authApi } from '../services/api'

// 4-spoke radial spike mark — visual stand-in for the Anthropic wordmark.
function SpikeMark({ size = 18, color = 'currentColor' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 0 L13.5 10.5 L24 12 L13.5 13.5 L12 24 L10.5 13.5 L0 12 L10.5 10.5 Z" fill={color} />
    </svg>
  )
}

function Layout({ children, onLogout }) {
  const location = useLocation()
  const [user, setUser] = useState(null)
  const [mobileOpen, setMobileOpen] = useState(false)

  // Low #27: replaced jwtDecode(localStorage.token) with a server-side
  // /auth/me round-trip. The HttpOnly cookie is attached automatically so
  // the backend resolves the user from the JWT and returns the canonical
  // profile (we don't trust client-side decoded claims).
  useEffect(() => {
    let cancelled = false
    authApi.me()
      .then((res) => { if (!cancelled) setUser(res.data) })
      .catch(() => { if (!cancelled) setUser(null) })
    return () => { cancelled = true }
  }, [])

  const navItems = [
    { path: '/', label: 'Dashboard', icon: LayoutDashboard },
    { path: '/logs', label: 'Log Search', icon: Search },
    { path: '/alerts', label: 'Alert Rules', icon: Bell },
    { path: '/alerts/triggered', label: 'Triggered', icon: BellRing },
  ]

  if (user?.role === 'Admin') {
    navItems.push({ path: '/users', label: 'Users', icon: Users })
  }

  const isActive = (path) => {
    if (path === '/') return location.pathname === '/'
    return location.pathname === path || location.pathname.startsWith(`${path}/`)
  }

  return (
    <div className="min-h-screen flex flex-col" style={{ backgroundColor: 'var(--color-canvas)' }}>
      {/* Top nav — 64px per Design.md top-nav spec */}
      <header
        className="sticky top-0 z-40 h-16 flex items-center px-4 lg:px-8 border-b"
        style={{
          backgroundColor: 'var(--color-canvas)',
          borderColor: 'var(--color-hairline)',
        }}
      >
        <Link to="/" className="flex items-center gap-2 mr-8 flex-shrink-0">
          <span style={{ color: 'var(--color-ink)' }}>
            <SpikeMark size={20} />
          </span>
          <span className="font-display text-lg" style={{ color: 'var(--color-ink)' }}>
            Log Management
          </span>
        </Link>

        {/* Desktop horizontal nav */}
        <nav className="hidden lg:flex items-center gap-1 flex-1">
          {navItems.map(({ path, label, icon: Icon }) => (
            <Link
              key={path}
              to={path}
              className={clsx('nav-link px-3 py-2 rounded-md', isActive(path) && 'nav-link-active')}
            >
              {label}
            </Link>
          ))}
        </nav>

        <div className="flex-1 lg:flex-none" />

        {/* User pill + sign out */}
        <div className="hidden md:flex items-center gap-3">
          {user && (
            <span
              className={clsx(
                'badge-pill text-sm',
                user.role === 'Admin' ? 'badge-coral' : 'badge-teal'
              )}
            >
              {user.role}
            </span>
          )}
          <button onClick={onLogout} className="btn btn-text-link" title="Sign out">
            <LogOut className="w-4 h-4" />
            <span className="ml-1">Sign out</span>
          </button>
        </div>

        {/* Mobile burger */}
        <button
          onClick={() => setMobileOpen((v) => !v)}
          className="lg:hidden p-2 rounded-md ml-auto"
          style={{ color: 'var(--color-ink)' }}
          aria-label="Open menu"
        >
          {mobileOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
        </button>
      </header>

      {/* Mobile sheet */}
      {mobileOpen && (
        <div
          className="lg:hidden fixed inset-0 z-30 pt-16"
          style={{ backgroundColor: 'var(--color-canvas)' }}
        >
          <nav className="flex flex-col p-4 gap-1">
            {navItems.map(({ path, label, icon: Icon }) => (
              <Link
                key={path}
                to={path}
                onClick={() => setMobileOpen(false)}
                className={clsx('nav-link flex items-center gap-3 px-3 py-3 rounded-md', isActive(path) && 'nav-link-active')}
              >
                <Icon className="w-5 h-5" />
                {label}
              </Link>
            ))}
            <button
              onClick={onLogout}
              className="nav-link flex items-center gap-3 px-3 py-3 rounded-md text-left"
              style={{ color: 'var(--color-error)' }}
            >
              <LogOut className="w-5 h-5" />
              Sign out
            </button>
          </nav>
        </div>
      )}

      {/* Main content */}
      <main className="flex-1">
        <div className="max-w-[1200px] mx-auto px-4 lg:px-8 py-8">{children}</div>
      </main>
    </div>
  )
}

export default Layout
