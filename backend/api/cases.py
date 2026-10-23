"""Case read APIs, the agent run trigger and demo controls. Shapes follow contracts/openapi.yaml."""
from collections import Counter

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from adapters.sim import SimAdminClient, SimHttp
from agent.orchestrator import AGENT, parse_iso, run_case
from api.auth import require_roles
from api.db import (
    Action, AuditEvent, BatchDecision, Case, Extraction, Notice, NoticeAttachment, Supplier, TraceResult, User,
    Verification, get_db, new_id,
)
from api.errors import ApiError
from api.notices import case_summary
from rules import AFFECTED

router = APIRouter(prefix="/api")

CASE_READERS = ("qa_specialist", "qa_manager", "shipping_supervisor")
QA = ("qa_specialist", "qa_manager")


def get_case(db: Session, case_id: str) -> Case:
    case = db.get(Case, case_id)
    if case is None:
        raise ApiError(404, "NOT_FOUND", f"Case {case_id} not found", {"case_id": case_id})
    return case


def action_out(a: Action) -> dict:
    return {"id": a.id, "case_id": a.case_id, "type": a.type, "target": a.target, "status": a.status,
            "requires_approval": a.requires_approval, "requested_by": a.requested_by,
            "idempotency_key": a.idempotency_key, "created_at": a.created_at, "result": a.result}


def case_actions(db: Session, case_id: str) -> list[Action]:
    return list(db.scalars(select(Action).where(Action.case_id == case_id).order_by(Action.created_at, Action.id)))


def case_decisions(db: Session, case_id: str) -> list[BatchDecision]:
    return list(db.scalars(select(BatchDecision).where(BatchDecision.case_id == case_id).order_by(BatchDecision.batch_id)))


def case_detail(db: Session, case: Case) -> dict:
    notice = db.get(Notice, case.notice_id)
    supplier = db.get(Supplier, notice.supplier_id) if notice.supplier_id else None
    ex = db.get(Extraction, case.id)
    tr = db.get(TraceResult, case.id)
    return {
        "id": case.id,
        "status": case.status,
        "duplicate_of": case.duplicate_of,
        "opened_at": case.opened_at,
        "contained_at": case.contained_at,
        "uncertainty_flags": case.uncertainty_flags,
        "notice": {"id": notice.id, "supplier": supplier.name if supplier else (notice.from_address or "Unverified sender"),
                   "subject": notice.subject, "received_at": notice.received_at},
        "extraction": None if ex is None else {
            "fields": ex.fields, "allergens_added": ex.allergens_added, "uncertainty_flags": ex.uncertainty_flags,
            "model": ex.model, "prompt_version": ex.prompt_version},
        "trace": None if tr is None else {"material_lots": tr.material_lot_ids, "batches": tr.graph["batches"], "gaps": tr.gaps},
        "batch_decisions": [{"batch_id": d.batch_id, "decision": d.decision, "rule_ids": d.rule_ids,
                             "uncertainty_flags": d.uncertainty_flags, "rationale": d.rationale} for d in case_decisions(db, case.id)],
        "actions": [action_out(a) for a in case_actions(db, case.id)],
        "metrics": {"agent_started_at": case.agent_started_at, "elapsed_seconds": case.elapsed_seconds},
    }


def batch_outcome(decision: BatchDecision, actions: list[Action]) -> tuple[str, bool]:
    if decision.decision not in AFFECTED:
        return "NO_ACTION", True
    mine = [a for a in actions if a.target.get("batch_id") == decision.batch_id]
    statuses = {a.status for a in mine}
    if decision.decision in ("SHIPPED_ESCALATE", "UNCERTAIN_ESCALATE"):
        return "ESCALATED", False
    if statuses & {"VERIFY_FAILED", "ESCALATED", "REJECTED"}:
        return "VERIFY_FAILED" if "VERIFY_FAILED" in statuses else "ESCALATED", False
    holds_ok = all(a.status == "VERIFIED" for a in mine if a.type == "PLACE_HOLD")
    removals = [a for a in mine if a.type == "REMOVE_FROM_SHIPMENT"]
    if mine and all(a.status == "VERIFIED" for a in mine):
        return ("REMOVED_FROM_SHIPMENT" if removals else "HELD"), True
    if holds_ok and any(a.status == "PENDING_APPROVAL" for a in removals):
        return "HELD_PENDING_REMOVAL", False
    return "IN_PROGRESS", False


