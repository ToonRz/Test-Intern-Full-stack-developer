import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import LogSearch from '../pages/LogSearch'
import * as api from '../services/api'

vi.mock('../services/api', () => ({
  logs: {
    query: vi.fn(),
    facets: vi.fn(),
    stats: vi.fn(),
    ingest: vi.fn(),
    ingestBatch: vi.fn(),
  },
}))

const renderLogSearch = () => {
  render(
    <BrowserRouter>
      <LogSearch />
    </BrowserRouter>
  )
}

const triggerFor = (label) => screen.getByRole('button', { name: new RegExp(`^${label}`, 'i') })

// Open the popover for `triggerLabel`, then click the checkbox whose row text
// matches the regex. We always pick the *last* <ul> in the DOM so multiple
// popovers can coexist.
const pick = async (triggerLabel, regex) => {
  fireEvent.click(triggerFor(triggerLabel))
  const lists = await screen.findAllByRole('list')
  const popover = lists[lists.length - 1]
  const items = within(popover).getAllByRole('listitem')
  const match = items.find((li) => regex.test(li.textContent))
  fireEvent.click(within(match).getByRole('checkbox'))
}

describe('LogSearch Page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.logs.query.mockResolvedValue({ data: { logs: [], total: 0, pages: 0 } })
    api.logs.facets.mockResolvedValue({
      data: {
        sources: ['firewall', 'aws'],
        event_types: ['LogonFailed', 'session_started'],
        actions: ['deny', 'login'],
        tenants: ['demoA'],
      },
    })
  })

  it('renders log search page', async () => {
    renderLogSearch()
    expect(screen.getByText(/log search/i)).toBeTruthy()
  })

  it('shows search input and filter popovers', async () => {
    renderLogSearch()
    expect(screen.getByPlaceholderText(/full-text search/i)).toBeTruthy()
    await waitFor(() => {
      expect(triggerFor('Source')).toBeTruthy()
      expect(triggerFor('Severity')).toBeTruthy()
      expect(triggerFor('Event type')).toBeTruthy()
      expect(triggerFor('Action')).toBeTruthy()
    })
  })

  it('displays logs when loaded', async () => {
    api.logs.query.mockResolvedValue({
      data: {
        logs: [
          {
            id: 1,
            '@timestamp': '2025-08-20T12:00:00Z',
            source: 'api',
            event_type: 'session_started',
            action: 'login',
            severity: 5,
            src_ip: '1.2.3.4',
            user: 'alice',
            raw: { msg: 'test' },
          },
        ],
        total: 1,
        pages: 1,
      },
    })

    renderLogSearch()

    await waitFor(() => {
      expect(screen.getByText(/session_started/)).toBeTruthy()
      expect(screen.getByText(/1\.2\.3\.4/i)).toBeTruthy()
    })
  })

  it('debounces and re-queries when search input changes', async () => {
    const queryMock = api.logs.query
    renderLogSearch()

    await waitFor(() => expect(queryMock).toHaveBeenCalled())
    const initialCalls = queryMock.mock.calls.length

    const searchInput = screen.getByPlaceholderText(/full-text search/i)
    fireEvent.change(searchInput, { target: { value: 'error' } })

    await new Promise((r) => setTimeout(r, 400))

    expect(queryMock.mock.calls.length).toBeGreaterThan(initialCalls)
  })

  it('shows empty state when no logs', async () => {
    renderLogSearch()

    await waitFor(() => {
      expect(screen.getByText(/no logs/i)).toBeTruthy()
    })
  })

  it('toggles a checkbox inside a filter popover and re-queries', async () => {
    const queryMock = api.logs.query
    renderLogSearch()

    await waitFor(() => expect(queryMock).toHaveBeenCalled())
    const callsBefore = queryMock.mock.calls.length

    await pick('Source', /firewall/i)

    await waitFor(() => {
      expect(queryMock.mock.calls.length).toBeGreaterThan(callsBefore)
    })

    const params = queryMock.mock.calls[queryMock.mock.calls.length - 1][0]
    expect(params.source).toEqual(['firewall'])
  })

  it('combines multiple checkbox filters', async () => {
    const queryMock = api.logs.query
    renderLogSearch()
    await waitFor(() => expect(queryMock).toHaveBeenCalled())

    await pick('Source', /firewall/i)
    await pick('Severity', /critical/i)
    await pick('Action', /deny/i)

    await waitFor(() => {
      const params = queryMock.mock.calls[queryMock.mock.calls.length - 1][0]
      expect(params.source).toEqual(['firewall'])
      expect(params.severity).toEqual(['critical'])
      expect(params.action).toEqual(['deny'])
    })
  })

  it('drops stale responses so the latest filter wins', async () => {
    // Simulate a slow in-flight request that resolves AFTER a fresher one.
    // Without the token guard, the older "all logs" payload would overwrite
    // the newer filtered result and the user would think the filter didn't apply.
    let resolveStale
    const stale = new Promise((resolve) => { resolveStale = resolve })
    const fresh = Promise.resolve({
      data: { logs: [{ id: 99, source: 'firewall', event_type: 'filtered_match' }], total: 1, pages: 1 },
    })
    api.logs.query
      .mockImplementationOnce(() => stale)
      .mockImplementationOnce(() => fresh)

    renderLogSearch()
    // Initial loadLogs is in flight (stale). Now click a filter to fire a fresh request.
    await waitFor(() => expect(api.logs.query).toHaveBeenCalledTimes(1))

    await pick('Source', /firewall/i)

    // Fresh response resolves first.
    await waitFor(() => expect(screen.queryByText('filtered_match')).toBeTruthy())

    // Late stale response arrives — the token guard must drop it on the floor.
    resolveStale({ data: { logs: [{ id: 1, source: 'api', event_type: 'stale_payload' }], total: 50, pages: 5 } })

    // Give microtasks a chance; the stale log must not appear.
    await new Promise((r) => setTimeout(r, 50))
    expect(screen.queryByText('stale_payload')).toBeNull()
    expect(screen.queryByText('filtered_match')).toBeTruthy()
  })
})