import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import Dashboard from '../pages/Dashboard'
import * as api from '../services/api'

vi.mock('../services/api', () => ({
  logs: {
    stats: vi.fn(),
  },
  alerts: {
    triggered: vi.fn(),
  },
}))

const renderDashboard = () => {
  render(
    <BrowserRouter>
      <Dashboard />
    </BrowserRouter>
  )
}

const emptyStats = {
  total: 0,
  timeline: [],
  top_src_ips: [],
  top_users: [],
  top_event_types: [],
  by_source: [],
  by_severity: [],
}

describe('Dashboard Page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.logs.stats.mockResolvedValue({ data: emptyStats })
    api.alerts.triggered.mockResolvedValue({ data: { alerts: [] } })
  })

  it('renders dashboard title', async () => {
    renderDashboard()
    expect(screen.getByText(/dashboard/i)).toBeTruthy()
  })

  it('shows stat cards after loading', async () => {
    api.logs.stats.mockResolvedValue({
      data: {
        ...emptyStats,
        total: 42,
        by_source: [{ key: 'api', count: 10 }],
        by_severity: [{ key: '5', count: 3 }],
      },
    })
    renderDashboard()

    await vi.waitFor(() => {
      expect(screen.getByText(/total logs/i)).toBeTruthy()
      expect(screen.getByText('Critical')).toBeTruthy()
      expect(screen.getByText('Sources')).toBeTruthy()
    })
  })

  it('renders chart sections', async () => {
    renderDashboard()

    await vi.waitFor(() => {
      expect(screen.getByText(/top source ips/i)).toBeTruthy()
      expect(screen.getByText(/top users/i)).toBeTruthy()
      expect(screen.getByText(/top event types/i)).toBeTruthy()
      expect(screen.getByText(/by source/i)).toBeTruthy()
    })
  })
})
