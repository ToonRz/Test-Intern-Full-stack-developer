import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import AlertTriggered from '../pages/AlertTriggered'
import * as api from '../services/api'

vi.mock('../services/api', () => ({
  alerts: {
    triggered: vi.fn(),
    detail: vi.fn(),
    acknowledge: vi.fn(),
  },
}))

const renderPage = () =>
  render(
    <BrowserRouter>
      <AlertTriggered />
    </BrowserRouter>,
  )

const sampleAlerts = [
  {
    id: 1, rule_id: 1, rule_name: 'Brute Force Login Detection',
    src_ip: '10.0.0.99', count: 15, unique_count: 1, severity: 'medium',
    first_seen: '2025-08-20T10:00:00Z', last_seen: '2025-08-20T10:00:00Z',
    tenant: 'demoA', source: 'api', event_type: 'app_login_failed',
    acknowledged: false, triggered_at: '2025-08-20T10:00:00Z',
  },
  {
    id: 2, rule_id: 1, rule_name: 'Brute Force Login Detection',
    src_ip: '192.0.2.200', count: 8, unique_count: 1, severity: 'high',
    first_seen: '2025-08-20T11:00:00Z', last_seen: '2025-08-20T11:00:00Z',
    tenant: 'demoA', source: 'ad', event_type: 'LogonFailed',
    acknowledged: false, triggered_at: '2025-08-20T11:00:00Z',
  },
  {
    id: 3, rule_id: 1, rule_name: 'Brute Force Login Detection',
    src_ip: '192.0.2.102', count: 22, unique_count: 1, severity: 'high',
    first_seen: '2025-08-20T12:00:00Z', last_seen: '2025-08-20T12:00:00Z',
    tenant: 'demoB', source: 'api', event_type: 'app_login_failed',
    acknowledged: false, triggered_at: '2025-08-20T12:00:00Z',
  },
  {
    id: 4, rule_id: 2, rule_name: 'Malware Detected',
    src_ip: '10.0.0.50', count: 1, unique_count: 1, severity: 'critical',
    first_seen: '2025-08-20T09:00:00Z', last_seen: '2025-08-20T09:00:00Z',
    tenant: 'demoA', source: 'crowdstrike', event_type: 'malware_detected',
    acknowledged: true, triggered_at: '2025-08-20T09:00:00Z',
  },
]

describe('AlertTriggered Page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.alerts.triggered.mockResolvedValue({ data: { alerts: sampleAlerts, total: 4 } })
    api.alerts.detail.mockResolvedValue({ data: { alert: sampleAlerts[0], logs: [] } })
    api.alerts.acknowledge.mockResolvedValue({ data: { status: 'acknowledged', alert_id: 1 } })
  })

  it('renders the page header', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText(/triggered alerts/i)).toBeTruthy())
  })

  it('groups alerts with the same rule_name into one card with a count', async () => {
    renderPage()
    // 3 alerts share "Brute Force Login Detection" → rendered as one group card.
    await waitFor(() => {
      expect(screen.getAllByText(/Brute Force Login Detection/).length).toBe(1)
      expect(screen.getByText('(3)')).toBeTruthy()
    })
  })

  it('renders the total event count aggregated across the group', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('45 total events')).toBeTruthy())
  })

  it('expands a group to reveal individual alerts and their src_ips', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('(3)')).toBeTruthy())

    // Click the group header (it's a button labelled by the rule name).
    const header = screen.getByRole('button', { name: /Brute Force Login Detection/ })
    fireEvent.click(header)

    await waitFor(() => {
      expect(screen.getByText('10.0.0.99')).toBeTruthy()
      expect(screen.getByText('192.0.2.200')).toBeTruthy()
      expect(screen.getByText('192.0.2.102')).toBeTruthy()
    })
  })

  it('collapses a group back to a single card', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('(3)')).toBeTruthy())

    const header = screen.getByRole('button', { name: /Brute Force Login Detection/ })
    fireEvent.click(header) // expand
    await waitFor(() => expect(screen.getByText('10.0.0.99')).toBeTruthy())

    fireEvent.click(header) // collapse
    await waitFor(() => {
      expect(screen.queryByText('10.0.0.99')).toBeNull()
    })
  })

  it('acknowledges an inner alert and removes it from the active group', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('(3)')).toBeTruthy())

    const header = screen.getByRole('button', { name: /Brute Force Login Detection/ })
    fireEvent.click(header)
    await waitFor(() => expect(screen.getByText('10.0.0.99')).toBeTruthy())

    // Find the row containing 10.0.0.99 and click its Acknowledge button.
    const row = screen.getByText('10.0.0.99').closest('li')
    const ackBtn = within(row).getByTitle('Acknowledge')
    fireEvent.click(ackBtn)

    await waitFor(() => {
      // Count chip drops from (3) to (2).
      expect(screen.getByText('(2)')).toBeTruthy()
    })
  })
})