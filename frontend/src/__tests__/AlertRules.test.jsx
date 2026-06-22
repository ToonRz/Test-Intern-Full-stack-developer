import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import AlertRules from '../pages/AlertRules'
import * as api from '../services/api'

vi.mock('../services/api', () => ({
  alerts: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
  },
  auth: {
    me: vi.fn(),
  },
  tenants: {
    list: vi.fn(),
  },
}))

const renderPage = () =>
  render(
    <BrowserRouter>
      <AlertRules />
    </BrowserRouter>,
  )

const sampleRules = [
  {
    id: 11, name: 'Brute Force Login Detection',
    description: '5 fails / 5m from same src_ip',
    tenant: '*', event_types: ['LogonFailed'],
    threshold: 5, window_minutes: 5, group_by: 'src_ip',
    action: 'store', webhook_url: '', email_to: '',
    enabled: true,
  },
  {
    id: 22, name: 'Disabled Rule',
    description: '', tenant: 'demoA',
    event_types: ['malware_detected'],
    threshold: 1, window_minutes: 10, group_by: 'src_ip',
    action: 'store', webhook_url: '', email_to: '',
    enabled: false,
  },
]

describe('AlertRules Page — delete flow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.alerts.list.mockResolvedValue({ data: { rules: sampleRules } })
    api.tenants.list.mockResolvedValue({ data: [] })
    api.alerts.delete.mockResolvedValue({ data: { status: 'deleted', id: 11 } })
  })

  it('hides the Delete button when the user is a Viewer', async () => {
    api.auth.me.mockResolvedValue({ data: { role: 'Viewer' } })
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Brute Force Login Detection')).toBeInTheDocument()
    })

    expect(screen.queryByRole('button', { name: 'Edit rule' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete rule' })).not.toBeInTheDocument()
  })

  it('shows Edit + Delete buttons for an Admin', async () => {
    api.auth.me.mockResolvedValue({ data: { role: 'Admin' } })
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Brute Force Login Detection')).toBeInTheDocument()
    })

    expect(screen.getAllByRole('button', { name: 'Edit rule' })).toHaveLength(2)
    expect(screen.getAllByRole('button', { name: 'Delete rule' })).toHaveLength(2)
  })

  it('opens a confirmation modal showing the rule name when Delete is clicked', async () => {
    api.auth.me.mockResolvedValue({ data: { role: 'Admin' } })
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Brute Force Login Detection')).toBeInTheDocument()
    })

    fireEvent.click(screen.getAllByRole('button', { name: 'Delete rule' })[0])

    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('Delete alert rule?')
    expect(dialog).toHaveTextContent('Brute Force Login Detection')
    expect(dialog).toHaveTextContent('Cancel')
    expect(dialog).toHaveTextContent('Delete rule')
  })

  it('closes the modal and does not call the API when Cancel is clicked', async () => {
    api.auth.me.mockResolvedValue({ data: { role: 'Admin' } })
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Brute Force Login Detection')).toBeInTheDocument()
    })

    fireEvent.click(screen.getAllByRole('button', { name: 'Delete rule' })[0])
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }))

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
    expect(api.alerts.delete).not.toHaveBeenCalled()
  })

  it('calls alerts.delete and reloads the list when Delete is confirmed', async () => {
    api.auth.me.mockResolvedValue({ data: { role: 'Admin' } })
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Brute Force Login Detection')).toBeInTheDocument()
    })

    fireEvent.click(screen.getAllByRole('button', { name: 'Delete rule' })[0])
    const dialog = await screen.findByRole('dialog')
    // The confirm button shares the accessible name "Delete rule" with the
    // icon trigger, so scope to within the dialog.
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete rule' }))

    await waitFor(() => {
      expect(api.alerts.delete).toHaveBeenCalledWith(11)
    })
    // The list is reloaded after delete — list() must be called again.
    await waitFor(() => {
      const calls = api.alerts.list.mock.calls.length
      expect(calls).toBeGreaterThanOrEqual(2)
    })
  })

  it('surfaces an API error inside the modal without closing it', async () => {
    api.auth.me.mockResolvedValue({ data: { role: 'Admin' } })
    api.alerts.delete.mockRejectedValueOnce({
      response: { data: { detail: 'Rule not found' } },
    })
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Brute Force Login Detection')).toBeInTheDocument()
    })

    fireEvent.click(screen.getAllByRole('button', { name: 'Delete rule' })[0])
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete rule' }))

    await waitFor(() => {
      expect(dialog).toHaveTextContent('Rule not found')
    })
    // Modal stays open so the user can retry or cancel.
    expect(screen.queryByRole('dialog')).toBeInTheDocument()
  })
})
