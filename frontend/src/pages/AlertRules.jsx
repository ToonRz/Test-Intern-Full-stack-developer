import { useState, useEffect } from 'react'
import { Plus, X, Bell, Loader2, Zap, ExternalLink } from 'lucide-react'
import { alerts } from '../services/api'
import clsx from 'clsx'
import { jwtDecode } from 'jwt-decode'

const EVENT_TYPE_SUGGESTIONS = [
  'LogonFailed', 'app_login_failed', 'malware_detected',
  'CreateUser', 'DeleteUser', 'UserLoggedIn',
]

function AlertRules() {
  const [rules, setRules] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    event_types: ['LogonFailed'],
    threshold: 5,
    window_minutes: 5,
    action: 'store',
    webhook_url: '',
    email_to: '',
  })
  const [loading, setLoading] = useState(false)
  const [userRole, setUserRole] = useState(null)
  const [errors, setErrors] = useState({})

  useEffect(() => {
    loadRules()
    const token = localStorage.getItem('token')
    if (!token) return
    try {
      setUserRole(jwtDecode(token).role)
    } catch {
      setUserRole(null)
    }
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
      await alerts.create(formData)
      setShowForm(false)
      setFormData({ name: '', description: '', event_types: ['LogonFailed'], threshold: 5, window_minutes: 5, action: 'store', webhook_url: '', email_to: '' })
      loadRules()
    } catch (err) {
      setErrors({ submit: 'Failed to create rule: ' + (err.response?.data?.detail || err.message) })
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
          <button className="btn btn-primary" onClick={() => setShowForm((v) => !v)}>
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
              New alert rule
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
              <button type="button" onClick={() => setShowForm(false)} className="btn btn-secondary">Cancel</button>
              <button type="submit" className="btn btn-primary">
                <Bell className="w-4 h-4" />
                Save rule
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
              </div>
            </article>
          ))
        )}
      </section>
    </div>
  )
}

export default AlertRules
