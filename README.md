# LabelLock

LabelLock turns a supplier's ingredient change notice into checked allergen-label decisions and safe actions in the warehouse.

1. Claude (`claude-opus-5-5`) extracts each field from the email and spec PDF, with its exact quote and source.
2. Deterministic rules decide the allergen impact.
3. LabelLock traces the lot to finished batches and shipments.
4. It places protective holds and re-reads each system to verify that the hold took effect.
5. Restricted actions wait for a QA manager's approval.
6. Every step is written to an audit trail.

Northfield Snacks and its suppliers, products, batches and enterprise systems are fictional. The ERP, WMS and label systems are simulated by us. Their state is real and changes on every action.

## Submission

- **Repository:** https://github.com/khanakbhatia/LabelLock
- **Final commit SHA:** `TO_BE_FILLED_AFTER_FINAL_MERGE` (the commit on `main` that we submit; a later commit that only updates this line does not change the code)
- **Demo video:** act two is recorded from the running product by `demo/`. See [Demo video](#demo-video).

## Repository layout

| Path | What it is |
|---|---|
| `backend/` | FastAPI + SQLAlchemy + SQLite API, the agent (`agent/`), allergen rules (`rules/`, `config/`), adapters to the simulated ERP/WMS/label systems (`adapters/`, `sim/`), audit log, 20-scenario eval suite (`scenarios/`), tests |
| `frontend/` | React + Vite + TypeScript web app: supplier portal, QA inbox, case workspace, approvals, ROI, settings |
| `extension/` | Gmail side panel (Chrome extension), built from `frontend/` |
| `contracts/` | OpenAPI spec, shared enums and example payloads, validated in tests |
| `demo/` | Playwright + ffmpeg scripts that record the demo video from the real app |
| `docs/` | Plan, decision log, manual test scripts |

## Setup

Requirements: Python 3.13, Node 22, Git Bash or any POSIX shell (the commands below use Windows venv paths; on macOS/Linux use `.venv/bin/python`).

### 1. Environment

```bash
cp .env.example .env
```

The backend reads the root `.env`. The defaults run fully offline with `LLM_MODE=mock`, which replays recorded Claude extractions. To call Claude live, set `ANTHROPIC_API_KEY` and `LLM_MODE=live`. Never commit `.env`.

### 2. Backend (port 8000)

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
DEMO_MODE=true .venv/Scripts/python -m uvicorn api.main:create_app --factory --port 8000
```

The simulated systems are served by the same process under `/sim`, seeded with the Northfield demo data (lot VL-2291, four batches, shipment L-552).

### 3. Frontend (port 5173)

```bash
cd frontend
npm ci
cp .env.example .env    # then set VITE_USE_MOCKS=false to use the backend
npm run dev
```

Open http://localhost:5173 and sign in with any demo user. Every password is `demo`.

| User | Role |
|---|---|
| `valley.ingredients` | Supplier: submits change notices |
| `priya.qa` | QA specialist: reviews cases, runs the agent |
| `daniel.qam` | QA manager: approves restricted actions |
| `marco.ship` | Shipping supervisor |
| `admin` | Demo controls: reset data, fault switch |

### 4. Try the golden path

1. As `valley.ingredients`, submit the notice in `backend/tests/fixtures/notices/` (the subject `Lecithin source change from lot VL-2291`, the body from `vl2291_body.txt`, and the PDF `RM-114_spec_rev4.pdf`).
2. As `priya.qa`, open it from the QA inbox and click **Run agent**.
3. As `daniel.qam`, approve the shipment removal under **Approvals**.

**Settings → Demo controls** (as `admin`) resets the data. It also turns on a test fault where the warehouse silently fails to apply holds, and LabelLock catches it. The full curl walkthrough is in [docs/demo-m1.md](docs/demo-m1.md).

### 5. Gmail extension (optional)

The extension needs a Chrome OAuth client ID. See [docs/extension-manual-test.md](docs/extension-manual-test.md).

## Tests and evaluation

```bash
cd backend && .venv/Scripts/python -m pytest          # backend unit and API tests
cd backend && .venv/Scripts/python -m scenarios.runner # 20-scenario eval through the real API (mock mode, free)
cd frontend && npm test                                 # frontend tests
```

Eval results are served at `GET /api/metrics/roi` and on the ROI page. On the ROI page, measured results are shown separately from editable assumptions.

## Demo video

With the backend (`LLM_MODE=live`) and frontend running:

```bash
cd demo
npm ci
npm run demo:record   # records each clip from the real app in Edge
npm run demo:render   # writes demo/output/labellock-act2-{captioned,clean}.mp4, .srt and voiceover-script.md
```

Nothing is mocked. Each clip starts from `/api/demo/reset`, and setup goes through the product API only. The Gmail clip is recorded by hand ([demo/gmail-manual.md](demo/gmail-manual.md)).

## Team

Anvi (backend, agent, evaluation, demo) and Khanak (frontend, extension, ROI).
