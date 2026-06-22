import { useState, useEffect } from 'react'
import { Plus, X, Bell, Loader2, Zap, ExternalLink, Pencil, Trash2 } from 'lucide-react'
import { alerts, auth as authApi, tenants as tenantsApi } from '../services/api'
import clsx from 'clsx'

const EVENT_TYPE_SUGGESTIONS = [
  'LogonFailed', 'app_login_failed', 'malware_detected',
  'CreateUser', 'DeleteUser', 'UserLoggedIn',
]

// "*" = global rule that fires for any tenant's logs (spec §6). Per-tenant
// rules restrict the trigger to a single tenant only.
const EMPTY_FORM = {
  name: '',
  description: '',
  tenant: '*',
  event_types: ['LogonFailed'],
  threshold: 5,
  window_minutes: 5,
  action: 'store',
  webhook_url: '',
  email_to: '',
}

function AlertRules() {
  const [rules, setRules] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [formData, setFormData] = useState(EMPTY_FORM)
  const [customEventType, setCustomEventType] = useState('')
  const [loading, setLoading] = useState(false)
  const [userRole, setUserRole] = useState(null)
  const [errors, setErrors] = useState({})
  const [tenantList, setTenantList] = useState([])

  useEffect(() => {
    loadRules()
    // Low #27: role is now derived from /auth/me (cookie-sent) instead of a
    // client-side JWT decode. The HttpOnly cookie carries the token; the
    // server resolves the canonical role claim and returns it. We don't
    // trust client-side decoded claims.
    let cancelled = false
    authApi.me()
      .then((res) => { if (!cancelled) setUserRole(res.data?.role || null) })
      .catch(() => { if (!cancelled) setUserRole(null) })
    return () => { cancelled = true }
  }, [])

  // Tenant selector is Admin-only. The list is sourced from /tenants so an
  // operator can pick the actual tenant names the system knows about instead
  // of typing free-text and missing silently.
  useEffect(() => {
    let cancelled = false
    tenantsApi.list()
      .then((res) => { if (!cancelled) setTenantList(Array.isArray(res.data) ? res.data : []) })
      .catch(() => { if (!cancelled) setTenantList([]) })
    return () => { cancelled = true }
  }, [])

  const loadRules = async () => {
    setLoading(true)
    try {
      const res = await alerts.list()
      setRules(res.data.rules || [])
    } catch (err) {
      console.error('Load rules error:', err)
    } finally {
      setLoading(false)
    }
  }

  const validate = () => {
    const e = {}
    if (!formData.name.trim()) e.name = 'Name is required'
    if (!formData.event_types.length) e.event_types = 'Select at least one event type'
    if (formData.threshold < 1) e.threshold = 'Threshold must be ≥ 1'
    if (formData.window_minutes < 1) e.window_minutes = 'Window must be ≥ 1 minute'
    setErrors(e)
    return Object.keys(e).length === 0
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!validate()) return
    try {
      if (editingId) {
        await alerts.update(editingId, formData)
      } else {
        await alerts.create(formData)
      }
      setShowForm(false)
      setEditingId(null)
      setFormData(EMPTY_FORM)
      setCustomEventType('')
      loadRules()
    } catch (err) {
      setErrors({ submit: 'Failed to save rule: ' + (err.response?.data?.detail || err.message) })
    }
  }

  const handleEdit = (rule) => {
    setEditingId(rule.id)
    setFormData({
      name: rule.name || '',
      description: rule.description || '',
      tenant: rule.tenant || '*',
      event_types: Array.isArray(rule.event_types) ? rule.event_types : [],
      threshold: rule.threshold ?? 5,
      window_minutes: rule.window_minutes ?? 5,
      action: rule.action || 'store',
      webhook_url: rule.webhook_url || '',
      email_to: rule.email_to || '',
    })
    setCustomEventType('')
    setErrors({})
    setShowForm(true)
  }

  const closeForm = () => {
    setShowForm(false)
    setEditingId(null)
    setFormData(EMPTY_FORM)
    setCustomEventType('')
    setErrors({})
  }

  const [deletingRule, setDeletingRule] = useState(null)
  const [deleteError, setDeleteError] = useState(null)

  const requestDelete = (rule) => {
    setDeleteError(null)
    setDeletingRule(rule)
  }

  const cancelDelete = () => {
    setDeletingRule(null)
    setDeleteError(null)
  }

  const confirmDelete = async () => {
    if (!deletingRule) return
    try {
      await alerts.delete(deletingRule.id)
      setDeletingRule(null)
      setDeleteError(null)
      loadRules()
    } catch (err) {
      setDeleteError(err.response?.data?.detail || err.message || 'Failed to delete rule')
    }
  }

  const toggleEventType = (et) => {
    setFormData((prev) => ({
      ...prev,
      event_types: prev.event_types.includes(et)
        ? prev.event_types.filter((x) => x !== et)
        : [...prev.event_types, et],
    }))
  }

  // Medium #23: let users add their own event types beyond the hard-coded
  // suggestions — the alert engine accepts arbitrary strings, so the UI
  // shouldn't artificially limit the vocabulary.
  const addCustomEventType = () => {
    const trimmed = customEventType.trim()
    if (!trimmed) return
    if (formData.event_types.includes(trimmed)) {
      setCustomEventType('')
      return
    }
    setFormData((prev) => ({ ...prev, event_types: [...prev.event_types, trimmed] }))
    setCustomEventType('')
  }

  const removeEventType = (et) => {
    setFormData((prev) => ({
      ...prev,
      event_types: prev.event_types.filter((x) => x !== et),
    }))
  }

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="font-display text-3xl" style={{ color: 'var(--color-ink)' }}>Alert Rules</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--color-muted)' }}>
            Configure automated detection rules
          </p>
        </div>
        {userRole === 'Admin' && (
          <button className="btn btn-primary" onClick={() => (showForm ? closeForm() : setShowForm(true))}>
            {showForm ? <X className="w-4 h-4" /> : <Plus className="w-4 h-4" />}
            {showForm ? 'Cancel' : 'New rule'}
          </button>
        )}
      </header>

      {showForm && (
        <section className="card" style={{ borderLeft: '4px solid var(--color-primary)' }}>
          <div className="flex items-center gap-2 mb-5">
            <Zap className="w-5 h-5" style={{ color: 'var(--color-primary)' }} />
            <h2 className="font-display text-lg" style={{ color: 'var(--color-ink)' }}>
              {editingId ? 'Edit alert rule' : 'New alert rule'}
            </h2>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
              <div>
                <label className="label-overline">Rule name *</label>
                <input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="input"
                  placeholder="Brute Force Login Detection"
                />
                {errors.name && <p className="text-xs mt-1" style={{ color: 'var(--color-error)' }}>{errors.name}</p>}
              </div>

              <div>
                <label className="label-overline">Description</label>
                <input
                  type="text"
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  className="input"
                  placeholder="What does this rule detect?"
                />
              </div>

              {/* Tenant selector — Admin can scope a rule to one tenant or
                  leave it as "*" (global). Viewer doesn't see this row; their
                  rules are always scoped to their own tenant server-side. */}
              {userRole === 'Admin' && (
                <div>
                  <label className="label-overline">Tenant scope</label>
                  <select
                    value={formData.tenant}
                    onChange={(e) => setFormData({ ...formData, tenant: e.target.value })}
                    className="input"
                  >
                    <option value="*">All tenants (global)</option>
                    {tenantList.map((t) => (
                      <option key={t.id ?? t.name} value={t.name}>
                        {t.name}
                      </option>
                    ))}
                  </select>
                  <p className="text-xs mt-1" style={{ color: 'var(--color-muted)' }}>
                    Global rules fire for any tenant. Per-tenant rules only fire
                    for logs whose tenant field matches.
                  </p>
                </div>
              )}

              <div>
                <label className="label-overline">Threshold (count) *</label>
                <input
                  type="number"
                  value={formData.threshold}
                  onChange={(e) => setFormData({ ...formData, threshold: parseInt(e.target.value) || 0 })}
                  min="1"
                  className="input"
                />
                {errors.threshold && <p className="text-xs mt-1" style={{ color: 'var(--color-error)' }}>{errors.threshold}</p>}
              </div>

              <div>
                <label className="label-overline">Time window (minutes) *</label>
                <input
                  type="number"
                  value={formData.window_minutes}
                  onChange={(e) => setFormData({ ...formData, window_minutes: parseInt(e.target.value) || 0 })}
                  min="1"
                  className="input"
                />
                {errors.window_minutes && <p className="text-xs mt-1" style={{ color: 'var(--color-error)' }}>{errors.window_minutes}</p>}
              </div>

              <div>
                <label className="label-overline">Action</label>
                <select
                  value={formData.action}
                  onChange={(e) => setFormData({ ...formData, action: e.target.value })}
                  className="input"
                >
                  <option value="store">Store only</option>
                  <option value="webhook">Webhook</option>
                  <option value="email">Email</option>
                  <option value="both">Webhook + Email</option>
                </select>
              </div>

              {(formData.action === 'webhook' || formData.action === 'both') && (
                <div>
                  <label className="label-overline">Webhook URL</label>
                  <input
                    type="url"
                    value={formData.webhook_url}
                    onChange={(e) => setFormData({ ...formData, webhook_url: e.target.value })}
                    className="input"
                    placeholder="https://..."
                  />
                </div>
              )}

              {(formData.action === 'email' || formData.action === 'both') && (
                <div>
                  <label className="label-overline">Email recipients</label>
                  <input
                    type="email"
                    value={formData.email_to}
                    onChange={(e) => setFormData({ ...formData, email_to: e.target.value })}
                    className="input"
                    placeholder="sec@example.com"
                  />
                </div>
              )}
            </div>

            <div>
              <label className="label-overline">Event types *</label>
              <div className="flex flex-wrap gap-2 mt-2">
                {EVENT_TYPE_SUGGESTIONS.map((et) => (
                  <button
                    key={et}
                    type="button"
                    onClick={() => toggleEventType(et)}
                    className={clsx(
                      'px-3 py-1.5 rounded-md text-xs font-medium transition-colors',
                      formData.event_types.includes(et) ? 'btn-primary' : 'btn-secondary',
                    )}
                  >
                    {et}
                  </button>
                ))}
              </div>

              {/* Medium #23: allow custom event types beyond the suggestions */}
              <div className="flex gap-2 mt-3">
                <input
                  type="text"
                  value={customEventType}
                  onChange={(e) => setCustomEventType(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      addCustomEventType()
                    }
                  }}
                  className="input flex-1"
                  placeholder="Add custom event type (e.g. SuspiciousProcessDetected)"
                />
                <button
                  type="button"
                  onClick={addCustomEventType}
                  className="btn btn-secondary"
                  disabled={!customEventType.trim()}
                >
                  <Plus className="w-4 h-4" /> Add
                </button>
              </div>

              {formData.event_types.filter((et) => !EVENT_TYPE_SUGGESTIONS.includes(et)).length > 0 && (
                <div className="flex flex-wrap gap-1.5 mt-3">
                  {formData.event_types
                    .filter((et) => !EVENT_TYPE_SUGGESTIONS.includes(et))
                    .map((et) => (
                      <span key={et} className="badge-pill text-xs flex items-center gap-1">
                        {et}
                        <button
                          type="button"
                          onClick={() => removeEventType(et)}
                          aria-label={`Remove ${et}`}
                          style={{ background: 'transparent', border: 0, padding: 0, cursor: 'pointer', color: 'inherit' }}
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    ))}
                </div>
              )}

              {errors.event_types && <p className="text-xs mt-1" style={{ color: 'var(--color-error)' }}>{errors.event_types}</p>}
            </div>

            {errors.submit && (
              <div
                className="text-sm px-3 py-2 rounded-md"
                style={{
                  backgroundColor: 'rgba(198, 69, 69, 0.10)',
                  color: 'var(--color-error)',
                  border: '1px solid rgba(198, 69, 69, 0.25)',
                }}
              >
                {errors.submit}
              </div>
            )}

            <div className="flex justify-end gap-3">
              <button type="button" onClick={closeForm} className="btn btn-secondary">Cancel</button>
              <button type="submit" className="btn btn-primary">
                <Bell className="w-4 h-4" />
                {editingId ? 'Save changes' : 'Save rule'}
              </button>
            </div>
          </form>
        </section>
      )}

      <section className="space-y-3">
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-8 h-8 animate-spin" style={{ color: 'var(--color-primary)' }} />
          </div>
        ) : rules.length === 0 ? (
          <div className="card text-center">
            <Bell className="w-12 h-12 mx-auto mb-3" style={{ color: 'var(--color-hairline)' }} />
            <p style={{ color: 'var(--color-muted)' }}>No alert rules configured</p>
            {userRole === 'Admin' && (
              <button onClick={() => setShowForm(true)} className="btn btn-primary mt-4">
                <Plus className="w-4 h-4" /> Create first rule
              </button>
            )}
          </div>
        ) : (
          rules.map((rule) => (
            <article key={rule.id} className="card">
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3 mb-2">
                    <h3 className="text-base font-medium" style={{ color: 'var(--color-ink)' }}>{rule.name}</h3>
                    <span className={clsx('badge-pill', rule.enabled ? 'badge-active' : 'badge-muted')}>
                      {rule.enabled ? 'Active' : 'Disabled'}
                    </span>
                    {rule.tenant && rule.tenant !== '*' && (
                      <span className="badge-pill badge-muted">tenant: {rule.tenant}</span>
                    )}
                    {rule.tenant === '*' && (
                      <span className="badge-pill badge-muted">all tenants</span>
                    )}
                  </div>
                  {rule.description && (
                    <p className="text-sm mb-3" style={{ color: 'var(--color-muted)' }}>{rule.description}</p>
                  )}
                  <div className="flex flex-wrap gap-3 text-xs" style={{ color: 'var(--color-muted)' }}>
                    <span className="flex items-center gap-1">
                      <Zap className="w-3 h-3" style={{ color: 'var(--color-accent-amber)' }} />
                      {rule.threshold} events
                    </span>
                    <span>within {rule.window_minutes}m</span>
                    <span>grouped by: {rule.group_by || 'src_ip'}</span>
                    <span>action: {rule.action}</span>
                    {rule.webhook_url && (
                      <span className="flex items-center gap-1" style={{ color: 'var(--color-primary)' }}>
                        <ExternalLink className="w-3 h-3" /> Webhook configured
                      </span>
                    )}
                  </div>
                  {rule.event_types?.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-3">
                      {rule.event_types.map((et) => (
                        <span key={et} className="badge-pill text-xs">{et}</span>
                      ))}
                    </div>
                  )}
                </div>

                {/* Admin actions. Delete deviates from spec §7 ("ดู/สร้าง/แก้ไข" only)
                    but the backend DELETE /alerts/{id} already exists for ops use —
                    this exposes it to Admins via a confirmation modal so an
                    accidental click cannot destroy a rule. */}
                {userRole === 'Admin' && (
                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      onClick={() => handleEdit(rule)}
                      className="btn btn-ghost"
                      aria-label="Edit rule"
                      title="Edit rule"
                    >
                      <Pencil className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => requestDelete(rule)}
                      className="btn btn-ghost"
                      aria-label="Delete rule"
                      title="Delete rule"
                      style={{ color: 'var(--color-accent-red, #dc2626)' }}
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                )}
              </div>
            </article>
          ))
        )}
      </section>

      {deletingRule && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ backgroundColor: 'rgba(15, 23, 42, 0.45)' }}
          onClick={cancelDelete}
        >
          <div
            className="card w-full max-w-md"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-rule-title"
          >
            <header className="flex items-center justify-between mb-4">
              <h2 id="delete-rule-title" className="font-display text-lg" style={{ color: 'var(--color-ink)' }}>
                Delete alert rule?
              </h2>
              <button onClick={cancelDelete} className="btn btn-ghost" aria-label="Close">
                <X className="w-4 h-4" />
              </button>
            </header>

            <p className="text-sm mb-2" style={{ color: 'var(--color-muted)' }}>
              You are about to permanently delete:
            </p>
            <p className="text-sm font-medium mb-4" style={{ color: 'var(--color-ink)' }}>
              {deletingRule.name}
            </p>
            <p className="text-sm mb-6" style={{ color: 'var(--color-muted)' }}>
              Any alert history triggered by this rule will also be removed. This cannot be undone.
            </p>

            {deleteError && (
              <div
                className="text-sm mb-4 px-3 py-2 rounded"
                style={{ backgroundColor: 'var(--color-accent-red, #dc2626)', color: '#fff' }}
                role="alert"
              >
                {deleteError}
              </div>
            )}

            <div className="flex items-center justify-end gap-2">
              <button onClick={cancelDelete} className="btn btn-ghost">
                Cancel
              </button>
              <button
                onClick={confirmDelete}
                className="btn"
                style={{ backgroundColor: 'var(--color-accent-red, #dc2626)', color: '#fff' }}
              >
                Delete rule
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default AlertRules
