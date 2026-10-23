# LabelLock frontend

React, Vite, TypeScript, React Router, and Vitest. Run from this directory:

```bash
npm ci
cp .env.example .env
npm run dev
```

The example environment uses contract fixtures and an in-memory mock API. Open the Vite URL, select any of the six demo users, and sign in with `demo`. To use the backend, set `VITE_USE_MOCKS=false` and set `VITE_API_BASE_URL` to its `/api` base URL. The frontend sends the role token as a bearer token.

```bash
npm test
npm run build
```

The mock inbox and notices reset when the page reloads. The QA inbox mock includes the contract's example notices. All demo data is synthetic.
