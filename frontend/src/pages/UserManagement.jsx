import { useState, useEffect, useCallback } from 'react'
import {
  UserPlus, Loader2, Trash2, X, Shield, ShieldCheck, KeyRound, Pencil,
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

const EMPTY_EDIT = {
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

  // Medium #18: edit-modal state. Reuses the PATCH /users/{id} endpoint
  // exposed by the API client (`users.update`). Password is optional and
  // sent only when the operator typed one — the backend hashes it then.
  const [editingUser, setEditingUser] = useState(null)
  const [editForm, setEditForm] = useState(EMPTY_EDIT)
  const [editLoading, setEditLoading] = useState(false)
  const [editError, setEditError] = useState('')

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
      // formData already carries "*" verbatim from the <select> when the
      // Admin picks "All tenants" — the backend accepts that sentinel for
      // the Admin role and rejects it for Viewer (Medium #16).
      await users.create(formData)
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

  const openEdit = (u) => {
    setEditingUser(u)
    setEditForm({
      email: u.email || '',
      password: '',
      role: u.role,
      tenant: u.tenant || '',
    })
    setEditError('')
  }

  const closeEdit = () => {
    setEditingUser(null)
    setEditForm(EMPTY_EDIT)
    setEditError('')
  }

  const handleEditSubmit = async (e) => {
    e.preventDefault()
    if (!editingUser) return
    setEditLoading(true)
    setEditError('')
    try {
      // Only send the fields the operator actually touched — the PATCH
      // endpoint treats each as optional.
      const payload = { role: editForm.role, tenant: editForm.tenant, email: editForm.email }
      if (editForm.password) payload.password = editForm.password
      await users.update(editingUser.id, payload)
      closeEdit()
      loadUsers()
    } catch (err) {
      setEditError(err.response?.data?.detail || 'Failed to update user')
    } finally {
      setEditLoading(false)
    }
  }

  const isAdmin = formData.role === 'Admin'
  const isEditAdmin = editForm.role === 'Admin'

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
                  placeholder={isAdmin ? '* or demoA' : 'demoA'}
                  required
                  minLength={1}
                />
              ) : (
                <select
                  value={formData.tenant}
                  onChange={(e) => setFormData({ ...formData, tenant: e.target.value })}
                  className="input"
                  required
                >
                  {isAdmin && <option value="*">All tenants (cross-tenant access)</option>}
                  <option value="" disabled>Select tenant…</option>
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
                    <div className="flex items-center justify-end gap-1">
                      <button
                        onClick={() => openEdit(u)}
                        className="btn btn-ghost"
                        aria-label="Edit user"
                        title="Edit user"
                      >
                        <Pencil className="w-4 h-4" />
                      </button>
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
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Medium #18: edit modal — lets an admin change email/role/tenant
          and rotate the password without leaving the user list. */}
      {editingUser && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ backgroundColor: 'rgba(15, 23, 42, 0.45)' }}
          onClick={closeEdit}
        >
          <div
            className="card w-full max-w-lg"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="edit-user-title"
          >
            <header className="flex items-center justify-between mb-4">
              <h2 id="edit-user-title" className="font-display text-lg" style={{ color: 'var(--color-ink)' }}>
                Edit user — {editingUser.username}
              </h2>
              <button onClick={closeEdit} className="btn btn-ghost" aria-label="Close">
                <X className="w-4 h-4" />
              </button>
            </header>

            <form onSubmit={handleEditSubmit} className="space-y-4">
              <div>
                <label className="label-overline">Email</label>
                <input
                  type="email"
                  value={editForm.email}
                  onChange={(e) => setEditForm({ ...editForm, email: e.target.value })}
                  className="input"
                  autoComplete="off"
                />
              </div>

              <div>
                <label className="label-overline">Role</label>
                <select
                  value={editForm.role}
                  onChange={(e) => setEditForm({ ...editForm, role: e.target.value })}
                  className="input"
                >
                  <option value="Viewer">Viewer</option>
                  <option value="Admin">Admin</option>
                </select>
              </div>

              <div>
                <label className="label-overline">
                  Tenant {isEditAdmin ? '(or "All tenants" for cross-tenant access)' : '*'}
                </label>
                {tenantList.length === 0 ? (
                  <input
                    value={editForm.tenant}
                    onChange={(e) => setEditForm({ ...editForm, tenant: e.target.value })}
                    className="input"
                    placeholder={isEditAdmin ? '* or demoA' : 'demoA'}
                    required
                    minLength={1}
                  />
                ) : (
                  <select
                    value={editForm.tenant}
                    onChange={(e) => setEditForm({ ...editForm, tenant: e.target.value })}
                    className="input"
                    required
                  >
                    {isEditAdmin && <option value="*">All tenants (cross-tenant access)</option>}
                    {tenantList.map((t) => (
                      <option key={t.id} value={t.name}>{t.name}</option>
                    ))}
                  </select>
                )}
              </div>

              <div>
                <label className="label-overline">New password (leave blank to keep current)</label>
                <div className="relative">
                  <KeyRound className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2" style={{ color: 'var(--color-muted)' }} />
                  <input
                    type="password"
                    value={editForm.password}
                    onChange={(e) => setEditForm({ ...editForm, password: e.target.value })}
                    className="input"
                    style={{ paddingLeft: '2.25rem' }}
                    autoComplete="new-password"
                    minLength={editForm.password ? 8 : undefined}
                    placeholder="••••••••"
                  />
                </div>
              </div>

              {editError && (
                <div
                  className="text-sm px-3 py-2 rounded-md"
                  style={{
                    backgroundColor: 'rgba(198, 69, 69, 0.10)',
                    color: 'var(--color-error)',
                    border: '1px solid rgba(198, 69, 69, 0.25)',
                  }}
                >
                  {editError}
                </div>
              )}

              <div className="flex justify-end gap-3">
                <button type="button" onClick={closeEdit} className="btn btn-secondary">Cancel</button>
                <button type="submit" disabled={editLoading} className="btn btn-primary">
                  {editLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Pencil className="w-4 h-4" />}
                  Save changes
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

export default UserManagement
