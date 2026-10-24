"""Case read APIs, the agent run trigger and demo controls. Shapes follow contracts/openapi.yaml."""
from collections import Counter
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from adapters.sim import SimAdminClient, SimHttp, idempotency_key
from agent.orchestrator import AGENT, CaseRun, parse_iso, run_case
from api.auth import require_roles
from api.db import (
    Action, Approval, AuditEvent, BatchDecision, Case, Disposition, Extraction, Notice, NoticeAttachment, Supplier,
    TraceResult, User, Verification, get_db, new_id, now_iso,
)
from api.errors import ApiError
from api.notices import case_summary
from audit import append_event, verify_chain
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


@router.get("/cases/{case_id}/audit/verify")
def verify_timeline(case_id: str, user: User = Depends(require_roles(*CASE_READERS)), db: Session = Depends(get_db)):
    get_case(db, case_id)
    return verify_chain(list(db.scalars(select(AuditEvent).where(AuditEvent.case_id == case_id).order_by(AuditEvent.id))))


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


def start_run(db: Session, request: Request, background: BackgroundTasks, case_id: str, started_by: str) -> str | None:
    """Claim the case's run lock and schedule the agent. None if a run already holds the lock."""
    run_id = new_id("r")
    claimed = db.execute(update(Case).where(Case.id == case_id, Case.running_run_id.is_(None))
                         .values(running_run_id=run_id)).rowcount
    db.commit()
    if not claimed:
        return None
    app = request.app
    background.add_task(run_case, app.state.sessionmaker, app.state.sim_http, app.state.settings, case_id, run_id, started_by)
    return run_id


@router.post("/cases/{case_id}/run")
def run(case_id: str, request: Request, background: BackgroundTasks,
        user: User = Depends(require_roles(*QA)), db: Session = Depends(get_db)):
    get_case(db, case_id)
    run_id = start_run(db, request, background, case_id, user.username)
    if run_id is None:
        raise ApiError(409, "CONFLICT", "The agent is already running on this case", {"case_id": case_id})
    return JSONResponse({"case_id": case_id, "run_id": run_id}, status_code=202)


# ---- approvals (restricted actions need a qa_manager)

class ApproveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    comment: str | None = None


class RejectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1)


def pending_action(db: Session, action_id: str) -> Action:
    action = db.get(Action, action_id)
    if action is None:
        raise ApiError(404, "NOT_FOUND", f"Action {action_id} not found", {"action_id": action_id})
    if not action.requires_approval or action.status != "PENDING_APPROVAL":
        raise ApiError(409, "CONFLICT", f"Action {action_id} is {action.status}, not awaiting approval",
                       {"action_id": action_id, "status": action.status})
    return action


def decide(db: Session, action: Action, user: User, decision: str, comment: str | None) -> None:
    db.add(Approval(action_id=action.id, decided_by=user.username, decision=decision, comment=comment, decided_at=now_iso()))
    append_event(db, action.case_id, user.username, "APPROVAL_DECIDED",
                 {"action_id": action.id, "type": action.type, "target": action.target, "decision": decision, "comment": comment})
    append_event(db, action.case_id, user.username, "ACTION_STATUS_CHANGED",
                 {"action_id": action.id, "type": action.type, "target": action.target, "from": action.status, "to": decision})
    action.status = decision
    db.commit()


@router.get("/approvals")
def approvals(status: str | None = None, user: User = Depends(require_roles("qa_manager", "qa_specialist")),
              db: Session = Depends(get_db)):
    q = select(Action).where(Action.requires_approval.is_(True))
    if status:
        q = q.where(Action.status == status)
    return [action_out(a) for a in db.scalars(q.order_by(Action.created_at.desc(), Action.id))]


@router.post("/actions/{action_id}/approve")
def approve(action_id: str, request: Request, background: BackgroundTasks, body: ApproveBody | None = None,
            user: User = Depends(require_roles("qa_manager")), db: Session = Depends(get_db)):
    action = pending_action(db, action_id)
    decide(db, action, user, "APPROVED", body.comment if body else None)
    # Execution is queued: the agent run executes it through the adapter gate, then re-reads the sim.
    if start_run(db, request, background, action.case_id, user.username) is None:
        # ponytail: a run already in progress may have passed its execute step; the next run picks this up.
        append_event(db, action.case_id, AGENT, "EXECUTION_DEFERRED", {"action_id": action.id, "reason": "run in progress"})
        db.commit()
    return action_out(action)


@router.post("/actions/{action_id}/reject")
def reject(action_id: str, body: RejectBody, request: Request,
           user: User = Depends(require_roles("qa_manager")), db: Session = Depends(get_db)):
    action = pending_action(db, action_id)
    decide(db, action, user, "REJECTED", body.reason)
    case = db.get(Case, action.case_id)
    run = CaseRun(db, case, request.app.state.sim_http, request.app.state.settings)
    status, reason = run.compute_status()
    run.set_status(status, reason=reason)
    db.commit()
    return action_out(action)


# ---- dispositions and release requests

RELEASABLE = {"RELEASE_AS_IS", "RELABEL", "REWORK"}  # DESTROY / RETURN_TO_SUPPLIER stock never goes back to AVAILABLE


class DispositionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: str = Field(min_length=1)
    disposition: Literal["RELABEL", "REWORK", "DESTROY", "RETURN_TO_SUPPLIER", "RELEASE_AS_IS"]
    evidence: str = Field(min_length=1)


class ReleaseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


def case_batch(db: Session, case_id: str, batch_id: str) -> BatchDecision:
    d = db.get(BatchDecision, (case_id, batch_id))
    if d is None:
        raise ApiError(404, "NOT_FOUND", f"Batch {batch_id} is not part of case {case_id}", {"case_id": case_id, "batch_id": batch_id})
    return d


def disposition_out(d: Disposition) -> dict:
    return {"id": d.id, "case_id": d.case_id, "batch_id": d.batch_id, "disposition": d.disposition,
            "evidence": d.evidence, "recorded_by": d.recorded_by, "recorded_at": d.recorded_at}


@router.post("/cases/{case_id}/dispositions", status_code=201)
def record_disposition(case_id: str, body: DispositionBody, user: User = Depends(require_roles("qa_manager")),
                       db: Session = Depends(get_db)):
    get_case(db, case_id)
    case_batch(db, case_id, body.batch_id)
    d = Disposition(id=new_id("d"), case_id=case_id, recorded_by=user.username, recorded_at=now_iso(), **body.model_dump())
    db.add(d)
    append_event(db, case_id, user.username, "DISPOSITION_RECORDED", disposition_out(d) | {"id": d.id})
    db.commit()
    return disposition_out(d)


def policy_violation(db: Session, case_id: str, actor: str, message: str, details: dict) -> ApiError:
    append_event(db, case_id, actor, "POLICY_VIOLATION", {"reason": message, **details})
    db.commit()
    return ApiError(409, "POLICY_VIOLATION", message, details)


@router.post("/cases/{case_id}/release-requests", status_code=201)
def request_release(case_id: str, body: ReleaseBody, user: User = Depends(require_roles(*CASE_READERS)),
                    db: Session = Depends(get_db)):
    get_case(db, case_id)
    case_batch(db, case_id, body.batch_id)
    details = {"case_id": case_id, "batch_id": body.batch_id}
    latest = db.scalar(select(Disposition).where(Disposition.case_id == case_id, Disposition.batch_id == body.batch_id)
                       .order_by(Disposition.seq.desc()).limit(1))
    if latest is None:
        raise policy_violation(db, case_id, user.username,
                               f"Cannot release {body.batch_id} without an approved disposition", details)
    if latest.disposition not in RELEASABLE:
        raise policy_violation(db, case_id, user.username,
                               f"Disposition {latest.disposition} for {body.batch_id} does not allow release",
                               details | {"disposition": latest.disposition})
    hold_ids = sorted(a.result["hold_id"] for a in case_actions(db, case_id)
                      if a.type == "PLACE_HOLD" and a.target["batch_id"] == body.batch_id
                      and a.status in ("EXECUTED", "VERIFIED") and (a.result or {}).get("hold_id"))
    if not hold_ids:
        raise ApiError(409, "CONFLICT", f"{body.batch_id} has no hold placed by this case", details)
    target = {"batch_id": body.batch_id, "hold_ids": ",".join(hold_ids)}
    key = idempotency_key(case_id, "RELEASE_HOLD", target)
    if db.scalar(select(Action).where(Action.idempotency_key == key)):
        raise ApiError(409, "CONFLICT", f"Release of {body.batch_id} was already requested", details)
    action = Action(id=new_id("a"), case_id=case_id, type="RELEASE_HOLD", target=target, status="PENDING_APPROVAL",
                    requires_approval=True, idempotency_key=key, requested_by=user.username, created_at=now_iso(),
                    result={"reason": body.reason, "disposition_id": latest.id})
    db.add(action)
    append_event(db, case_id, user.username, "APPROVAL_REQUESTED",
                 {"action_id": action.id, "type": action.type, "target": target, "reason": body.reason, "disposition": latest.disposition})
    case = db.get(Case, case_id)
    if case.status == "CONTAINED":  # a pending restricted action reopens the approval state
        append_event(db, case_id, AGENT, "STATUS_CHANGED", {"from": case.status, "to": "AWAITING_APPROVAL", "reason": "release requested"})
        case.status = "AWAITING_APPROVAL"
    db.commit()
    return action_out(action)


# ---- demo controls (admin, DEMO_MODE only)

class DemoFaults(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wms_silent_hold_failure: bool


def sim_admin(request: Request) -> SimAdminClient:
    if not request.app.state.settings.demo_mode:
        raise ApiError(404, "NOT_FOUND", "Demo controls are disabled (DEMO_MODE=false)")
    return SimAdminClient(SimHttp(request.app.state.sim_http, request.app.state.settings.sim_api_key))


@router.get("/demo/faults")
def demo_faults_state(request: Request, user: User = Depends(require_roles("admin"))):
    return sim_admin(request).get_faults()


@router.put("/demo/faults")
def demo_faults(body: DemoFaults, request: Request, user: User = Depends(require_roles("admin"))):
    sim_admin(request).set_faults(body.wms_silent_hold_failure)
    return {"ok": True}


@router.post("/demo/reset")
def demo_reset(request: Request, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    sim_admin(request).reset()
    # benchmarks are measurements (the ROI baseline), not demo state, so a reset keeps them
    for model in (Approval, Disposition, Verification, Action, BatchDecision, TraceResult, Extraction, AuditEvent, Case, NoticeAttachment, Notice):
        db.execute(delete(model))
    db.commit()
    return {"ok": True}
