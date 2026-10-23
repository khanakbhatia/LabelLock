"""Typed HTTP clients for the simulated systems, used only by the agent.

- 5 s timeout; GETs retry once on transport errors or 5xx; writes never retry here.
- Writes carry Idempotency-Key = hash(case_id, action_type, target).
- Any failure surfaces as ApiError 502 UPSTREAM_FAILED.
- Least privilege: hold writes are direct; release and remove-line need an APPROVED action in
  the app DB, else a POLICY_VIOLATION is audited and raised.
"""
import hashlib
import json
from typing import Callable, TypedDict

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db import Action, Approval, User
from api.errors import ApiError
from audit import append_event

TIMEOUT_SECONDS = 5.0
OnCall = Callable[[dict], None]


def idempotency_key(case_id: str, action_type: str, target: dict) -> str:
    raw = json.dumps([case_id, action_type, target], sort_keys=True, separators=(",", ":"))
    return "idem_" + hashlib.sha256(raw.encode()).hexdigest()[:32]


class MaterialLot(TypedDict):
    lot_id: str
    material_id: str
    material_name: str
    supplier_id: str
    received_at: str


class ProductRow(TypedDict):
    sku: str
    name: str
    label_version: str


class GenealogyRow(TypedDict):
    batch_id: str
    sku: str
    material_lot_id: str


class BatchRow(TypedDict):
    batch_id: str
    sku: str
    product: str | None
    produced_at: str
    material_lot_ids: list[str]


class InventoryRow(TypedDict):
    batch_id: str
    location: str
    qty: int
    status: str


class HoldRow(TypedDict):
    hold_id: str
    batch_id: str
    location: str
    reason: str
    case_ref: str
    status: str
    created_at: str
    released_at: str | None


class ShipmentRow(TypedDict):
    shipment_id: str
    destination: str
    departs_at: str
    status: str
    lines: list[dict]


class LabelRow(TypedDict):
    sku: str
    version: str
    ingredient_statement: str
    contains: list[str]
    may_contain: list[str]
    claims: list[str]


class SimHttp:
    def __init__(self, client: httpx.Client, sim_key: str, on_call: OnCall | None = None):
        self.client, self.sim_key, self.on_call = client, sim_key, on_call or (lambda _: None)

    def request(self, system: str, method: str, path: str, *, params: dict | None = None, body: dict | None = None,
                idem: str | None = None, allow_404: bool = False):
        headers = {"X-Sim-Key": self.sim_key} | ({"Idempotency-Key": idem} if idem else {})
        attempts = 2 if method == "GET" else 1
        response, error = None, None
        for attempt in range(1, attempts + 1):
            try:
                response = self.client.request(method, path, params=params, json=body, headers=headers, timeout=TIMEOUT_SECONDS)
                error = f"HTTP {response.status_code}" if response.status_code >= 500 else None
            except httpx.HTTPError as e:
                response, error = None, f"{type(e).__name__}: {e}"
            if error is None:
                break
        status = response.status_code if response is not None else None
        self.on_call({"system": system, "method": method, "path": path, "params": params, "body": body,
                      "status": status, "attempts": attempt, "error": error})
        if error is not None:
            raise ApiError(502, "UPSTREAM_FAILED", f"{system} {method} {path} failed: {error}",
                           {"system": system, "path": path})
        if status == 404 and allow_404:
            return None
        if status >= 400:
            raise ApiError(502, "UPSTREAM_FAILED", f"{system} {method} {path} rejected with HTTP {status}",
                           {"system": system, "path": path, "upstream": response.json() if response.content else None})
        return response.json()


class ErpClient:
    def __init__(self, http: SimHttp):
        self.http = http

    def material_lot(self, lot_id: str) -> MaterialLot | None:
        return self.http.request("erp", "GET", f"/sim/erp/material-lots/{lot_id}", allow_404=True)

    def products(self, material_id: str) -> list[ProductRow]:
        return self.http.request("erp", "GET", "/sim/erp/products", params={"material_id": material_id})

    def genealogy(self, material_lot_id: str) -> list[GenealogyRow]:
        return self.http.request("erp", "GET", "/sim/erp/genealogy", params={"material_lot_id": material_lot_id})

    def batch(self, batch_id: str) -> BatchRow | None:
        return self.http.request("erp", "GET", f"/sim/erp/batches/{batch_id}", allow_404=True)


