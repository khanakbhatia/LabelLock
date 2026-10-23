# M1 demo: golden path and silent hold failure (curl)

Reproduces the M1 vertical slice against a running backend in `LLM_MODE=mock`. Every command here
was run against `uvicorn` on 2026-10-23; the outputs shown are from that run.

## Start the backend

From `backend/` (Git Bash on Windows, or any POSIX shell; `jq` is not needed):

```bash
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt   # macOS/Linux: .venv/bin/python
DEMO_MODE=true .venv/Scripts/python -m uvicorn api.main:create_app --factory --port 8000
```

Defaults: `LLM_MODE=mock`, `SIM_API_KEY=dev-sim-key`, `SIM_BASE_URL=http://localhost:8000`, app DB
`./labellock.db`, sim DB `./sim.db`. With no `/data/seed` yet, the sim loads
`backend/tests/fixtures/seed_stub/` (Northfield stub: VL-2291 lecithin lot, four batches, shipment L-552).

The mock LLM replays a recorded extraction keyed by the notice's content hash, so the notice below must be
sent byte-for-byte from `backend/tests/fixtures/notices/` (that folder is marked `-text` in `.gitattributes`
so Git never rewrites its line endings). Any other notice gets every field MISSING and escalates.

Run the rest from `backend/` in a second shell.

## Shared setup

```bash
API=http://localhost:8000/api
NOTICE=tests/fixtures/notices
json() { python -c "import json,sys; d=json.load(sys.stdin); print(d$1)"; }
login() { curl -s -X POST $API/auth/login -H 'Content-Type: application/json' -d "{\"username\":\"$1\",\"password\":\"demo\"}" | json "['token']"; }
SUPPLIER=$(login valley.ingredients); QA=$(login priya.qa); ADMIN=$(login admin)
submit() { curl -s -X POST $API/notices -H "Authorization: Bearer $SUPPLIER" \
  -F "subject=Lecithin source change from lot VL-2291" -F "body=<$NOTICE/vl2291_body.txt" \
  -F "attachment=@$NOTICE/RM-114_spec_rev4.pdf;type=application/pdf" | json "['case_id']"; }
```

## A. Golden path

```bash
# 0. Clean state, fault switch off
curl -s -X POST $API/demo/reset -H "Authorization: Bearer $ADMIN"
curl -s -X PUT $API/demo/faults -H "Authorization: Bearer $ADMIN" -H 'Content-Type: application/json' -d '{"wms_silent_hold_failure": false}'

# 1. Supplier submits the notice; 2. QA specialist runs the agent (202, finishes in the background)
CASE=$(submit); echo $CASE
curl -s -X POST $API/cases/$CASE/run -H "Authorization: Bearer $QA"
sleep 2

# 3. Status, per-batch decisions, actions
curl -s $API/cases/$CASE -H "Authorization: Bearer $QA" | python -c "import json,sys; d=json.load(sys.stdin); print(d['status']); [print(b['batch_id'], b['decision']) for b in d['batch_decisions']]; [print(a['type'], a['target'], a['status']) for a in d['actions']]"
```

```
AWAITING_APPROVAL
FG-1040 NO_IMPACT
FG-1041 HOLD_RELABEL
FG-1042 HOLD_RELABEL
FG-1043 CLAIM_CONFLICT
REMOVE_FROM_SHIPMENT {'batch_id': 'FG-1043', 'shipment_id': 'L-552'} PENDING_APPROVAL
PLACE_HOLD {'batch_id': 'FG-1042', 'location': 'DC-EAST'} VERIFIED
PLACE_HOLD {'batch_id': 'FG-1043', 'location': 'DC-EAST'} VERIFIED
PLACE_HOLD {'batch_id': 'FG-1042', 'location': 'PLANT-1'} VERIFIED
PLACE_HOLD {'batch_id': 'FG-1041', 'location': 'DC-EAST'} VERIFIED
```

Physical state, read straight from the simulated WMS (sim key, not a user token):

```bash
for B in FG-1040 FG-1041 FG-1042 FG-1043; do curl -s "http://localhost:8000/sim/wms/inventory?batch_id=$B" -H 'X-Sim-Key: dev-sim-key'; echo; done
curl -s http://localhost:8000/sim/wms/shipments/L-552 -H 'X-Sim-Key: dev-sim-key'
```

