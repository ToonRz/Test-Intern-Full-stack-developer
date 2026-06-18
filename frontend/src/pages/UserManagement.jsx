import { useState, useEffect, useCallback } from 'react'
import {
  UserPlus, Loader2, Trash2, X, Shield, ShieldCheck, KeyRound,
} from 'lucide-react'
import { users, tenants } from '../services/api'
import clsx from 'clsx'

const EMPTY_FORM = {
  username: '',
  email: '',
  password: '',
  role: 'Viewer',
  tenant: '',
}

function UserManagement() {
  const [userList, setUserList] = useState([])
  const [tenantList, setTenantList] = useState([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [formData, setFormData] = useState(EMPTY_FORM)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')
  const [deletingId, setDeletingId] = useState(null)

  const loadUsers = useCallback(async () => {
    setLoading(true)
    try {
      const res = await users.list()
      setUserList(Array.isArray(res.data) ? res.data : [])
    } catch (err) {
      console.error('Load users error:', err)
      setUserList([])
    } finally {
      setLoading(false)
    }
  }, [])

  const loadTenants = useCallback(async () => {
    try {
      const res = await tenants.list()
      setTenantList(Array.isArray(res.data) ? res.data : [])
    } catch (err) {
      // Viewer role can't hit /tenants — that's expected, just leave the list empty.
      console.error('Load tenants error:', err)
      setTenantList([])
    }
  }, [])

  useEffect(() => { loadUsers() }, [loadUsers])
  useEffect(() => { loadTenants() }, [loadTenants])

  const closeForm = () => {
    setShowForm(false)
    setFormData(EMPTY_FORM)
    setError('')
  }

  const handleCreate = async (e) => {
    e.preventDefault()
    setCreating(true)
    setError('')
    try {
      // Map the form's "all tenants" sentinel to the server's `*` value when
      // the role is Admin and the user explicitly chose to grant cross-tenant
      // access. Otherwise pass the chosen tenant (or empty string for Viewers
      // who haven't picked one — the backend defaults to `""` which means
      // "assign on first login" / no access yet).
      const payload = { ...formData }
      if (formData.role === 'Admin' && formData.tenant === '*') {
        payload.tenant = '*'
      }
      await users.create(payload)
      closeForm()
      loadUsers()
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to create user')
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (id) => {
    if (!confirm('Delete this user?')) return
    setDeletingId(id)
    try {
      await users.delete(id)
      loadUsers()
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to delete user')
    } finally {
      setDeletingId(null)
    }
  }

  const isAdmin = formData.role === 'Admin'

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl" style={{ color: 'var(--color-ink)' }}>User Management</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--color-muted)' }}>
            Manage users and their access levels (Admin only)
          </p>
        </div>
        <button
          className="btn btn-primary"
          onClick={() => (showForm ? closeForm() : setShowForm(true))}
        >
          {showForm ? <X className="w-4 h-4" /> : <UserPlus className="w-4 h-4" />}
          {showForm ? 'Cancel' : 'Add user'}
        </button>
      </header>

      {showForm && (
        <section className="card" style={{ borderLeft: '4px solid var(--color-primary)' }}>
          <h2 className="font-display text-lg mb-4" style={{ color: 'var(--color-ink)' }}>Create new user</h2>
          {/* md: breakpoint is 768px — wide enough for two columns on a 13"
              laptop so the fields stay side-by-side instead of stacking. */}
          <form onSubmit={handleCreate} className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="label-overline">Username *</label>
              <input
                value={formData.username}
                onChange={(e) => setFormData({ ...formData, username: e.target.value })}
                className="input"
                required
                minLength={3}
                autoComplete="off"
              />
            </div>
            <div>
              <label className="label-overline">Password *</label>
              <input
                type="password"
                value={formData.password}
                onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                className="input"
                required
                minLength={8}
                autoComplete="new-password"
              />
            </div>
            <div>
              <label className="label-overline">Email</label>
              <input
                type="email"
                value={formData.email}
                onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                className="input"
                autoComplete="off"
              />
            </div>
            <div>
              <label className="label-overline">Role *</label>
              <select
                value={formData.role}
                onChange={(e) => setFormData({ ...formData, role: e.target.value, tenant: '' })}
                className="input"
              >
                <option value="Viewer">Viewer</option>
                <option value="Admin">Admin</option>
              </select>
            </div>

            <div className="md:col-span-2">
              <label className="label-overline">
                Tenant {isAdmin ? '(or "All tenants" for cross-tenant access)' : '*'}
              </label>
              {tenantList.length === 0 ? (
                <input
                  value={formData.tenant}
                  onChange={(e) => setFormData({ ...formData, tenant: e.target.value })}
                  className="input"
                  placeholder={isAdmin ? 'Leave empty for all tenants' : 'demoA'}
                />
              ) : (
                <select
                  value={formData.tenant}
                  onChange={(e) => setFormData({ ...formData, tenant: e.target.value })}
                  className="input"
                  required={!isAdmin}
                >
                  {isAdmin && <option value="*">All tenants (cross-tenant access)</option>}
                  {isAdmin && <option value="">— None —</option>}
                  {!isAdmin && <option value="">Select tenant…</option>}
                  {tenantList.map((t) => (
                    <option key={t.id} value={t.name}>{t.name}</option>
                  ))}
                </select>
              )}
              {!isAdmin && tenantList.length === 0 && (
                <p className="text-xs mt-1" style={{ color: 'var(--color-muted)' }}>
                  No tenants registered yet. Create one from <code>/tenants</code> first.
                </p>
              )}
            </div>

            {error && (
              <div
                className="text-sm px-3 py-2 rounded-md md:col-span-2"
                style={{
                  backgroundColor: 'rgba(198, 69, 69, 0.10)',
                  color: 'var(--color-error)',
                  border: '1px solid rgba(198, 69, 69, 0.25)',
                }}
              >
                {error}
              </div>
            )}

            <div className="flex gap-3 md:col-span-2">
              <button type="submit" disabled={creating} className="btn btn-primary">
                {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <UserPlus className="w-4 h-4" />}
                Create user
              </button>
              <button type="button" onClick={closeForm} className="btn btn-secondary">Cancel</button>
            </div>
          </form>
        </section>
      )}

      <section className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: '1px solid var(--color-hairline)' }}>
                <th className="text-left px-3 py-2 label-overline">Username</th>
                <th className="text-left px-3 py-2 label-overline">Email</th>
                <th className="text-left px-3 py-2 label-overline">Role</th>
                <th className="text-left px-3 py-2 label-overline">Tenant</th>
                <th className="text-left px-3 py-2 label-overline">Created</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={6} className="text-center py-12">
                  <Loader2 className="w-6 h-6 animate-spin mx-auto" style={{ color: 'var(--color-primary)' }} />
                </td></tr>
              ) : userList.length === 0 ? (
                <tr><td colSpan={6} className="text-center py-12" style={{ color: 'var(--color-muted)' }}>
                  No users found
                </td></tr>
              ) : userList.map((u) => (
                <tr key={u.id} style={{ borderTop: '1px solid var(--color-hairline-soft)' }}>
                  <td className="px-3 py-2 font-medium" style={{ color: 'var(--color-ink)' }}>
                    <div className="flex items-center gap-2">
                      {u.role === 'Admin'
                        ? <ShieldCheck className="w-4 h-4" style={{ color: 'var(--color-primary)' }} />
                        : <Shield className="w-4 h-4" style={{ color: 'var(--color-muted)' }} />}
                      {u.username}
                    </div>
                  </td>
                  <td className="px-3 py-2" style={{ color: 'var(--color-muted)' }}>{u.email || '-'}</td>
                  <td className="px-3 py-2">
                    <span className={clsx('badge-pill', u.role === 'Admin' && 'badge-coral')}>{u.role}</span>
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">
                    {u.tenant === '*'
                      ? <span style={{ color: 'var(--color-primary)' }}>All tenants</span>
                      : u.tenant || <span style={{ color: 'var(--color-muted-soft)' }}>—</span>}
                  </td>
                  <td className="px-3 py-2 text-xs" style={{ color: 'var(--color-muted)' }}>
                    {u.created_at ? new Date(u.created_at).toLocaleDateString() : '-'}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button
                      onClick={() => handleDelete(u.id)}
                      disabled={deletingId === u.id}
                      className="btn btn-ghost"
                      style={{ color: 'var(--color-error)' }}
                      aria-label="Delete"
                      title="Delete user"
                    >
                      {deletingId === u.id
                        ? <Loader2 className="w-4 h-4 animate-spin" />
                        : <Trash2 className="w-4 h-4" />}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}

export default UserManagement