class LabelsClient:
    def __init__(self, http: SimHttp):
        self.http = http

    def label(self, sku: str) -> LabelRow | None:
        return self.http.request("labels", "GET", f"/sim/labels/{sku}", allow_404=True)


class ApprovalGate:
    """Checks the app DB before a restricted sim write. Violations are audited, then raised."""

    def __init__(self, db: Session, case_id: str, actor: str):
        self.db, self.case_id, self.actor = db, case_id, actor

    def require_approved(self, action_id: str, action_type: str) -> Action:
        action = self.db.get(Action, action_id)
        problem = None
        if action is None:
            problem = f"action {action_id} does not exist"
        elif action.type != action_type:
            problem = f"action {action_id} is {action.type}, not {action_type}"
        elif action.status != "APPROVED":
            problem = f"action {action_id} is {action.status}, not APPROVED"
        elif not self.db.scalar(select(Approval.id).join(User, User.username == Approval.decided_by).where(
                Approval.action_id == action_id, Approval.decision == "APPROVED", User.role == "qa_manager")):
            problem = f"action {action_id} has no recorded approval by a qa_manager"
        if problem:
            details = {"action_id": action_id, "action_type": action_type, "reason": problem}
            append_event(self.db, action.case_id if action else self.case_id, self.actor, "POLICY_VIOLATION", details)
            self.db.commit()
            raise ApiError(409, "POLICY_VIOLATION", f"{action_type} needs an approved action: {problem}", details)
        return action


class WmsClient:
    def __init__(self, http: SimHttp, gate: ApprovalGate):
        self.http, self.gate = http, gate

    def inventory(self, batch_id: str) -> list[InventoryRow]:
        return self.http.request("wms", "GET", "/sim/wms/inventory", params={"batch_id": batch_id})

    def holds(self, batch_id: str) -> list[HoldRow]:
        return self.http.request("wms", "GET", "/sim/wms/holds", params={"batch_id": batch_id})

    def shipments(self, batch_id: str) -> list[ShipmentRow]:
        return self.http.request("wms", "GET", "/sim/wms/shipments", params={"batch_id": batch_id})

    def shipment(self, shipment_id: str) -> ShipmentRow | None:
        return self.http.request("wms", "GET", f"/sim/wms/shipments/{shipment_id}", allow_404=True)

    # -- direct writes (no approval)

    def place_hold(self, case_id: str, batch_id: str, location: str, reason: str) -> HoldRow:
        target = {"batch_id": batch_id, "location": location}
        return self.http.request("wms", "POST", "/sim/wms/holds", idem=idempotency_key(case_id, "PLACE_HOLD", target),
                                 body=target | {"reason": reason, "case_ref": case_id})

    # -- restricted writes: parameters come from the approved action, never from the caller

    def release_hold(self, action_id: str) -> list[HoldRow]:
        """Release every hold listed in the approved action's target (hold_ids, comma-separated)."""
        action = self.gate.require_approved(action_id, "RELEASE_HOLD")
        return [self.http.request("wms", "POST", f"/sim/wms/holds/{hold_id}/release", idem=f"{action.idempotency_key}:{hold_id}")
                for hold_id in action.target["hold_ids"].split(",")]

    def remove_line(self, action_id: str) -> dict:
        action = self.gate.require_approved(action_id, "REMOVE_FROM_SHIPMENT")
        return self.http.request("wms", "POST", f"/sim/wms/shipments/{action.target['shipment_id']}/remove-line",
                                 body={"batch_id": action.target["batch_id"]}, idem=action.idempotency_key)


class SimAdminClient:
    def __init__(self, http: SimHttp):
        self.http = http

    def set_faults(self, wms_silent_hold_failure: bool) -> dict:
        return self.http.request("admin", "PUT", "/sim/admin/faults", body={"wms_silent_hold_failure": wms_silent_hold_failure})

    def reset(self) -> dict:
        return self.http.request("admin", "POST", "/sim/admin/reset")
