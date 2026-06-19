# Frontend — Log Management System

React SPA dashboard for the Log Management System

อ้างอิง: `spec.md` §7 (Dashboard pages)

## Tech Stack

- **React 18** + **Vite 5** — dev server + build
- **React Router v6** — client-side routing + auth guards
- **Recharts** — bar/line charts (Top N, Timeline, severity)
- **Axios** — HTTP client with 401 interceptor
- **TailwindCSS** + custom `styles/main.css`
- **Vitest** + **@testing-library/react** — unit/component tests
- **lucide-react** — icons
- **clsx** — conditional classNames

## Pages (`src/pages/`)

| Path | File | Spec §7 | Auth | Description |
|---|---|---|---|---|
| `/login` | `Login.jsx` | Login | — | Login form → POST `/auth/login` (cookie set by server) |
| `/` | `Dashboard.jsx` | Dashboard | any | Top-N (src_ip/user/event_type), Timeline, By Source, By Severity |
| `/logs` | `LogSearch.jsx` | Log Search | any | Filter (tenant/source/event_type/action/severity bucket/time) + pagination + full-text |
| `/alerts` | `AlertRules.jsx` | Alert Rules | Admin | View/Create/Edit alert rules (Viewer เห็นอย่างเดียว) |
| `/alerts/triggered` | `AlertTriggered.jsx` | Alert Triggered | any | Grouped triggered alerts + acknowledge + expand-to-logs |
| `/users` | `UserManagement.jsx` | — | Admin | CRUD users (create/edit/delete + reset password + tenant assignment) |

`UserManagement` เพิ่มเข้ามานอกเหนือจาก spec §7 เพื่อให้ Admin จัดการ users ผ่าน UI ได้ (spec §6 ระบุว่า Admin ต้อง "จัดการ users" — endpoint มีอยู่แล้วใน backend, หน้า UI นี้ wrap endpoint)

## Directory Layout

```
frontend/
├── src/
│   ├── App.jsx                       # Routes + ProtectedRoute + auth probe
│   ├── components/
│   │   └── Layout.jsx                # Nav + header + content shell
│   ├── pages/
│   │   ├── Login.jsx
│   │   ├── Dashboard.jsx
│   │   ├── LogSearch.jsx
│   │   ├── AlertRules.jsx
│   │   ├── AlertTriggered.jsx
│   │   └── UserManagement.jsx
│   ├── services/
│   │   └── api.js                    # Axios instance w/ 401 interceptor + cookie auth
│   ├── styles/
│   │   └── main.css
│   └── __tests__/                    # Vitest specs (Dashboard, Login, setup)
├── index.html
├── vite.config.js                    # Proxy /api → backend (Docker: backend:8000)
├── nginx.conf                        # Container nginx (port 80)
├── tailwind.config.js
├── postcss.config.js
├── vitest.config.js
├── Dockerfile
└── package.json
```

## Authentication Flow

1. App boot → call `GET /auth/me` (cookie ถูกส่งอัตโนมัติ) → ถ้า 200 = logged in, 401 = redirect to `/login`
2. Login form → `POST /auth/login` → server set `HttpOnly` cookie + return `access_token` (เก็บไว้ใน memory เผื่อ CLI/debug) + redirect ไป `/`
3. Logout → `POST /auth/logout` → server clear cookie + client reset state
4. Axios interceptor → ถ้าเจอ 401 → dispatch `auth:logout` event → router navigate ไป `/login`

JWT **ไม่ถูกเก็บใน localStorage** — อยู่ใน HttpOnly cookie เท่านั้น (กัน XSS exfiltrate)

## Routing & Guards

`App.jsx` ใช้ `<ProtectedRoute session={...}>` ครอบทุก protected route:
- `session === null` → ยังโหลดอยู่ (probe `/auth/me`) → render `null`
- `session === false` → redirect ไป `/login`
- `session === true` → render children ภายใน `<Layout>`

## API Integration

`src/services/api.js` export object ต่อ resource:
- `auth.login`, `auth.logout`, `auth.me`
- `logs.query`, `logs.stats`, `logs.facets`
- `alerts.list`, `alerts.create`, `alerts.update`, `alerts.delete`, `alerts.listTriggered`, `alerts.getTriggered`, `alerts.acknowledge`
- `users.list`, `users.create`, `users.update`, `users.delete`
- `tenants.list`, `tenants.create`, `tenants.delete`

Base URL: `/api/v1` (Vite proxy ส่งไป `backend:8000` ใน Docker, `localhost:8000` ตอน dev นอก Docker)
Override ด้วย env `VITE_API_URL` (frontend container) หรือ `VITE_DEV_PROXY` (vite dev server)

## Run

```bash
# ใน Docker (แนะนำ — ใช้ stack เดียวกับ backend)
make up
# → http://localhost:3000 (frontend dev) หรือ https://localhost (ผ่าน nginx)

# Dev นอก Docker
cd frontend
npm install
npm run dev
# → http://localhost:3000 (proxy /api → http://localhost:8000)

# Build production
npm run build
# → dist/

# Tests
npm run test:run     # one-shot
npm test             # watch
```

## Tests

```bash
make test-frontend
# หรือ
cd frontend && npm run test:run
```

Specs:
- `Dashboard.test.jsx`
- `Login.test.jsx`
- `setup.js` (Vitest globals + jest-dom)
