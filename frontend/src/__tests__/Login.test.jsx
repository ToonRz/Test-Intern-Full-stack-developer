import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import Login from '../pages/Login'
import * as api from '../services/api'

vi.mock('../services/api', () => ({
  auth: {
    login: vi.fn(),
  },
}))

const renderLogin = (onLogin = vi.fn()) => {
  render(
    <BrowserRouter>
      <Login onLogin={onLogin} />
    </BrowserRouter>
  )
}

describe('Login Page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders login form', () => {
    renderLogin()
    expect(screen.getByPlaceholderText(/username/i)).toBeTruthy()
    // Password input has a placeholder of bullets, not a label; identify by type.
    expect(screen.getByPlaceholderText(/•+/)).toBeTruthy()
    expect(screen.getByRole('button', { name: /sign in/i })).toBeTruthy()
  })

  it('calls onLogin on successful login (cookie handles token storage)', async () => {
    // Low #27: after the HttpOnly cookie migration the browser stores the
    // token in a cookie the SPA cannot read. Login.jsx only needs to know
    // the call succeeded — it calls onLogin() with no args.
    const onLogin = vi.fn()
    api.auth.login.mockResolvedValue({ data: { access_token: 'opaque-to-js' } })

    renderLogin(onLogin)

    fireEvent.change(screen.getByPlaceholderText(/username/i), {
      target: { value: 'admin' },
    })
    fireEvent.change(screen.getByPlaceholderText(/•+/), {
      target: { value: 'admin123' },
    })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))

    await vi.waitFor(() => {
      expect(api.auth.login).toHaveBeenCalledWith('admin', 'admin123')
      expect(onLogin).toHaveBeenCalledWith()
    })
  })

  it('shows error on invalid credentials', async () => {
    const onLogin = vi.fn()
    api.auth.login.mockRejectedValue({ response: { data: { detail: 'Invalid credentials' } } })

    renderLogin(onLogin)

    fireEvent.change(screen.getByPlaceholderText(/username/i), {
      target: { value: 'admin' },
    })
    fireEvent.change(screen.getByPlaceholderText(/•+/), {
      target: { value: 'wrong' },
    })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))

    await vi.waitFor(() => {
      expect(screen.getByText(/invalid credentials/i)).toBeTruthy()
    })
  })

  it('fills demo admin account on click', () => {
    renderLogin()

    // The demo account button is a button with the username text.
    const adminButton = screen.getByRole('button', { name: /admin.*Admin.*Full access/s })
    fireEvent.click(adminButton)

    expect(screen.getByPlaceholderText(/username/i)).toHaveValue('admin')
    expect(screen.getByPlaceholderText(/•+/)).toHaveValue('admin123')
  })
})
