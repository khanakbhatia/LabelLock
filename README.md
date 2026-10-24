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
- **Final commit SHA:** `18f9d323acbfd3d2ba4a5c94127dbbd8532ca083` (merge of PR #20 on `main`: the submitted version, including the 2:08 demo scripts; later commits only update this line)
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

Requirements: Python 3.13 and Node 22. The commands below are for Git Bash or another POSIX shell. They use Windows venv paths; on macOS/Linux use `.venv/bin/python`. In PowerShell, `VAR=value command` does not work: set the variable first (`$env:DEMO_MODE = 'true'`), then run the command.

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

The simulated systems are served by the same process under `/sim`. They load a small stub dataset from `backend/tests/fixtures/seed_stub/`: 9 products, 17 batches and 3 shipments, including lot VL-2291, its four batches and shipment L-552. The larger Northfield dataset (`/data/seed`) is not in the repository yet, so the backend logs `Seed dir … missing … using stub` at startup. That warning is expected.

The backend's adapters call `/sim` over HTTP at `SIM_BASE_URL` (default `http://localhost:8000`). If you run the backend on another port, set `SIM_BASE_URL` to the same port. Otherwise the adapters reach whatever else is listening on 8000.

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

**Settings → Demo controls** (as `admin`) resets the data. It also turns on a test fault where the warehouse silently fails to apply holds, and LabelLock catches it.

Reset before every scenario. Holds are shared physical state in the simulated warehouse, so a second case on the same lot finds the stock already HELD by the first and verifies it as held. Also check that the fault switch is off unless the scenario needs it. The full curl walkthrough is in [docs/demo-m1.md](docs/demo-m1.md).

### 5. Gmail extension (optional)

Build it with `cd frontend && npm run build:panel`, then load `extension/dist` unpacked in Chrome. Gmail sign-in needs the Chrome extension OAuth client ID in `extension/manifest.json` and `EXTENSION_ORIGIN` in `.env`. See [extension/README.md](extension/README.md) and the manual test in [docs/extension-manual-test.md](docs/extension-manual-test.md).

## Tests and evaluation

```bash
cd backend && .venv/Scripts/python -m pytest          # backend unit and API tests
cd backend && .venv/Scripts/python -m scenarios.runner # 20-scenario eval through the real API (replayed extractions, free)
cd frontend && npm test                                 # frontend tests
```

The 20 scenarios in `backend/scenarios/` are written by the team and run against the stub dataset. Their extractions were recorded once from live Claude and are replayed, so the eval is deterministic and free. Its scores measure accuracy on our own test set, not performance in the field. Agent timings come only from the live recording runs.

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
