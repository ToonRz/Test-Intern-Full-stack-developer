import { useState, useEffect, useCallback } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, AreaChart, Area,
} from 'recharts'
import { Activity, AlertTriangle, Clock, Shield, TrendingUp, Globe, Zap, Filter } from 'lucide-react'
import { logs, alerts } from '../services/api'

// Severity → CSS class bucket used by every page (severity is integer 0-10).
export function severityBucket(sev) {
  if (sev == null) return 'low'
  if (sev >= 9) return 'critical'
  if (sev >= 7) return 'high'
  if (sev >= 4) return 'medium'
  return 'low'
}

const SOURCE_COLORS = {
  firewall: '#cc785c',
  crowdstrike: '#5db8a6',
  aws: '#e8a55a',
  m365: '#5db872',
  ad: '#a9583e',
  api: '#3d8b7a',
  network: '#8e8b82',
}

const SOURCES = ['firewall', 'crowdstrike', 'aws', 'm365', 'ad', 'api', 'network']
const TIME_RANGES = [
  { key: '1h', label: 'Last hour', hours: 1 },
  { key: '24h', label: 'Last 24h', hours: 24 },
  { key: '7d', label: 'Last 7 days', hours: 24 * 7 },
]

function Dashboard() {
  const [stats, setStats] = useState({
    total: 0,
    timeline: [],
    top_src_ips: [],
    top_users: [],
    top_event_types: [],
    by_source: [],
    by_severity: [],
  })
  const [alertsCount, setAlertsCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [range, setRange] = useState('24h')
  const [source, setSource] = useState('')
  const [tenant, setTenant] = useState('')
  // Low #25: dropdown sourced from /logs/facets so operators can't typo a
  // tenant name and silently get zero results (the old free-text input did
  // exactly that).
  const [tenantOptions, setTenantOptions] = useState([])

  useEffect(() => {
    let cancelled = false
    logs.facets()
      .then((res) => { if (!cancelled) setTenantOptions(res.data?.tenants || []) })
      .catch(() => { if (!cancelled) setTenantOptions([]) })
    return () => { cancelled = true }
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const rangeHours = TIME_RANGES.find((r) => r.key === range)?.hours || 24
      const end = new Date()
      const start = new Date(end.getTime() - rangeHours * 3600 * 1000)
      const params = {
        start: start.toISOString(),
        end: end.toISOString(),
        bucket_minutes: rangeHours > 48 ? 360 : 60,
        top_n: 10,
      }
      if (source) params.source = source
      if (tenant) params.tenant = tenant

      const [statsRes, alertsRes] = await Promise.all([
        logs.stats(params),
        alerts.triggered({ limit: 1000 }),
      ])
      setStats(statsRes.data)
      setAlertsCount((alertsRes.data.alerts || []).length)
    } catch (err) {
      console.error('Dashboard load error:', err)
    } finally {
      setLoading(false)
    }
  }, [range, source, tenant])

  useEffect(() => {
    load()
  }, [load])

  const criticalCount = stats.by_severity
    .filter((s) => parseInt(s.key, 10) >= 8)
    .reduce((sum, s) => sum + s.count, 0)

  const statCards = [
    { label: 'Total Logs', value: stats.total.toLocaleString(), icon: Activity, accent: 'var(--color-primary)' },
    { label: 'Critical', value: criticalCount.toLocaleString(), icon: AlertTriangle, accent: 'var(--color-error)' },
    { label: 'Sources', value: stats.by_source.length.toLocaleString(), icon: Globe, accent: 'var(--color-accent-teal)' },
    { label: 'Alerts', value: alertsCount.toLocaleString(), icon: Shield, accent: 'var(--color-accent-amber)' },
  ]

  return (
    <div className="space-y-8">
      {/* Header */}
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl" style={{ color: 'var(--color-ink)' }}>Dashboard</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--color-muted)' }}>
            Real-time security intelligence overview
          </p>
        </div>
        <button onClick={load} className="btn btn-secondary" disabled={loading}>
          <Zap className="w-4 h-4" />
          Refresh
        </button>
      </header>

      {/* Filter bar */}
      <section className="card flex flex-wrap items-end gap-4">
        <div className="flex items-center gap-2 mr-2" style={{ color: 'var(--color-muted)' }}>
          <Filter className="w-4 h-4" />
          <span className="text-xs uppercase tracking-wider font-medium">Filters</span>
        </div>

        <div className="flex-1 min-w-[160px]">
          <label className="label-overline">Time range</label>
          <div className="inline-flex rounded-md p-1" style={{ backgroundColor: 'var(--color-surface-card)' }}>
            {TIME_RANGES.map((r) => (
              <button
                key={r.key}
                onClick={() => setRange(r.key)}
                className={clsx('px-3 py-1.5 text-sm rounded-md transition-colors', range === r.key && 'category-tab-active')}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex-1 min-w-[160px]">
          <label className="label-overline">Source</label>
          <select className="input" value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="">All sources</option>
            {SOURCES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>

        <div className="flex-1 min-w-[160px]">
          <label className="label-overline">Tenant</label>
          <select className="input" value={tenant} onChange={(e) => setTenant(e.target.value)}>
            <option value="">(all)</option>
            {tenantOptions.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>
      </section>

      {/* Stat cards */}
      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {statCards.map(({ label, value, icon: Icon, accent }) => (
          <div key={label} className="card">
            <div className="flex items-start justify-between">
              <div>
                <p className="label-overline">{label}</p>
                <p className="font-display text-3xl mt-2" style={{ color: 'var(--color-ink)' }}>{value}</p>
              </div>
              <div
                className="w-10 h-10 rounded-lg flex items-center justify-center"
                style={{ backgroundColor: accent + '20', color: accent }}
              >
                <Icon className="w-5 h-5" />
              </div>
            </div>
          </div>
        ))}
      </section>

      {/* Timeline */}
      <section className="card">
        <div className="flex items-center gap-2 mb-4">
          <Clock className="w-4 h-4" style={{ color: 'var(--color-primary)' }} />
          <h2 className="font-display text-lg" style={{ color: 'var(--color-ink)' }}>Activity timeline</h2>
        </div>
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={stats.timeline.map((b) => ({ ...b, time: new Date(b.bucket).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit' }) }))}>
            <defs>
              <linearGradient id="dashTimeline" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--color-primary)" stopOpacity={0.3} />
                <stop offset="100%" stopColor="var(--color-primary)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="var(--color-hairline)" strokeDasharray="3 3" />
            <XAxis dataKey="time" tick={{ fontSize: 11, fill: 'var(--color-muted)' }} />
            <YAxis tick={{ fontSize: 11, fill: 'var(--color-muted)' }} allowDecimals={false} />
            <Tooltip contentStyle={{ background: 'var(--color-surface-dark)', border: 'none', borderRadius: 8, color: 'var(--color-on-dark)', fontSize: 12 }} />
            <Area type="monotone" dataKey="count" stroke="var(--color-primary)" fill="url(#dashTimeline)" strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      </section>

      {/* Charts grid */}
      <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ChartCard title="Top source IPs" icon={Globe} accent="var(--color-primary)">
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={stats.top_src_ips.map((d) => ({ name: d.key, value: d.count }))} layout="vertical" margin={{ left: 16 }}>
              <CartesianGrid stroke="var(--color-hairline)" strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 11, fill: 'var(--color-muted)' }} allowDecimals={false} />
              <YAxis dataKey="name" type="category" tick={{ fontSize: 11, fill: 'var(--color-muted)' }} width={120} />
              <Tooltip contentStyle={{ background: 'var(--color-surface-dark)', border: 'none', borderRadius: 8, color: 'var(--color-on-dark)', fontSize: 12 }} />
              <Bar dataKey="value" fill="var(--color-primary)" radius={[0, 4, 4, 0]} barSize={14} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Top users" icon={TrendingUp} accent="var(--color-accent-teal)">
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={stats.top_users.map((d) => ({ name: d.key, value: d.count }))} layout="vertical" margin={{ left: 16 }}>
              <CartesianGrid stroke="var(--color-hairline)" strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 11, fill: 'var(--color-muted)' }} allowDecimals={false} />
              <YAxis dataKey="name" type="category" tick={{ fontSize: 11, fill: 'var(--color-muted)' }} width={120} />
              <Tooltip contentStyle={{ background: 'var(--color-surface-dark)', border: 'none', borderRadius: 8, color: 'var(--color-on-dark)', fontSize: 12 }} />
              <Bar dataKey="value" fill="var(--color-accent-teal)" radius={[0, 4, 4, 0]} barSize={14} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Top event types" icon={Activity} accent="var(--color-accent-amber)">
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={stats.top_event_types.map((d) => ({ name: d.key, value: d.count }))} layout="vertical" margin={{ left: 16 }}>
              <CartesianGrid stroke="var(--color-hairline)" strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 11, fill: 'var(--color-muted)' }} allowDecimals={false} />
              <YAxis dataKey="name" type="category" tick={{ fontSize: 11, fill: 'var(--color-muted)' }} width={120} />
              <Tooltip contentStyle={{ background: 'var(--color-surface-dark)', border: 'none', borderRadius: 8, color: 'var(--color-on-dark)', fontSize: 12 }} />
              <Bar dataKey="value" fill="var(--color-accent-amber)" radius={[0, 4, 4, 0]} barSize={14} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="By source" icon={Globe} accent="var(--color-accent-teal)">
          <div className="flex items-center gap-6">
            <ResponsiveContainer width={160} height={160}>
              <PieChart>
                <Pie data={stats.by_source} dataKey="count" nameKey="key" innerRadius={45} outerRadius={75} paddingAngle={2}>
                  {stats.by_source.map((s, i) => (
                    <Cell key={i} fill={SOURCE_COLORS[s.key] || 'var(--color-muted)'} />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
            <ul className="flex-1 space-y-2">
              {stats.by_source.slice(0, 6).map((s, i) => (
                <li key={s.key} className="flex items-center justify-between text-sm">
                  <span className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: SOURCE_COLORS[s.key] || 'var(--color-muted)' }} />
                    <span style={{ color: 'var(--color-body)' }}>{s.key}</span>
                  </span>
                  <span className="font-medium" style={{ color: 'var(--color-ink)' }}>{s.count.toLocaleString()}</span>
                </li>
              ))}
              {stats.by_source.length === 0 && <li className="text-sm" style={{ color: 'var(--color-muted)' }}>No data for this range</li>}
            </ul>
          </div>
        </ChartCard>
      </section>
    </div>
  )
}

function ChartCard({ title, icon: Icon, accent, children }) {
  return (
    <div className="card">
      <div className="flex items-center gap-2 mb-4">
        <Icon className="w-4 h-4" style={{ color: accent }} />
        <h2 className="text-sm font-medium" style={{ color: 'var(--color-ink)' }}>{title}</h2>
      </div>
      {children}
    </div>
  )
}

// Inline clsx — avoids adding a dep.
function clsx(...parts) {
  return parts.filter(Boolean).join(' ')
}

export default Dashboard
