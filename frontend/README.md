# Jarvis portal

React + TypeScript + Vite UI served in production from `frontend/dist` by the FastAPI app on port 4780.

## Scripts

```powershell
npm install
npm run dev      # http://127.0.0.1:5173, proxies /api to :4780
npm run build    # tsc -b && vite build → dist/
npm run lint     # oxlint
```

The backend must be running for `npm run dev` (see [docs/DEVELOPMENT.md](../docs/DEVELOPMENT.md)). Pages live in `src/pages/`; routes and nav are in `src/App.tsx`; authenticated `fetch` is `src/api.ts`.
