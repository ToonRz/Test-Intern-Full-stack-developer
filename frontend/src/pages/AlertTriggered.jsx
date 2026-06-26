import { useState, useEffect, useMemo, useRef } from 'react'
import {
  BellRing, Check, Clock, Loader2, AlertTriangle, MapPin, Filter,
  ChevronDown, ChevronUp, X, RefreshCw, ArrowLeft, ChevronRight,
} from 'lucide-react'
import { alerts } from '../services/api'
import clsx from 'clsx'
// F-C3: import from the shared utility. The previous local `severityColor`
// did `if (sev >= 9)` on a *string* bucket (`'critical' >= 9` is false),
// so every alert card rendered teal regardless of severity.
import { severityBucket, severityColor, SEVERITY_RANK } from '../utils/severity'

const SEVERITY_OPTIONS = [
  { value: '', label: 'All severities' },
  { value: 'critical', label: 'Critical' },
  { value: 'high', label: 'High' },
  { value: 'medium', label: 'Medium' },
  { value: 'low', label: 'Low' },
]

// Group a flat alert list by `rule_name`. Within a group we surface the max
// severity, the summed event count, and the most recent last_seen — the
// numbers that matter for a collapsed summary view. We sort groups so the
// freshest one floats to the top.
function groupAlertsByRule(alerts) {
  const map = new Map()
  for (const a of alerts) {
    const key = a.rule_name || '(unknown rule)'
    const existing = map.get(key)
    if (existing) {
      existing.alerts.push(a)
      existing.totalEvents += a.count || 0
      if (SEVERITY_RANK[a.severity] > SEVERITY_RANK[existing.severity]) {
        existing.severity = a.severity
      }
      if (a.last_seen && (!existing.lastSeen || a.last_seen > existing.lastSeen)) {
        existing.lastSeen = a.last_seen
      }
    } else {
      map.set(key, {
        rule_name: key,
        severity: a.severity || 'low',
        totalEvents: a.count || 0,
        lastSeen: a.last_seen || null,
        alerts: [a],
      })
    }
  }
  const groups = Array.from(map.values())
  // Sort each group's alerts newest-first so the dropdown reads top-down.
  groups.forEach((g) => {
    g.alerts.sort((a, b) => (b.last_seen || '').localeCompare(a.last_seen || ''))
  })
  groups.sort((a, b) => (b.lastSeen || '').localeCompare(a.lastSeen || ''))
  return groups
}

