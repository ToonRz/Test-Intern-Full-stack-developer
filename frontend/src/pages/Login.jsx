import { useState } from 'react'
import { Eye, EyeOff, Loader2 } from 'lucide-react'
import { auth } from '../services/api'

// Demo accounts only auto-fill in dev — never expose production bundle with
// plaintext credentials.
const DEMO_ACCOUNTS = import.meta.env.DEV
  ? [
      { username: 'admin', password: 'admin123', role: 'Admin', desc: 'Full access across all tenants' },
      { username: 'viewer', password: 'viewer123', role: 'Viewer', desc: 'demoA tenant only' },
    ]
  : []

function SpikeMark({ size = 28 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 0 L13.5 10.5 L24 12 L13.5 13.5 L12 24 L10.5 13.5 L0 12 L10.5 10.5 Z" fill="currentColor" />
    </svg>
  )
}

function Login({ onLogin }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      // Low #27: the server-side /auth/login response sets an HttpOnly cookie
      // via Set-Cookie. We don't receive — and don't need — the raw JWT in
      // JavaScript anymore. The browser stores the cookie automatically and
      // replays it on subsequent API calls (with axios's `withCredentials`).
      await auth.login(username, password)
      onLogin()
    } catch (err) {
      setError(err.response?.data?.detail || 'Invalid credentials')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4" style={{ backgroundColor: 'var(--color-canvas)' }}>
      <div className="w-full max-w-md">
        {/* Hero band — cream + serif display per Design.md */}
        <div className="text-center mb-10">
          <div
            className="inline-flex w-14 h-14 rounded-2xl items-center justify-center mb-5"
            style={{ backgroundColor: 'var(--color-primary)', color: 'var(--color-on-primary)' }}
          >
            <SpikeMark size={26} />
          </div>
          <h1 className="font-display text-4xl mb-2" style={{ color: 'var(--color-ink)' }}>
            Log Management
          </h1>
          <p className="text-base" style={{ color: 'var(--color-muted)' }}>
            Security Intelligence Platform
          </p>
        </div>

        {/* Card */}
        <div className="card">
          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="block text-xs font-medium uppercase tracking-wider mb-2" style={{ color: 'var(--color-muted)' }}>
                Username
              </label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="input"
                placeholder="username"
                required
                autoComplete="username"
              />
            </div>

            <div>
              <label className="block text-xs font-medium uppercase tracking-wider mb-2" style={{ color: 'var(--color-muted)' }}>
                Password
              </label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="input pr-10"
                  placeholder="••••••••"
                  required
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2"
                  style={{ color: 'var(--color-muted)' }}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {error && (
              <div
                className="text-sm px-3 py-2 rounded-md"
                style={{
                  backgroundColor: 'rgba(198, 69, 69, 0.10)',
                  color: 'var(--color-error)',
                  border: '1px solid rgba(198, 69, 69, 0.25)',
                }}
              >
                {error}
              </div>
            )}

            <button type="submit" disabled={loading} className="btn btn-primary w-full">
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
              {loading ? 'Signing in…' : 'Sign in'}
            </button>
          </form>

          {DEMO_ACCOUNTS.length > 0 && (
            <>
              <div className="mt-6 pt-6 border-t" style={{ borderColor: 'var(--color-hairline)' }}>
                <p className="text-xs uppercase tracking-wider mb-3 text-center" style={{ color: 'var(--color-muted)' }}>
                  Demo accounts (dev only)
                </p>
                <div className="space-y-2">
                  {DEMO_ACCOUNTS.map((acc) => (
                    <button
                      key={acc.username}
                      type="button"
                      onClick={() => {
                        setUsername(acc.username)
                        setPassword(acc.password)
                        setError('')
                      }}
                      className="w-full text-left px-3 py-2.5 rounded-md transition-colors hover:opacity-90"
                      style={{
                        backgroundColor: 'var(--color-surface-card)',
                        border: '1px solid var(--color-hairline)',
                      }}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="text-sm font-medium" style={{ color: 'var(--color-ink)' }}>
                            {acc.username}
                          </span>
                          <span
                            className="text-xs px-1.5 py-0.5 rounded-full"
                            style={{
                              backgroundColor: acc.role === 'Admin' ? 'var(--color-primary)' : 'var(--color-surface-cream-strong)',
                              color: acc.role === 'Admin' ? 'var(--color-on-primary)' : 'var(--color-ink)',
                            }}
                          >
                            {acc.role}
                          </span>
                        </div>
                        <span className="text-xs truncate" style={{ color: 'var(--color-muted)' }}>
                          {acc.desc}
                        </span>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>

        <p className="text-center mt-6 text-xs" style={{ color: 'var(--color-muted-soft)' }}>
          Protected by JWT auth · Multi-tenant by design
        </p>
      </div>
    </div>
  )
}

export default Login
