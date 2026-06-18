# Frontend - Log Management System

React-based dashboard per spec.md section 7.

## Pages

1. **Login** (`/login`) - Authentication with JWT
2. **Dashboard** (`/`) - Top N charts, Timeline, Stats
3. **Log Search** (`/logs`) - Full-text search, filters, pagination
4. **Alert Rules** (`/alerts`) - View/create alert rules (Admin)
5. **Alert Triggered** (`/alerts/triggered`) - Triggered alert list

## Tech Stack

- React 18
- React Router v6
- Recharts (charts)
- Axios (API calls)

## Run

```bash
npm install
npm run dev
```

## API Integration

Connects to `/api/v1/*` endpoints proxied via Vite to backend.