function AlertTriggered() {
  const [triggeredAlerts, setTriggeredAlerts] = useState([])
  const [loading, setLoading] = useState(true)
  const [acknowledging, setAcknowledging] = useState(null)
  const [filters, setFilters] = useState({ severity: '', source: '', acknowledged: '' })
  const [showFilters, setShowFilters] = useState(false)
  const [selectedAlert, setSelectedAlert] = useState(null)
  const [alertDetail, setAlertDetail] = useState(null)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [expandedGroups, setExpandedGroups] = useState(() => new Set())
  // Monotonic token so a slow in-flight request can't overwrite a fresher one
  // when the user changes filters rapidly.
  const loadTokenRef = useRef(0)

  useEffect(() => { loadAlerts() }, [filters])

  // Low #28: auto-refresh every 30s so the operator sees new triggers without
  // hammering the Refresh button. Cleanup on unmount prevents the interval
  // from leaking when the user navigates away.
  useEffect(() => {
    const id = setInterval(loadAlerts, 30000)
    return () => clearInterval(id)
    // loadAlerts reads `filters` via closure; depending on `filters` here
    // would reset the timer on every filter change which defeats the purpose.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.severity, filters.source, filters.acknowledged])

  const loadAlerts = async () => {
    const token = ++loadTokenRef.current
    setLoading(true)
    try {
      const params = { limit: 100 }
      if (filters.severity) params.severity = filters.severity
      if (filters.source) params.source = filters.source
      if (filters.acknowledged !== '') params.acknowledged = filters.acknowledged

      const res = await alerts.triggered(params)
      if (token !== loadTokenRef.current) return
      setTriggeredAlerts(res.data.alerts || [])
    } catch (err) {
      if (token !== loadTokenRef.current) return
      console.error('Load triggered alerts error:', err)
    } finally {
      if (token === loadTokenRef.current) setLoading(false)
    }
  }

  const loadAlertDetail = async (alertId) => {
    const token = loadTokenRef.current
    setLoadingDetail(true)
    try {
      const res = await alerts.detail(alertId)
      if (token !== loadTokenRef.current) return
      setAlertDetail(res.data)
    } catch (err) {
      if (token !== loadTokenRef.current) return
      console.error('Load alert detail error:', err)
    } finally {
      if (token === loadTokenRef.current) setLoadingDetail(false)
    }
  }

  const handleAcknowledge = async (id) => {
    setAcknowledging(id)
    try {
      await alerts.acknowledge(id)
      setTriggeredAlerts((prev) => prev.map((a) => (a.id === id ? { ...a, acknowledged: true } : a)))
      if (selectedAlert?.id === id) {
        setSelectedAlert((prev) => ({ ...prev, acknowledged: true }))
      }
    } catch (err) {
      console.error('Acknowledge error:', err)
    } finally {
      setAcknowledging(null)
    }
  }

  const handleAlertClick = (alert) => {
    setSelectedAlert(alert)
    loadAlertDetail(alert.id)
  }

  const handleBack = () => {
    setSelectedAlert(null)
    setAlertDetail(null)
  }

  const unacknowledged = triggeredAlerts.filter((a) => !a.acknowledged)
  const acknowledged = triggeredAlerts.filter((a) => a.acknowledged)

  // Group by rule_name at render time so the flat `triggeredAlerts` stays the
  // single source of truth (Acknowledge's optimistic update mutates it directly).
  const unackGroups = useMemo(() => groupAlertsByRule(unacknowledged), [unacknowledged])
  const ackGroups = useMemo(() => groupAlertsByRule(acknowledged), [acknowledged])

  const toggleGroup = (ruleName) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev)
      if (next.has(ruleName)) next.delete(ruleName)
      else next.add(ruleName)
      return next
    })
  }

  // Detail view
  if (selectedAlert) {
    return (
      <div className="space-y-6">
        <header className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button onClick={handleBack} className="btn btn-ghost">
              <ArrowLeft className="w-4 h-4" />
              Back
            </button>
            <div>
              <h1 className="font-display text-3xl" style={{ color: 'var(--color-ink)' }}>Alert Detail</h1>
              <p className="text-sm mt-1" style={{ color: 'var(--color-muted)' }}>{selectedAlert.rule_name}</p>
            </div>
          </div>
        </header>

        <section
          className="card"
          style={{ borderLeft: `4px solid ${severityColor(selectedAlert.severity || 5)}` }}
        >
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1 min-w-0">
              <div className="flex flex-wrap items-center gap-3 mb-4">
                <AlertTriangle className="w-5 h-5" style={{ color: severityColor(selectedAlert.severity || 5) }} />
                <h3 className="font-display text-lg" style={{ color: 'var(--color-ink)' }}>{selectedAlert.rule_name}</h3>
                <span className={`badge-pill badge-${severityBucket(selectedAlert.severity)}`}>
                  {severityBucket(selectedAlert.severity).toUpperCase()}
                </span>
                {selectedAlert.acknowledged ? (
                  <span className="badge-pill">Acknowledged</span>
                ) : (
                  <span className="badge-pill" style={{ backgroundColor: 'var(--color-accent-amber)', color: 'var(--color-on-primary)' }}>Active</span>
                )}
              </div>

              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                {[
                  ['Source IP', selectedAlert.src_ip],
                  ['Count', selectedAlert.count],
                  ['First seen', selectedAlert.first_seen ? new Date(selectedAlert.first_seen).toLocaleString() : '-'],
                  ['Last seen', selectedAlert.last_seen ? new Date(selectedAlert.last_seen).toLocaleString() : '-'],
                  ['Tenant', selectedAlert.tenant],
                  ['Source', selectedAlert.source],
                  ['Event', selectedAlert.event_type],
                  ['Rule', selectedAlert.rule_name],
                ].map(([k, v]) => (
                  <div key={k} className="p-3 rounded-md" style={{ backgroundColor: 'var(--color-surface-soft)' }}>
                    <span className="label-overline block">{k}</span>
                    <span className="font-medium break-all" style={{ color: 'var(--color-ink)' }}>{String(v ?? '-')}</span>
                  </div>
                ))}
              </div>
            </div>

            {!selectedAlert.acknowledged && (
              <button
                onClick={() => handleAcknowledge(selectedAlert.id)}
                disabled={acknowledging === selectedAlert.id}
                className="btn btn-primary"
              >
                {acknowledging === selectedAlert.id ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                Acknowledge
              </button>
            )}
          </div>
        </section>

        <section className="card">
          <h3 className="text-sm font-medium mb-4" style={{ color: 'var(--color-ink)' }}>
            Related logs ({alertDetail?.logs?.length || 0})
          </h3>
          {loadingDetail ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-6 h-6 animate-spin" style={{ color: 'var(--color-primary)' }} />
            </div>
          ) : alertDetail?.logs?.length > 0 ? (
            <div className="space-y-3">
              {alertDetail.logs.map((log) => (
                <article
                  key={log.id}
                  className="p-4 rounded-md border"
                  style={{ backgroundColor: 'var(--color-canvas)', borderColor: 'var(--color-hairline)' }}
                >
                  <div className="flex items-start justify-between mb-3 gap-2">
                    <div className="flex items-center gap-3 min-w-0">
                      <span className="w-2 h-2 rounded-full" style={{ backgroundColor: severityColor(log.severity) }} />
                      <span className="font-medium truncate" style={{ color: 'var(--color-ink)' }}>{log.event_type}</span>
                      <span className="font-mono text-sm" style={{ color: 'var(--color-muted)' }}>{log.src_ip || '-'}</span>
                    </div>
                    <span className="text-xs font-mono" style={{ color: 'var(--color-muted)' }}>
                      {log['@timestamp'] ? new Date(log['@timestamp']).toLocaleString() : '-'}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 text-xs">
                    {log.user && <div><span style={{ color: 'var(--color-muted)' }}>User:</span> <span style={{ color: 'var(--color-ink)' }}>{log.user}</span></div>}
                    {log.host && <div><span style={{ color: 'var(--color-muted)' }}>Host:</span> <span style={{ color: 'var(--color-ink)' }}>{log.host}</span></div>}
                    {log.action && <div><span style={{ color: 'var(--color-muted)' }}>Action:</span> <span style={{ color: 'var(--color-ink)' }}>{log.action}</span></div>}
                    {log.severity != null && <div><span style={{ color: 'var(--color-muted)' }}>Severity:</span> <span style={{ color: 'var(--color-ink)' }}>{log.severity}</span></div>}
                  </div>
                  {log.raw && (
                    <pre className="code-block text-xs overflow-x-auto mt-3">{JSON.stringify(log.raw, null, 2)}</pre>
                  )}
                </article>
              ))}
            </div>
          ) : (
            <p className="text-sm text-center py-4" style={{ color: 'var(--color-muted)' }}>No logs found</p>
          )}
        </section>
      </div>
    )
  }

  // List view
  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl" style={{ color: 'var(--color-ink)' }}>Triggered Alerts</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--color-muted)' }}>
            {unacknowledged.length} active · {acknowledged.length} acknowledged
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={() => setShowFilters((v) => !v)} className={clsx('btn', showFilters ? 'btn-primary' : 'btn-secondary')}>
            <Filter className="w-4 h-4" /> Filters
          </button>
          <button onClick={loadAlerts} className="btn btn-secondary">
            <RefreshCw className="w-4 h-4" /> Refresh
          </button>
        </div>
      </header>

      {showFilters && (
        <section className="card flex flex-wrap gap-4 items-end">
          <div>
            <label className="label-overline">Severity</label>
            <select
              value={filters.severity}
              onChange={(e) => setFilters((f) => ({ ...f, severity: e.target.value }))}
              className="input"
            >
              {SEVERITY_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label-overline">Status</label>
            <select
              value={filters.acknowledged}
              onChange={(e) => setFilters((f) => ({ ...f, acknowledged: e.target.value }))}
              className="input"
            >
              <option value="">All</option>
              <option value="false">Active</option>
              <option value="true">Acknowledged</option>
            </select>
          </div>
          <div>
            <label className="label-overline">Source</label>
            <input
              type="text"
              placeholder="api, ad, firewall…"
              value={filters.source}
              onChange={(e) => setFilters((f) => ({ ...f, source: e.target.value }))}
              className="input w-40"
            />
          </div>
          {(filters.severity || filters.acknowledged || filters.source) && (
            <button
              onClick={() => setFilters({ severity: '', source: '', acknowledged: '' })}
              className="btn btn-ghost"
              style={{ color: 'var(--color-error)' }}
            >
              <X className="w-4 h-4" /> Clear
            </button>
          )}
        </section>
      )}

      {loading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-8 h-8 animate-spin" style={{ color: 'var(--color-primary)' }} />
        </div>
      )}

      {!loading && unackGroups.length > 0 && (
        <section className="space-y-3">
          <h2 className="label-overline flex items-center gap-2" style={{ color: 'var(--color-error)' }}>
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75" style={{ backgroundColor: 'var(--color-error)' }} />
              <span className="relative inline-flex rounded-full h-2 w-2" style={{ backgroundColor: 'var(--color-error)' }} />
            </span>
            Active alerts ({unacknowledged.length})
          </h2>
          {unackGroups.map((group) => (
            <AlertGroupCard
              key={group.rule_name}
              group={group}
              expanded={expandedGroups.has(group.rule_name)}
              onToggle={() => toggleGroup(group.rule_name)}
              acknowledging={acknowledging}
              onAcknowledge={handleAcknowledge}
              onOpenDetail={handleAlertClick}
            />
          ))}
        </section>
      )}

      {!loading && ackGroups.length > 0 && (
        <section className="space-y-3">
          <h2 className="label-overline" style={{ color: 'var(--color-muted)' }}>
            Acknowledged ({acknowledged.length})
          </h2>
          {ackGroups.map((group) => (
            <AlertGroupCard
              key={group.rule_name}
              group={group}
              expanded={expandedGroups.has(group.rule_name)}
              onToggle={() => toggleGroup(group.rule_name)}
              acknowledging={acknowledging}
              onAcknowledge={handleAcknowledge}
              onOpenDetail={handleAlertClick}
              dimmed
            />
          ))}
        </section>
      )}

      {!loading && triggeredAlerts.length === 0 && (
        <section className="card text-center py-12">
          <BellRing className="w-12 h-12 mx-auto mb-3" style={{ color: 'var(--color-hairline)' }} />
          <h3 className="font-display text-lg mb-1" style={{ color: 'var(--color-ink)' }}>No triggered alerts</h3>
          <p className="text-sm max-w-sm mx-auto" style={{ color: 'var(--color-muted)' }}>
            Your alert rules are active and monitoring. Any triggered alerts will appear here.
          </p>
        </section>
      )}
    </div>
  )
}

