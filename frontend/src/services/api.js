import axios from 'axios'

// VITE_API_URL is set by docker-compose (http://backend:8000/api/v1) and falls
// back to a relative path so `npm run dev` outside Docker still hits /api/v1
// (which the vite proxy forwards to localhost:8000).
const API_BASE = import.meta.env.VITE_API_URL || '/api/v1'

// Axios's default array serialization emits `?key[]=a&key[]=b`, which
// FastAPI's `Optional[List[str]] = Query(None)` does not parse — the
// bracket suffix makes FastAPI treat the param as a different name and
// silently drop the filter. Emit repeated params (`?key=a&key=b`) so the
// backend's IN-list filter actually receives the values.
function serializeParams(params) {
  const parts = []
  const append = (key, value) => {
    if (value === null || value === undefined) return
    parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(value)}`)
  }
  Object.entries(params || {}).forEach(([key, value]) => {
    if (Array.isArray(value)) value.forEach((v) => append(key, v))
    else append(key, value)
  })
  return parts.join('&')
}

const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
  timeout: 30000,
  paramsSerializer: serializeParams,
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status
    if (status === 401) {
      localStorage.removeItem('token')
      // Avoid full-page reload loops when already on /login.
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  },
)

export const auth = {
  login: (username, password) => api.post('/auth/login', { username, password }),
  me: () => api.get('/auth/me'),
}

export const logs = {
  query: (params) => api.get('/logs', { params }),
  stats: (params) => api.get('/logs/stats', { params }),
  facets: (params) => api.get('/logs/facets', { params }),
  ingest: (data) => api.post('/ingest', data),
  ingestBatch: (data) => api.post('/ingest/batch', data),
}

export const alerts = {
  list: () => api.get('/alerts'),
  create: (rule) => api.post('/alerts', rule),
  update: (id, rule) => api.put(`/alerts/${id}`, rule),
  delete: (id) => api.delete(`/alerts/${id}`),
  // Both `limit` and arbitrary filter params are forwarded so the existing
  // call sites can keep using one signature.
  triggered: (params = {}) => {
    const { limit = 100, ...rest } = params || {}
    return api.get('/alerts/triggered', { params: { limit, ...rest } })
  },
  detail: (id) => api.get(`/alerts/triggered/${id}`),
  acknowledge: (id) => api.post(`/alerts/${id}/acknowledge`),
}

export const users = {
  list: () => api.get('/users'),
  create: (data) => api.post('/users', data),
  update: (id, data) => api.patch(`/users/${id}`, data),
  delete: (id) => api.delete(`/users/${id}`),
}

export const tenants = {
  list: () => api.get('/tenants'),
  create: (data) => api.post('/tenants', data),
  delete: (id) => api.delete(`/tenants/${id}`),
}

export default api
