"""The case agent: extract -> trace -> decide -> act -> verify -> report.

Step status lives on the case (`steps`), so a second run resumes instead of repeating work. Actions
are keyed by hash(case_id, type, target), the same key the sim sees, so nothing is ever duplicated.
Every step, rule fired, adapter call and status change is an audit event.
"""
import logging
import re
import time
from collections import Counter
from datetime import datetime

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from adapters.sim import ApprovalGate, ErpClient, LabelsClient, SimHttp, WmsClient, idempotency_key
from agent.extract import check_evidence, pdf_pages, unresolved_critical
from agent.llm import PROMPT_VERSION, get_llm
from api.db import Action, BatchDecision, Case, Extraction, Notice, NoticeAttachment, TraceResult, Verification, new_id, now_iso
from api.errors import ApiError
from api.settings import Settings
from audit import append_event
from rules import AFFECTED, HOLDABLE, SHIPPED_STATUSES, allergens_in, decide_batch

log = logging.getLogger("labellock.agent")

AGENT = "labellock-agent"
STEPS = ("extract", "trace", "decide", "act", "verify", "report")
ALWAYS_RERUN = {"verify", "report"}  # read-only checks plus idempotent retries
KNOWN_LLM_FLAGS = {"LLM_UNCERTAIN"}


def parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class CaseRun:
    def __init__(self, db: Session, case: Case, http_client: httpx.Client, settings: Settings):
        self.db, self.case, self.settings = db, case, settings
        http = SimHttp(http_client, settings.sim_api_key, on_call=lambda s: self.audit("ADAPTER_CALL", s))
        self.erp, self.labels = ErpClient(http), LabelsClient(http)
        self.wms = WmsClient(http, ApprovalGate(db, case.id, AGENT))

    # ---- helpers

    def audit(self, kind: str, payload: dict, actor: str = AGENT) -> None:
        append_event(self.db, self.case.id, actor, kind, payload)

    def set_status(self, status: str, **why) -> None:
        if self.case.status != status:
            self.audit("STATUS_CHANGED", {"from": self.case.status, "to": status, **why})
            self.case.status = status
            if status == "CONTAINED":
                self.case.contained_at = now_iso()

    def set_action_status(self, action: Action, status: str, **details) -> None:
        if action.status != status:
            self.audit("ACTION_STATUS_CHANGED", {"action_id": action.id, "type": action.type, "target": action.target,
                                                 "from": action.status, "to": status, **details})
            action.status = status

    def escalate(self, reason: str, **details) -> bool:
        self.audit("ESCALATED", {"reason": reason, **details})
        return False

    def actions(self, *types: str) -> list[Action]:
        q = select(Action).where(Action.case_id == self.case.id).order_by(Action.created_at, Action.id)
        return [a for a in self.db.scalars(q) if not types or a.type in types]

    def get_or_create_action(self, type_: str, target: dict, *, requires_approval: bool, status: str) -> tuple[Action, bool]:
        key = idempotency_key(self.case.id, type_, target)
        action = self.db.scalar(select(Action).where(Action.idempotency_key == key))
        if action:
            return action, False
        action = Action(id=new_id("a"), case_id=self.case.id, type=type_, target=target, status=status,
                        requires_approval=requires_approval, idempotency_key=key, requested_by=AGENT, created_at=now_iso())
        self.db.add(action)
        self.audit("ACTION_CREATED", {"action_id": action.id, "type": type_, "target": target, "status": status,
                                      "requires_approval": requires_approval})
        return action, True

    # ---- run

    def execute(self, run_id: str, started_by: str) -> None:
        case = self.case
        self.audit("RUN_STARTED", {"run_id": run_id, "resuming": dict(case.steps or {})}, actor=started_by)
        self.t0 = time.monotonic()  # stored timestamps are whole seconds; elapsed needs better
        if case.agent_started_at is None:
            case.agent_started_at = now_iso()
        if case.status == "RECEIVED":
            self.set_status("ANALYZING")
        self.db.commit()
        stopped = any(v == "STOPPED" for v in (case.steps or {}).values())
        for step in STEPS:
            if (stopped and step != "report") or ((case.steps or {}).get(step) == "DONE" and step not in ALWAYS_RERUN):
                continue
            self.audit("STEP_STARTED", {"step": step, "run_id": run_id})
            ok = getattr(self, step)()
            case.steps = {**(case.steps or {}), step: "DONE" if ok else "STOPPED"}
            self.audit("STEP_COMPLETED", {"step": step, "run_id": run_id, "outcome": case.steps[step]})
            self.db.commit()
            stopped = stopped or not ok

    def extract(self) -> bool:
        notice = self.db.get(Notice, self.case.notice_id)
        paths = self.db.scalars(select(NoticeAttachment.path).where(NoticeAttachment.notice_id == notice.id).order_by(NoticeAttachment.id))
        pages = pdf_pages(list(paths))
        llm = get_llm(self.settings.llm_mode)
        raw = llm.extract(content_hash=notice.content_hash, email_text=notice.body, pages=pages)
        fields, downgraded = check_evidence(raw["fields"], notice.body, pages)
        # The LLM may only add flags we know; anything else becomes a generic uncertainty flag.
        flags = sorted({f if f in KNOWN_LLM_FLAGS else "LLM_UNCERTAIN" for f in raw.get("uncertainty_flags", [])})
        if downgraded:
            flags.append("EVIDENCE_MISMATCH")
        critical = unresolved_critical(fields)
        if critical:
            flags.append("CRITICAL_FIELD_UNRESOLVED")
        new_ingredient = fields.get("new_ingredient", {})
        added = allergens_in(new_ingredient.get("value")) if new_ingredient.get("status") == "FOUND" else []

        self.db.merge(Extraction(case_id=self.case.id, fields=fields, uncertainty_flags=flags, model=llm.model,
                                 prompt_version=PROMPT_VERSION,
                                 allergens_added=[{"allergen": a["allergen"], "rule_id": a["rule_id"]} for a in added]))
        statuses = Counter(f.get("status") for f in fields.values())
        self.audit("EXTRACTION_COMPLETED", {"model": llm.model, "prompt_version": PROMPT_VERSION, "found": statuses["FOUND"],
                                            "missing": statuses["MISSING"], "ambiguous": statuses["AMBIGUOUS"],
                                            "evidence_downgraded": downgraded, "uncertainty_flags": flags})
        for a in added:
            self.audit("RULE_FIRED", {"rule_id": a["rule_id"], "allergen": a["allergen"], "term": a["term"], "input": "new_ingredient"})
        if critical:
            return self.escalate("CRITICAL_FIELD_UNRESOLVED", fields=critical)
        return True

    def trace(self) -> bool:
        ex = self.db.get(Extraction, self.case.id)
        lot_id = ex.fields["effective_lot"]["value"].strip()
        gaps, batches, labels, shipment_status = [], [], {}, {}
        lot = self.erp.material_lot(lot_id)
        if lot is None:
            gaps.append({"kind": "LOT_NOT_FOUND", "detail": f"ERP has no material lot {lot_id}"})
        else:
            code = re.search(r"\bRM-\d+\b", ex.fields["material"]["value"] or "")
            if code and code.group() != lot["material_id"]:
                gaps.append({"kind": "MATERIAL_MISMATCH",
                             "detail": f"Notice names {code.group()} but lot {lot_id} is {lot['material_id']}"})
        if not gaps:
            names = {p["sku"]: p["name"] for p in self.erp.products(lot["material_id"])}
            for g in self.erp.genealogy(lot_id):
                sku = g["sku"]
                if sku not in labels:
                    labels[sku] = self.labels.label(sku)
                    if labels[sku] is None:
                        gaps.append({"kind": "LABEL_NOT_FOUND", "detail": f"No label for {sku}"})
                ships = self.wms.shipments(g["batch_id"])
                shipment_status |= {s["shipment_id"]: s["status"] for s in ships}
                batches.append({
                    "batch_id": g["batch_id"], "sku": sku, "product": names.get(sku, sku),
                    "locations": [{"location": r["location"], "qty": r["qty"], "status": r["status"]}
                                  for r in self.wms.inventory(g["batch_id"])],
                    "shipments": [{"shipment_id": s["shipment_id"], "destination": s["destination"], "departs_at": s["departs_at"],
                                   "qty": next(ln["qty"] for ln in s["lines"] if ln["batch_id"] == g["batch_id"])} for s in ships],
                })
        self.db.merge(TraceResult(case_id=self.case.id, material_lot_ids=[lot_id], batch_ids=[b["batch_id"] for b in batches],
                                  graph={"batches": batches, "labels": labels, "shipment_status": shipment_status}, gaps=gaps))
        self.audit("TRACE_COMPLETED", {"material_lots": [lot_id], "batches": [b["batch_id"] for b in batches], "gaps": gaps})
        blocking = [g for g in gaps if g["kind"] in ("LOT_NOT_FOUND", "MATERIAL_MISMATCH")]
        return self.escalate(blocking[0]["kind"], gaps=gaps) if blocking else True

    def decide(self) -> bool:
        ex = self.db.get(Extraction, self.case.id)
        tr = self.db.get(TraceResult, self.case.id)
        uncertain = "LLM_UNCERTAIN" in ex.uncertainty_flags
        self.db.execute(delete(BatchDecision).where(BatchDecision.case_id == self.case.id))
        for b in tr.graph["batches"]:
            ship_state = [{"shipment_id": s["shipment_id"], "status": tr.graph["shipment_status"][s["shipment_id"]], "qty": s["qty"]}
                          for s in b["shipments"]]
            d = decide_batch(tr.graph["labels"].get(b["sku"]), ex.allergens_added, b["locations"], ship_state, uncertain=uncertain)
            self.db.add(BatchDecision(case_id=self.case.id, batch_id=b["batch_id"], decision=d.decision, rule_ids=d.rule_ids,
                                      uncertainty_flags=d.uncertainty_flags, rationale=d.rationale))
            self.audit("RULE_FIRED", {"batch_id": b["batch_id"], "decision": d.decision, "rule_ids": d.rule_ids, "rationale": d.rationale})
        if "SUPPLIER_UNVERIFIED" in self.case.uncertainty_flags:
            return self.escalate("SUPPLIER_UNVERIFIED")
        return True

    def act(self) -> bool:
        tr = self.db.get(TraceResult, self.case.id)
        batches = {b["batch_id"]: b for b in tr.graph["batches"]}
        decisions = self.db.scalars(select(BatchDecision).where(BatchDecision.case_id == self.case.id).order_by(BatchDecision.batch_id))
        for d in decisions:
            if d.decision not in HOLDABLE:
                continue
            batch = batches[d.batch_id]
            for loc in batch["locations"]:
                if loc["qty"] <= 0:
                    continue
                action, _ = self.get_or_create_action("PLACE_HOLD", {"batch_id": d.batch_id, "location": loc["location"]},
                                                      requires_approval=False, status="PROPOSED")
                if action.status == "PROPOSED":
                    self.place_hold(action, reason=f"{d.decision}: {', '.join(d.rule_ids)}")
            for s in batch["shipments"]:
                if tr.graph["shipment_status"][s["shipment_id"]] in SHIPPED_STATUSES:
                    continue
                action, created = self.get_or_create_action("REMOVE_FROM_SHIPMENT", {"batch_id": d.batch_id, "shipment_id": s["shipment_id"]},
                                                            requires_approval=True, status="PENDING_APPROVAL")
                if created:
                    self.audit("APPROVAL_REQUESTED", {"action_id": action.id, "type": action.type, "target": action.target})
            self.db.commit()
        return True

    def place_hold(self, action: Action, reason: str) -> None:
        self.set_action_status(action, "EXECUTING")
        try:
            hold = self.wms.place_hold(self.case.id, action.target["batch_id"], action.target["location"], reason)
        except ApiError as e:
            action.result = {"error": e.code, "message": e.message}
            self.set_action_status(action, "ESCALATED", reason=e.code)
            return
        action.result = {"hold_id": hold["hold_id"]}
        self.set_action_status(action, "EXECUTED", hold_id=hold["hold_id"])

    def verify(self) -> bool:
        tr = self.db.get(TraceResult, self.case.id)
        graph = {**tr.graph, "batches": [dict(b) for b in tr.graph["batches"]]}
        for action in self.actions("PLACE_HOLD"):
            if action.status not in ("EXECUTED", "VERIFY_FAILED"):
                continue
            passed, observed = self.check_hold(action)
            if not passed:
                self.audit("VERIFY_MISMATCH", {"action_id": action.id, "target": action.target, "observed": observed})
                try:
                    self.wms.place_hold(self.case.id, action.target["batch_id"], action.target["location"], "retry after verify mismatch")
                    passed, observed = self.check_hold(action)
                except ApiError as e:
                    observed = {"error": e.code}
            if passed:
                self.set_action_status(action, "VERIFIED")
            else:
                self.set_action_status(action, "VERIFY_FAILED", observed=observed)
                self.audit("ESCALATED", {"reason": "VERIFY_FAILED", "action_id": action.id, "target": action.target})
            for b in graph["batches"]:
                if b["batch_id"] == action.target["batch_id"]:
                    b["locations"] = [loc | ({"status": observed["status"]} if loc["location"] == action.target["location"]
                                             and "status" in observed else {}) for loc in b["locations"]]
        for action in self.actions("REMOVE_FROM_SHIPMENT"):
            if action.status != "EXECUTED":
                continue
            shipment = self.wms.shipment(action.target["shipment_id"])
            lines = [ln["batch_id"] for ln in (shipment or {}).get("lines", [])]
            passed = shipment is not None and action.target["batch_id"] not in lines
            self.record_verification(action, {"batch_id_absent": action.target["batch_id"]}, {"lines": lines}, passed)
            self.set_action_status(action, "VERIFIED" if passed else "VERIFY_FAILED")
        tr.graph = graph
        self.db.commit()
        return True

    def check_hold(self, action: Action) -> tuple[bool, dict]:
        rows = self.wms.inventory(action.target["batch_id"])
        row = next((r for r in rows if r["location"] == action.target["location"]), None)
        passed = row is not None and row["status"] == "HELD"
        observed = {"status": row["status"], "qty": row["qty"]} if row else {"status": None}
        self.record_verification(action, {"status": "HELD"}, observed, passed)
        return passed, observed

    def record_verification(self, action: Action, expected: dict, observed: dict, passed: bool) -> None:
        attempt = len(self.db.scalars(select(Verification.id).where(Verification.action_id == action.id)).all()) + 1
        self.db.add(Verification(action_id=action.id, attempt=attempt, expected=expected, observed=observed,
                                 passed=passed, checked_at=now_iso()))
        self.audit("VERIFICATION", {"action_id": action.id, "attempt": attempt, "expected": expected, "observed": observed, "passed": passed})

    def report(self) -> bool:
        status, reason = self.compute_status()
        self.set_status(status, reason=reason)
        if self.case.elapsed_seconds is None:  # first run that reaches a report: agent time to a decision
            self.case.elapsed_seconds = round(time.monotonic() - self.t0, 3)
        decisions = Counter(self.db.scalars(select(BatchDecision.decision).where(BatchDecision.case_id == self.case.id)))
        self.audit("REPORT_GENERATED", {"status": status, "reason": reason, "decisions": dict(decisions),
                                        "action_counts": dict(Counter(a.status for a in self.actions())),
                                        "elapsed_seconds": self.case.elapsed_seconds})
        return True

    def compute_status(self) -> tuple[str, str]:
        """Never CONTAINED while any affected batch is unverified."""
        if any(v == "STOPPED" for v in (self.case.steps or {}).values()):
            return "ESCALATED", "step stopped"
        decisions = list(self.db.scalars(select(BatchDecision).where(BatchDecision.case_id == self.case.id)))
        affected = [d for d in decisions if d.decision in AFFECTED]
        if not affected:
            return "NO_IMPACT", "no affected batches"
        actions = self.actions()
        if any(d.decision not in HOLDABLE for d in affected):
            return "ESCALATED", "batch needs human decision"
        if any(a.status in ("VERIFY_FAILED", "ESCALATED", "REJECTED") for a in actions):
            return "ESCALATED", "action failed, unverified or rejected"
        if any(a.status in ("PENDING_APPROVAL", "APPROVED", "EXECUTING", "EXECUTED", "PROPOSED") for a in actions):
            waiting = any(a.status == "PENDING_APPROVAL" for a in actions)
            return ("AWAITING_APPROVAL", "restricted actions pending") if waiting else ("ESCALATED", "actions not verified")
        held = {a.target["batch_id"] for a in actions if a.status == "VERIFIED"}
        if all(d.batch_id in held for d in affected):
            return "CONTAINED", "all affected batches verified"
        return "ESCALATED", "affected batch without verified containment"


def run_case(sm: sessionmaker[Session], http_client: httpx.Client, settings: Settings, case_id: str, run_id: str,
             started_by: str) -> None:
    with sm() as db:
        case = db.get(Case, case_id)
        try:
            CaseRun(db, case, http_client, settings).execute(run_id, started_by)
        except Exception as e:  # never leave a case silently half-done
            log.exception("run %s for case %s failed", run_id, case_id)
            db.rollback()
            case = db.get(Case, case_id)
            run = CaseRun(db, case, http_client, settings)
            run.audit("RUN_FAILED", {"run_id": run_id, "error": type(e).__name__, "message": str(e)[:500]})
            run.set_status("ESCALATED", reason="run failed")
        finally:
            case.running_run_id = None
            db.commit()
