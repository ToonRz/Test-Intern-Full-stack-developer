import { describe, it, expect, vi, beforeEach } from 'vitest'

// Stub axios.create before importing the module so we can capture the
// paramsSerializer that was registered. `vi.hoisted` runs before the mock
// factory is evaluated, which is required because vi.mock factories are
// themselves hoisted.
const { captured } = vi.hoisted(() => ({ captured: { current: null } }))

vi.mock('axios', () => ({
  default: {
    create: (config) => {
      captured.current = config
      return {
        interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
        get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn(),
      }
    },
  },
}))

// localStorage is touched by the request interceptor setup.
vi.stubGlobal('localStorage', { getItem: vi.fn(), removeItem: vi.fn() })
// jsdom doesn't provide window.location.pathname in this stub; give a safe value.
Object.defineProperty(window, 'location', {
  value: { pathname: '/', href: '' },
  writable: true,
})

import api, { logs } from '../services/api'

describe('api.js paramsSerializer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('serializes array params as repeated keys (no brackets)', async () => {
    expect(captured.current).toBeTruthy()
    const { paramsSerializer } = captured.current
    expect(typeof paramsSerializer).toBe('function')

    // Multi-checkbox scenario from LogSearch.jsx — this is the bug we hit
    // before: axios default emitted `source[]=a&source[]=b`, which FastAPI's
    // `Optional[List[str]] = Query(None)` silently dropped.
    const result = paramsSerializer({
      source: ['firewall', 'aws'],
      severity: ['critical', 'low'],
      action: ['create'],
      page: 1,
      size: 50,
    })

    expect(result).toContain('source=firewall')
    expect(result).toContain('source=aws')
    expect(result).toContain('severity=critical')
    expect(result).toContain('severity=low')
    expect(result).toContain('action=create')
    expect(result).toContain('page=1')
    expect(result).toContain('size=50')
    // No bracket suffix anywhere — that was the silent-filter-drop bug.
    expect(result).not.toContain('[]')
  })

  it('emits each array value as its own repeated key, not a CSV', () => {
    const result = captured.current.paramsSerializer({ source: ['firewall', 'aws'] })
    // Repeated form (?source=a&source=b) — what FastAPI expects.
    expect(result).toBe('source=firewall&source=aws')
  })

  it('drops null/undefined values', () => {
    const result = captured.current.paramsSerializer({ a: 'x', b: null, c: undefined, d: 'y' })
    expect(result).toBe('a=x&d=y')
  })

  it('handles non-array scalars unchanged', () => {
    const result = captured.current.paramsSerializer({ q: 'hello world', page: 2 })
    expect(result).toMatch(/q=hello(\+|%20)world/)
    expect(result).toContain('page=2')
  })
})

// Touch the imported api module so vitest doesn't tree-shake it out; the
// paramsSerializer test above relies on the axios.create call having run.
describe('api module shape', () => {
  it('exports logs helpers and the default api client', () => {
    expect(typeof logs.query).toBe('function')
    expect(typeof logs.stats).toBe('function')
    expect(typeof logs.facets).toBe('function')
    expect(api).toBeTruthy()
  })
})
