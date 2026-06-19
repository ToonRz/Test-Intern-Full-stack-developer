import { BrowserRouter, Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useState, useEffect, useCallback } from 'react'
import Layout from './components/Layout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import LogSearch from './pages/LogSearch'
import AlertRules from './pages/AlertRules'
import AlertTriggered from './pages/AlertTriggered'
import UserManagement from './pages/UserManagement'
import { auth as authApi } from './services/api'

// Low #27: session is now derived from /auth/me (cookie-sent) instead of a
// localStorage token. `null` means we haven't checked yet, `true` means the
// cookie is valid, `false` means the user must log in.
function ProtectedRoute({ session, children }) {
  const location = useLocation()
  if (session === null) return null
  if (!session) return <Navigate to="/login" state={{ from: location }} replace />
  return children
}

// Low #26: react-router lives inside BrowserRouter, but the axios 401 handler
// lives in a module-level interceptor with no router access. This bridge
// listens for the `auth:logout` event the interceptor dispatches and runs
// navigate() — keeping the client SPA intact instead of forcing a full reload.
function AuthEvents({ onLogout }) {
  const navigate = useNavigate()
  useEffect(() => {
    const onLogoutEvent = () => {
      onLogout()
      if (window.location.pathname !== '/login') {
        navigate('/login', { replace: true })
      }
    }
    window.addEventListener('auth:logout', onLogoutEvent)
    return () => window.removeEventListener('auth:logout', onLogoutEvent)
  }, [navigate, onLogout])
  return null
}

function App() {
  const [session, setSession] = useState(null)

  // On first mount, probe /auth/me. The HttpOnly cookie is sent automatically;
  // if it's present and valid we get a user back, otherwise we get 401 and
  // show the login screen.
  useEffect(() => {
    let cancelled = false
    authApi.me()
      .then(() => { if (!cancelled) setSession(true) })
      .catch(() => { if (!cancelled) setSession(false) })
    return () => { cancelled = true }
  }, [])

  const handleLogin = useCallback(() => {
    // Login response already set the cookie; mark the session active so the
    // route guard lets the user through immediately. /auth/me in Layout will
    // pick up the user details on the next protected render.
    setSession(true)
  }, [])

  const handleLogout = useCallback(async () => {
    // Best-effort: tell the backend to clear the cookie via /auth/logout.
    // We swallow errors because the local state should still reset even if
    // the request fails (e.g., the backend is briefly unreachable) — the
    // cookie's expiry on the next page load will sort things out.
    try {
      await authApi.logout()
    } catch {
      // ignore — client state reset is what matters here
    }
    setSession(false)
  }, [])

  return (
    <BrowserRouter>
      <AuthEvents onLogout={handleLogout} />
      <Routes>
        <Route
          path="/login"
          element={
            session === true
              ? <Navigate to="/" replace />
              : session === false
                ? <Login onLogin={handleLogin} />
                : null
          }
        />

        <Route
          path="/"
          element={
            <ProtectedRoute session={session}>
              <Layout onLogout={handleLogout}>
                <Dashboard />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/logs"
          element={
            <ProtectedRoute session={session}>
              <Layout onLogout={handleLogout}>
                <LogSearch />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/alerts"
          element={
            <ProtectedRoute session={session}>
              <Layout onLogout={handleLogout}>
                <AlertRules />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/alerts/triggered"
          element={
            <ProtectedRoute session={session}>
              <Layout onLogout={handleLogout}>
                <AlertTriggered />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/users"
          element={
            <ProtectedRoute session={session}>
              <Layout onLogout={handleLogout}>
                <UserManagement />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="*"
          element={
            session === false
              ? <Navigate to="/login" replace />
              : session === true
                ? <Navigate to="/" replace />
                : null
          }
        />
      </Routes>
    </BrowserRouter>
  )
}

export default App