```
[{"batch_id":"FG-1040","location":"PLANT-1","qty":600,"status":"AVAILABLE"}]     <- Oat Crunch Bar already declares soy
[{"batch_id":"FG-1041","location":"DC-EAST","qty":480,"status":"HELD"}]
[{"batch_id":"FG-1042","location":"DC-EAST","qty":150,"status":"HELD"},{"batch_id":"FG-1042","location":"PLANT-1","qty":200,"status":"HELD"}]
[{"batch_id":"FG-1043","location":"DC-EAST","qty":120,"status":"HELD"}]
{"shipment_id":"L-552",...,"lines":[{"batch_id":"FG-1040","qty":100},{"batch_id":"FG-1043","qty":240}]}   <- removal waits for a QA manager
```

Report, timeline, and the server-side role check:

```bash
curl -s $API/cases/$CASE/report -H "Authorization: Bearer $QA"
curl -s $API/cases/$CASE/timeline -H "Authorization: Bearer $QA" | python -c "import json,sys; [print(e['ts'], e['actor'], e['kind']) for e in json.load(sys.stdin)]"
curl -s -X POST $API/actions/any/approve -H "Authorization: Bearer $QA"     # 403 FORBIDDEN
```

FG-1043's report entry is `"final_state":"HELD_PENDING_REMOVAL","verified":false`, so the case is not
CONTAINED until the shipment removal is approved, executed and verified (approvals land in M2).

## B. Silent hold failure (fault switch)

```bash
curl -s -X POST $API/demo/reset -H "Authorization: Bearer $ADMIN"
curl -s -X PUT $API/demo/faults -H "Authorization: Bearer $ADMIN" -H 'Content-Type: application/json' -d '{"wms_silent_hold_failure": true}'
CASE=$(submit)
curl -s -X POST $API/cases/$CASE/run -H "Authorization: Bearer $QA"
sleep 2
curl -s $API/cases/$CASE -H "Authorization: Bearer $QA" | python -c "import json,sys; d=json.load(sys.stdin); print(d['status'], d['contained_at']); [print(a['type'], a['target'], a['status']) for a in d['actions']]"
curl -s "http://localhost:8000/sim/wms/inventory?batch_id=FG-1042" -H 'X-Sim-Key: dev-sim-key'
```

```
ESCALATED None
PLACE_HOLD {'batch_id': 'FG-1042', 'location': 'PLANT-1'} VERIFIED
REMOVE_FROM_SHIPMENT {'batch_id': 'FG-1043', 'shipment_id': 'L-552'} PENDING_APPROVAL
PLACE_HOLD {'batch_id': 'FG-1042', 'location': 'DC-EAST'} VERIFY_FAILED
PLACE_HOLD {'batch_id': 'FG-1043', 'location': 'DC-EAST'} VERIFY_FAILED
PLACE_HOLD {'batch_id': 'FG-1041', 'location': 'DC-EAST'} VERIFY_FAILED
[{"batch_id":"FG-1042","location":"DC-EAST","qty":150,"status":"AVAILABLE"},{"batch_id":"FG-1042","location":"PLANT-1","qty":200,"status":"HELD"}]
```

The WMS answered "hold placed" every time; the re-read caught it. The agent retried each hold once
(same Idempotency-Key), re-read again, then marked it VERIFY_FAILED and escalated:

```bash
curl -s $API/cases/$CASE/timeline -H "Authorization: Bearer $QA" | python -c "import json,sys; [print(e['ts'], e['kind'], e['payload'].get('to') or e['payload'].get('reason') or '') for e in json.load(sys.stdin) if e['kind'] in ('VERIFY_MISMATCH','ESCALATED','STATUS_CHANGED')]"
```

Clear the fault and run again; verification retries, the holds stick, and the case recovers:

```bash
curl -s -X PUT $API/demo/faults -H "Authorization: Bearer $ADMIN" -H 'Content-Type: application/json' -d '{"wms_silent_hold_failure": false}'
curl -s -X POST $API/cases/$CASE/run -H "Authorization: Bearer $QA"
sleep 2
curl -s $API/cases/$CASE -H "Authorization: Bearer $QA" | json "['status']"    # AWAITING_APPROVAL
```

## Automated equivalents

`backend/tests/test_agent.py` runs both scenarios (plus re-run, crash-resume, approval gate and
escalation cases) in-process: `.venv/Scripts/python -m pytest tests/test_agent.py -v`.