@router.get("/cases")
def list_cases(user: User = Depends(require_roles(*CASE_READERS)), db: Session = Depends(get_db)):
    cases = db.scalars(select(Case).order_by(Case.opened_at.desc(), Case.id))
    return [case_summary(db, c) for c in cases]


@router.get("/cases/{case_id}")
def get_case_detail(case_id: str, user: User = Depends(require_roles(*CASE_READERS)), db: Session = Depends(get_db)):
    return case_detail(db, get_case(db, case_id))


@router.get("/cases/{case_id}/timeline")
def timeline(case_id: str, user: User = Depends(require_roles(*CASE_READERS)), db: Session = Depends(get_db)):
    get_case(db, case_id)
    events = db.scalars(select(AuditEvent).where(AuditEvent.case_id == case_id).order_by(AuditEvent.id))
    return [{"id": f"e_{e.id:06d}", "case_id": e.case_id, "ts": e.ts, "actor": e.actor, "kind": e.kind,
             "payload": e.payload, "prev_hash": e.prev_hash, "hash": e.hash} for e in events]


@router.get("/cases/{case_id}/report")
def report(case_id: str, user: User = Depends(require_roles(*QA)), db: Session = Depends(get_db)):
    case = get_case(db, case_id)
    actions = case_actions(db, case_id)
    batches = []
    for d in case_decisions(db, case_id):
        final_state, verified = batch_outcome(d, actions)
        batches.append({"batch_id": d.batch_id, "decision": d.decision, "final_state": final_state, "verified": verified})
    to_contained = ((parse_iso(case.contained_at) - parse_iso(case.opened_at)).total_seconds() if case.contained_at else None)
    return {"case_id": case.id, "status": case.status, "opened_at": case.opened_at, "contained_at": case.contained_at,
            "batches": batches, "action_counts": dict(Counter(a.status for a in actions)),
            "metrics": {"agent_started_at": case.agent_started_at, "elapsed_seconds": case.elapsed_seconds,
                        "seconds_to_contained": to_contained}}


@router.post("/cases/{case_id}/run")
def run(case_id: str, request: Request, background: BackgroundTasks,
        user: User = Depends(require_roles(*QA)), db: Session = Depends(get_db)):
    get_case(db, case_id)
    run_id = new_id("r")
    claimed = db.execute(update(Case).where(Case.id == case_id, Case.running_run_id.is_(None))
                         .values(running_run_id=run_id)).rowcount
    db.commit()
    if not claimed:
        raise ApiError(409, "CONFLICT", "The agent is already running on this case", {"case_id": case_id})
    app = request.app
    background.add_task(run_case, app.state.sessionmaker, app.state.sim_http, app.state.settings, case_id, run_id, user.username)
    return JSONResponse({"case_id": case_id, "run_id": run_id}, status_code=202)


# ---- demo controls (admin, DEMO_MODE only)

class DemoFaults(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wms_silent_hold_failure: bool


def sim_admin(request: Request) -> SimAdminClient:
    if not request.app.state.settings.demo_mode:
        raise ApiError(404, "NOT_FOUND", "Demo controls are disabled (DEMO_MODE=false)")
    return SimAdminClient(SimHttp(request.app.state.sim_http, request.app.state.settings.sim_api_key))


@router.put("/demo/faults")
def demo_faults(body: DemoFaults, request: Request, user: User = Depends(require_roles("admin"))):
    sim_admin(request).set_faults(body.wms_silent_hold_failure)
    return {"ok": True}


@router.post("/demo/reset")
def demo_reset(request: Request, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    sim_admin(request).reset()
    for model in (Verification, Action, BatchDecision, TraceResult, Extraction, AuditEvent, Case, NoticeAttachment, Notice):
        db.execute(delete(model))
    db.commit()
    return {"ok": True}
