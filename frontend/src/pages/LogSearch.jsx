import { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import {
  Search, Filter, ChevronDown, ChevronUp, X, Loader2, RefreshCw,
  Check, SlidersHorizontal,
} from 'lucide-react'
import { logs } from '../services/api'
import clsx from 'clsx'
import { severityBucket } from './Dashboard'

// Default options — fall back when the /logs/facets endpoint has no values yet
// (empty DB) so the filter UI still works.
const DEFAULT_SOURCES = ['firewall', 'crowdstrike', 'aws', 'm365', 'ad', 'api', 'network']
const DEFAULT_ACTIONS = ['allow', 'deny', 'create', 'delete', 'login', 'logout', 'alert']

const SEVERITY_OPTIONS = [
  { value: 'critical', label: 'Critical', hint: '9–10' },
  { value: 'high', label: 'High', hint: '7–8' },
  { value: 'medium', label: 'Medium', hint: '4–6' },
  { value: 'low', label: 'Low', hint: '0–3' },
]

const TIME_RANGES = [
  { key: '', label: 'Any time' },
  { key: '1h', label: 'Last hour', hours: 1 },
  { key: '24h', label: 'Last 24h', hours: 24 },
  { key: '7d', label: 'Last 7 days', hours: 24 * 7 },
]

/* ──────────────────────────────────────────────────────────────────────────
   Checkbox filter popover

   Renders a button labeled "Source (2)" that, when clicked, opens a small
   panel of checkboxes. Clicking outside the panel closes it. We attach the
   listener manually instead of importing a headless-ui-style library so the
   bundle stays small.

   The panel positions itself under the trigger; if it would overflow the
   viewport we flip to the left side. This keeps everything inside the
   1200px content column without horizontal scrolling.
   ────────────────────────────────────────────────────────────────────────── */
function FilterPopover({ label, options, selected, onChange, buttonHint, renderOption }) {
  const [open, setOpen] = useState(false)
  const wrapperRef = useRef(null)
  const triggerRef = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const onDocClick = (e) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) {
        setOpen(false)
      }
    }
    const onEsc = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onEsc)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onEsc)
    }
  }, [open])

  const toggle = (val) => {
    if (selected.includes(val)) onChange(selected.filter((v) => v !== val))
    else onChange([...selected, val])
  }

  const count = selected.length

  return (
    <div className="relative shrink-0" ref={wrapperRef}>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={clsx(
          'flex items-center gap-2 h-10 px-3 rounded-md text-sm border transition-colors',
          count > 0 ? 'border-[color:var(--color-primary)] bg-[color:var(--color-surface-soft)]' : 'border-[color:var(--color-hairline)] bg-[color:var(--color-canvas)]',
        )}
        style={{ color: 'var(--color-ink)' }}
      >
        <span className="text-xs font-medium uppercase tracking-wider" style={{ color: 'var(--color-muted)' }}>
          {label}
        </span>
        {count > 0 ? (
          <span
            className="inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 text-xs font-semibold rounded-full"
            style={{ backgroundColor: 'var(--color-primary)', color: 'var(--color-on-primary)' }}
          >
            {count}
          </span>
        ) : buttonHint ? (
          <span className="text-xs" style={{ color: 'var(--color-muted-soft)' }}>{buttonHint}</span>
        ) : null}
        <ChevronDown className={clsx('w-3.5 h-3.5 transition-transform', open && 'rotate-180')} />
      </button>

      {open && (
        <div
          className="absolute z-30 mt-1 min-w-[200px] max-w-[280px] rounded-md border shadow-lg p-2"
          style={{
            top: '100%',
            left: 0,
            backgroundColor: 'var(--color-canvas)',
            borderColor: 'var(--color-hairline)',
          }}
        >
          {options.length === 0 ? (
            <p className="text-xs px-2 py-3" style={{ color: 'var(--color-muted)' }}>
              No options yet — ingest some logs first.
            </p>
          ) : (
            <ul className="max-h-[260px] overflow-y-auto">
              {options.map((opt) => {
                const value = typeof opt === 'string' ? opt : opt.value
                const labelText = typeof opt === 'string' ? opt : opt.label
                const hint = typeof opt === 'object' ? opt.hint : null
                const checked = selected.includes(value)
                return (
                  <li key={value}>
                    <label className="flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer hover:bg-[color:var(--color-surface-soft)]">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggle(value)}
                        className="w-4 h-4 accent-[color:var(--color-primary)] cursor-pointer"
                      />
                      <span className="flex-1 text-sm capitalize" style={{ color: 'var(--color-ink)' }}>
                        {renderOption ? renderOption(opt) : labelText}
                      </span>
                      {hint && (
                        <span className="text-xs" style={{ color: 'var(--color-muted-soft)' }}>{hint}</span>
                      )}
                    </label>
                  </li>
                )
              })}
            </ul>
          )}
          {count > 0 && (
            <div className="flex justify-end pt-2 mt-1 border-t" style={{ borderColor: 'var(--color-hairline)' }}>
              <button
                type="button"
                onClick={() => onChange([])}
                className="text-xs"
                style={{ color: 'var(--color-error)' }}
              >
                Clear
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/* ──────────────────────────────────────────────────────────────────────────
   Selected-chip strip

   Shows every active filter value as a removable chip so users can audit
   what's applied at a glance and peel things off one at a time.
   ────────────────────────────────────────────────────────────────────────── */
function ActiveChips({ chips, onRemove, onClearAll }) {
  if (chips.length === 0) return null
  return (
    <div className="flex flex-wrap items-center gap-2 pt-2 border-t" style={{ borderColor: 'var(--color-hairline)' }}>
      <span className="text-xs uppercase tracking-wider" style={{ color: 'var(--color-muted)' }}>
        Active
      </span>
      {chips.map((chip) => (
        <button
          key={`${chip.group}:${chip.value}`}
          type="button"
          onClick={() => onRemove(chip)}
          className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium"
          style={{ backgroundColor: 'var(--color-surface-soft)', color: 'var(--color-ink)' }}
        >
          <span style={{ color: 'var(--color-muted)' }}>{chip.group}:</span>
          <span>{chip.label}</span>
          <X className="w-3 h-3" style={{ color: 'var(--color-muted)' }} />
        </button>
      ))}
      <button
        type="button"
        onClick={onClearAll}
        className="text-xs"
        style={{ color: 'var(--color-error)' }}
      >
        Clear all
      </button>
    </div>
  )
}

function LogSearch() {
  const [logData, setLogData] = useState([])
  const [total, setTotal] = useState(0)
  const [pages, setPages] = useState(0)
  const [page, setPage] = useState(1)
  const [facets, setFacets] = useState({
    sources: DEFAULT_SOURCES,
    event_types: [],
    actions: DEFAULT_ACTIONS,
    tenants: [],
  })
  const [filters, setFilters] = useState({
    tenant: [],
    source: [],
    event_type: [],
    action: [],
    severity: [],
    q: '',
    range: '',
  })
  const [loading, setLoading] = useState(false)
  const [expandedRow, setExpandedRow] = useState(null)
  const size = 50
  const debounceRef = useRef(null)
  // Monotonic token incremented on every loadLogs; stale responses are dropped
  // so a slow page-N request can't overwrite a fresher filtered page-1 result.
  const loadTokenRef = useRef(0)

  // ── Fetch facets once on mount so the checkbox lists reflect real data.
  useEffect(() => {
    let cancelled = false
    logs.facets()
      .then((res) => {
        if (cancelled) return
        const f = res.data || {}
        setFacets({
          sources: f.sources?.length ? f.sources : DEFAULT_SOURCES,
          event_types: f.event_types || [],
          actions: f.actions?.length ? f.actions : DEFAULT_ACTIONS,
          tenants: f.tenants || [],
        })
      })
      .catch((err) => console.error('Load facets error:', err))
    return () => { cancelled = true }
  }, [])

  // ── Re-query whenever filters or page changes. Debounce only the free-text
  // search so typing in `q` doesn't fire on every keystroke; structural
  // filter changes fire immediately.
  useEffect(() => {
    setPage(1)
    setExpandedRow(null)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      loadLogs(1)
    }, 300)
    return () => clearTimeout(debounceRef.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters])

  useEffect(() => {
    if (page > 1) loadLogs(page)
    setExpandedRow(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page])

  const buildParams = useCallback((targetPage) => {
    const params = { page: targetPage, size }
    if (filters.q) params.q = filters.q
    if (filters.tenant.length) params.tenant = filters.tenant
    if (filters.source.length) params.source = filters.source
    if (filters.event_type.length) params.event_type = filters.event_type
    if (filters.action.length) params.action = filters.action
    if (filters.severity.length) params.severity = filters.severity
    if (filters.range) {
      const r = TIME_RANGES.find((t) => t.key === filters.range)
      if (r?.hours) {
        const end = new Date()
        const start = new Date(end.getTime() - r.hours * 3600 * 1000)
        params.start = start.toISOString()
        params.end = end.toISOString()
      }
    }
    return params
  }, [filters, size])

  const loadLogs = async (targetPage = page) => {
    const token = ++loadTokenRef.current
    setLoading(true)
    try {
      const params = buildParams(targetPage)
      const res = await logs.query(params)
      if (token !== loadTokenRef.current) return
      setLogData(res.data.logs || [])
      setTotal(res.data.total || 0)
      setPages(res.data.pages || 0)
    } catch (err) {
      if (token !== loadTokenRef.current) return
      console.error('Load logs error:', err)
    } finally {
      if (token === loadTokenRef.current) setLoading(false)
    }
  }

  const setFilterGroup = (key, value) => {
    setFilters((prev) => ({ ...prev, [key]: value }))
  }

  const removeChip = (chip) => {
    setFilters((prev) => ({
      ...prev,
      [chip.group]: prev[chip.group].filter((v) => v !== chip.value),
    }))
  }

  const clearAll = () =>
    setFilters({ tenant: [], source: [], event_type: [], action: [], severity: [], q: '', range: '' })

  // Build the chip strip from the current filter state.
  const chips = useMemo(() => {
    const out = []
    filters.source.forEach((v) => out.push({ group: 'source', value: v, label: v }))
    filters.event_type.forEach((v) => out.push({ group: 'event_type', value: v, label: v }))
    filters.action.forEach((v) => out.push({ group: 'action', value: v, label: v }))
    filters.severity.forEach((v) => {
      const opt = SEVERITY_OPTIONS.find((o) => o.value === v)
      out.push({ group: 'severity', value: v, label: opt ? opt.label : v })
    })
    filters.tenant.forEach((v) => out.push({ group: 'tenant', value: v, label: v }))
    if (filters.range) {
      const r = TIME_RANGES.find((t) => t.key === filters.range)
      if (r) out.push({ group: 'range', value: r.key, label: r.label })
    }
    return out
  }, [filters])

  const hasActiveFilters =
    filters.source.length || filters.event_type.length || filters.action.length ||
    filters.severity.length || filters.tenant.length || filters.range || filters.q

  const facetSources = facets.sources
  const facetEventTypes = facets.event_types
  const facetActions = facets.actions

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl" style={{ color: 'var(--color-ink)' }}>Log Search</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--color-muted)' }}>
            {total.toLocaleString()} logs found
          </p>
        </div>
        <button onClick={() => loadLogs(page)} disabled={loading} className="btn btn-secondary">
          <RefreshCw className={clsx('w-4 h-4', loading && 'animate-spin')} />
          Refresh
        </button>
      </header>

      {/* ── Filter section ─────────────────────────────────────────────── */}
      <section className="card space-y-4">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5" style={{ color: 'var(--color-muted)' }} />
          <input
            type="text"
            placeholder="Full-text search across all logs…"
            value={filters.q}
            onChange={(e) => setFilters((prev) => ({ ...prev, q: e.target.value }))}
            className="input pl-10"
          />
          {filters.q && (
            <button
              onClick={() => setFilters((prev) => ({ ...prev, q: '' }))}
              className="absolute right-3 top-1/2 -translate-y-1/2"
              style={{ color: 'var(--color-muted)' }}
              aria-label="Clear search"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-2 mr-1" style={{ color: 'var(--color-muted)' }}>
            <SlidersHorizontal className="w-4 h-4" />
            <span className="text-xs font-medium uppercase tracking-wider">Filters</span>
          </div>

          <FilterPopover
            label="Source"
            options={facetSources}
            selected={filters.source}
            onChange={(v) => setFilterGroup('source', v)}
          />

          <FilterPopover
            label="Severity"
            options={SEVERITY_OPTIONS}
            selected={filters.severity}
            onChange={(v) => setFilterGroup('severity', v)}
          />

          <FilterPopover
            label="Event type"
            options={facetEventTypes}
            selected={filters.event_type}
            onChange={(v) => setFilterGroup('event_type', v)}
            buttonHint={facetEventTypes.length ? 'Any' : 'No data'}
          />

          <FilterPopover
            label="Action"
            options={facetActions}
            selected={filters.action}
            onChange={(v) => setFilterGroup('action', v)}
          />

          {facets.tenants.length > 0 && (
            <FilterPopover
              label="Tenant"
              options={facets.tenants}
              selected={filters.tenant}
              onChange={(v) => setFilterGroup('tenant', v)}
            />
          )}

          <div className="shrink-0">
            <label className="sr-only">Time range</label>
            <select
              value={filters.range}
              onChange={(e) => setFilterGroup('range', e.target.value)}
              className="input h-10"
              style={{ width: 'auto', minWidth: '140px' }}
            >
              {TIME_RANGES.map((r) => (
                <option key={r.key} value={r.key}>{r.label}</option>
              ))}
            </select>
          </div>
        </div>

        <ActiveChips chips={chips} onRemove={removeChip} onClearAll={clearAll} />
      </section>

      {/* ── Results table ──────────────────────────────────────────────── */}
      <section className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: '1px solid var(--color-hairline)' }}>
                <th className="w-10"></th>
                <th className="text-left px-3 py-2 label-overline">Timestamp</th>
                <th className="text-left px-3 py-2 label-overline">Source</th>
                <th className="text-left px-3 py-2 label-overline">Event</th>
                <th className="text-left px-3 py-2 label-overline">Severity</th>
                <th className="text-left px-3 py-2 label-overline">Action</th>
                <th className="text-left px-3 py-2 label-overline">Source IP</th>
                <th className="text-left px-3 py-2 label-overline">User</th>
                <th className="text-left px-3 py-2 label-overline">Host</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={9} className="text-center py-12">
                    <div className="flex flex-col items-center gap-2">
                      <Loader2 className="w-6 h-6 animate-spin" style={{ color: 'var(--color-primary)' }} />
                      <p className="text-sm" style={{ color: 'var(--color-muted)' }}>Searching logs…</p>
                    </div>
                  </td>
                </tr>
              ) : logData.length === 0 ? (
                <tr>
                  <td colSpan={9} className="text-center py-12">
                    <Search className="w-8 h-8 mx-auto" style={{ color: 'var(--color-hairline)' }} />
                    <p className="text-sm mt-2" style={{ color: 'var(--color-muted)' }}>
                      {hasActiveFilters
                        ? 'No logs match your filter combination'
                        : 'No logs yet — ingest some from the samples directory.'}
                    </p>
                  </td>
                </tr>
              ) : (
                logData.map((log) => {
                  const bucket = severityBucket(log.severity)
                  return (
                    <tr key={log.id} className="border-b" style={{ borderColor: 'var(--color-hairline-soft)' }}>
                      <td
                        className="text-center cursor-pointer px-2"
                        onClick={() => setExpandedRow(expandedRow === log.id ? null : log.id)}
                      >
                        {expandedRow === log.id ? (
                          <ChevronUp className="w-4 h-4 inline" style={{ color: 'var(--color-muted)' }} />
                        ) : (
                          <ChevronDown className="w-4 h-4 inline" style={{ color: 'var(--color-muted)' }} />
                        )}
                      </td>
                      <td className="font-mono text-xs px-3 py-2" style={{ color: 'var(--color-body)' }}>
                        {log['@timestamp'] ? new Date(log['@timestamp']).toLocaleString() : '-'}
                      </td>
                      <td className="px-3 py-2">
                        <span className="badge-pill capitalize">{log.source || '-'}</span>
                      </td>
                      <td className="px-3 py-2 font-medium" style={{ color: 'var(--color-ink)' }}>
                        {log.event_type || '-'}
                      </td>
                      <td className="px-3 py-2">
                        <span className={`badge-pill badge-${bucket}`}>{bucket.toUpperCase()} {log.severity ?? ''}</span>
                      </td>
                      <td className="px-3 py-2 text-xs capitalize" style={{ color: 'var(--color-body)' }}>
                        {log.action || '-'}
                      </td>
                      <td className="font-mono text-xs px-3 py-2" style={{ color: 'var(--color-body)' }}>
                        {log.src_ip || '-'}
                      </td>
                      <td className="text-sm px-3 py-2" style={{ color: 'var(--color-body)' }}>
                        {log.user || '-'}
                      </td>
                      <td className="text-sm px-3 py-2" style={{ color: 'var(--color-body)' }}>
                        {log.host || '-'}
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {pages > 1 && (
          <div className="flex items-center justify-between px-4 py-3" style={{ borderTop: '1px solid var(--color-hairline)' }}>
            <p className="text-xs" style={{ color: 'var(--color-muted)' }}>
              Page {page} of {pages} — {total.toLocaleString()} total
            </p>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                className="btn btn-secondary px-3 py-1.5 text-xs"
              >
                Previous
              </button>
              {Array.from({ length: Math.min(5, pages) }, (_, i) => {
                const offset = Math.min(Math.max(1, page - 2), Math.max(1, pages - 4))
                const p = offset + i
                if (p > pages) return null
                return (
                  <button
                    key={p}
                    onClick={() => setPage(p)}
                    className={clsx('btn px-3 py-1.5 text-xs', page === p ? 'btn-primary' : 'btn-secondary')}
                  >
                    {p}
                  </button>
                )
              })}
              <button
                onClick={() => setPage((p) => Math.min(pages, p + 1))}
                disabled={page === pages}
                className="btn btn-secondary px-3 py-1.5 text-xs"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </section>

      {/* Detail drawer */}
      {expandedRow && (() => {
        const log = logData.find((l) => l.id === expandedRow)
        if (!log) return null
        const fields = [
          ['Tenant', log.tenant],
          ['Source', log.source],
          ['Vendor', log.vendor],
          ['Product', log.product],
          ['Event Type', log.event_type],
          ['Event Subtype', log.event_subtype],
          ['Severity', log.severity],
          ['Action', log.action],
          ['Source IP', log.src_ip],
          ['Dest IP', log.dst_ip],
          ['Source Port', log.src_port],
          ['Dest Port', log.dst_port],
          ['Protocol', log.protocol],
          ['User', log.user],
          ['Host', log.host],
          ['Process', log.process],
          ['URL', log.url],
          ['Status Code', log.status_code],
          ['Rule Name', log.rule_name],
          ['Tags', log._tags?.join(', ')],
          ['Geo Country', log.geo_country],
          ['Geo City', log.geo_city],
          ['RDNS Host', log.rdns_hostname],
        ]
        return (
          <section className="card">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-display text-lg" style={{ color: 'var(--color-ink)' }}>
                Log #{log.id}
              </h3>
              <button onClick={() => setExpandedRow(null)} className="btn btn-ghost">
                <X className="w-3 h-3" /> Close
              </button>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
              {fields.filter(([, v]) => v !== null && v !== undefined && v !== '').map(([k, v]) => (
                <div key={k} className="p-3 rounded-md" style={{ backgroundColor: 'var(--color-surface-soft)' }}>
                  <span className="label-overline block">{k}</span>
                  <span className="text-sm font-medium break-all" style={{ color: 'var(--color-ink)' }}>
                    {String(v)}
                  </span>
                </div>
              ))}
            </div>
            {log.raw && (
              <div className="mt-4">
                <p className="label-overline mb-2">Raw data</p>
                <pre className="code-block text-xs overflow-x-auto">{JSON.stringify(log.raw, null, 2)}</pre>
              </div>
            )}
          </section>
        )
      })()}
    </div>
  )
}

export default LogSearch