// Renders one rule_name as a collapsed card with a count suffix, plus an
// expandable list of individual alerts underneath. The header toggles the
// expand state; each child alert keeps its own Acknowledge button and
// detail-view chevron so the existing per-alert interactions are preserved.
function AlertGroupCard({
  group, expanded, onToggle, acknowledging, onAcknowledge, onOpenDetail, dimmed,
}) {
  const sevNum = severityBucket(group.severity)
  return (
    <article
      className={clsx('card', dimmed && 'opacity-75')}
      style={{ borderLeft: `4px solid ${severityColor(sevNum)}` }}
    >
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-start justify-between gap-4 text-left"
        aria-expanded={expanded}
      >
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-3 mb-2">
            <AlertTriangle className="w-4 h-4" style={{ color: severityColor(sevNum) }} />
            <h3 className="font-medium" style={{ color: 'var(--color-ink)' }}>{group.rule_name}</h3>
            <span
              className="inline-flex items-center justify-center min-w-[22px] h-5 px-2 text-xs font-semibold rounded-full"
              style={{ backgroundColor: 'var(--color-primary)', color: 'var(--color-on-primary)' }}
            >
              ({group.alerts.length})
            </span>
            <span className={`badge-pill badge-${sevNum}`}>{sevNum.toUpperCase()}</span>
            <span className="text-xs" style={{ color: 'var(--color-muted)' }}>
              {group.totalEvents.toLocaleString()} total events
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <div className="flex items-center gap-2">
              <Clock className="w-4 h-4" style={{ color: 'var(--color-muted)' }} />
              <span style={{ color: 'var(--color-body)' }}>
                {group.lastSeen ? new Date(group.lastSeen).toLocaleString() : '-'}
              </span>
            </div>
            {group.alerts[0]?.source && (
              <span className="badge-pill capitalize">{group.alerts[0].source}</span>
            )}
            {group.alerts[0]?.tenant && (
              <span className="badge-pill">{group.alerts[0].tenant}</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs hidden sm:inline" style={{ color: 'var(--color-muted)' }}>
            {expanded ? 'Collapse' : 'Expand'}
          </span>
          {expanded
            ? <ChevronUp className="w-5 h-5" style={{ color: 'var(--color-muted)' }} />
            : <ChevronDown className="w-5 h-5" style={{ color: 'var(--color-muted)' }} />}
        </div>
      </button>

      {expanded && (
        <ul className="mt-4 pt-4 space-y-2 border-t" style={{ borderColor: 'var(--color-hairline)' }}>
          {group.alerts.map((alert) => (
            <li
              key={alert.id}
              className="flex items-center justify-between gap-4 px-3 py-2 rounded-md"
              style={{ backgroundColor: 'var(--color-surface-soft)' }}
            >
              <div className="flex items-center gap-3 min-w-0 flex-1">
                <MapPin className="w-4 h-4 shrink-0" style={{ color: 'var(--color-muted)' }} />
                <span className="font-mono text-sm" style={{ color: 'var(--color-ink)' }}>{alert.src_ip}</span>
                <span className={`badge-pill badge-${severityBucket(alert.severity)} text-xs`}>
                  {severityBucket(alert.severity).toUpperCase()}
                </span>
                <span className="text-sm" style={{ color: 'var(--color-body)' }}>
                  <span className="font-medium">{alert.count}</span>
                  <span style={{ color: 'var(--color-muted)' }}> events</span>
                </span>
                <span className="text-xs hidden md:inline" style={{ color: 'var(--color-muted)' }}>
                  {alert.last_seen ? new Date(alert.last_seen).toLocaleString() : '-'}
                </span>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {!alert.acknowledged && (
                  <button
                    onClick={(e) => { e.stopPropagation(); onAcknowledge(alert.id) }}
                    disabled={acknowledging === alert.id}
                    className="btn btn-secondary px-2 py-1"
                    aria-label="Acknowledge"
                    title="Acknowledge"
                  >
                    {acknowledging === alert.id
                      ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      : <Check className="w-3.5 h-3.5" />}
                  </button>
                )}
                <button
                  onClick={(e) => { e.stopPropagation(); onOpenDetail(alert) }}
                  className="p-1 rounded-md hover:bg-[color:var(--color-surface-card)]"
                  aria-label="Open detail"
                  title="Open detail"
                >
                  <ChevronRight className="w-4 h-4" style={{ color: 'var(--color-muted)' }} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </article>
  )
}

export default AlertTriggered
