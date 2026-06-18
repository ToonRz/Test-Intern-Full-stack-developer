import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { useState, useEffect } from 'react'
import Layout from './components/Layout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import LogSearch from './pages/LogSearch'
import AlertRules from './pages/AlertRules'
import AlertTriggered from './pages/AlertTriggered'
import UserManagement from './pages/UserManagement'

function ProtectedRoute({ token, children }) {
  const location = useLocation()
  if (!token) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }
  return children
}

function App() {
  const [token, setToken] = useState(() => localStorage.getItem('token') || null)

  useEffect(() => {
    const onStorage = () => setToken(localStorage.getItem('token') || null)
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const handleLogin = (newToken) => {
    localStorage.setItem('token', newToken)
    setToken(newToken)
  }

  const handleLogout = () => {
    localStorage.removeItem('token')
    setToken(null)
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={token ? <Navigate to="/" replace /> : <Login onLogin={handleLogin} />} />

        <Route
          path="/"
          element={
            <ProtectedRoute token={token}>
              <Layout onLogout={handleLogout}>
                <Dashboard />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/logs"
          element={
            <ProtectedRoute token={token}>
              <Layout onLogout={handleLogout}>
                <LogSearch />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/alerts"
          element={
            <ProtectedRoute token={token}>
              <Layout onLogout={handleLogout}>
                <AlertRules />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/alerts/triggered"
          element={
            <ProtectedRoute token={token}>
              <Layout onLogout={handleLogout}>
                <AlertTriggered />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/users"
          element={
            <ProtectedRoute token={token}>
              <Layout onLogout={handleLogout}>
                <UserManagement />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<Navigate to={token ? '/' : '/login'} replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
