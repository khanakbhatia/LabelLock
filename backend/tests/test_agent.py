"""M1 acceptance: golden path, fault path, idempotent re-run, approval gate, escalations. Mock LLM."""
import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from adapters.sim import ApprovalGate, SimHttp, WmsClient
from api.db import Action, AuditEvent, Case, Verification
from api.errors import ApiError
from api.main import create_app
from api.settings import Settings
from sim.db import Hold, Inventory, ShipmentLine
from tests.conftest import assert_matches
from tests.test_auth import assert_error, bearer

NOTICES = Path(__file__).parent / "fixtures" / "notices"
SUBJECT = "Lecithin source change from lot VL-2291"
BODY = (NOTICES / "vl2291_body.txt").read_text(encoding="utf-8")
PDF = (NOTICES / "RM-114_spec_rev4.pdf").read_bytes()


@pytest.fixture
def env(tmp_path):
    settings = Settings(database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}", auth_secret="t",
                        sim_database_url=f"sqlite:///{(tmp_path / 'sim.db').as_posix()}", sim_api_key="k",
                        upload_dir=tmp_path / "uploads", seed_dir=tmp_path / "no-seed", demo_mode=True)
    app = create_app(settings)
    app.state.sim_http = TestClient(app)
    client = TestClient(app)
    tokens = {}

    def token(username):
        if username not in tokens:
            tokens[username] = client.post("/api/auth/login", json={"username": username, "password": "demo"}).json()["token"]
        return bearer(tokens[username])
    return app, client, token


def submit(client, token, subject=SUBJECT, body=BODY) -> str:
    r = client.post("/api/notices", data={"subject": subject, "body": body},
                    files={"attachment": ("RM-114_spec_rev4.pdf", PDF, "application/pdf")}, headers=token("valley.ingredients"))
    assert r.status_code == 201, r.text
    return r.json()["case_id"]


def run(client, token, case_id):
    r = client.post(f"/api/cases/{case_id}/run", headers=token("priya.qa"))
    assert r.status_code == 202, r.text
    assert_matches("RunStarted", r.json())
    return r.json()


def detail(client, token, case_id) -> dict:
    r = client.get(f"/api/cases/{case_id}", headers=token("priya.qa"))
    assert r.status_code == 200, r.text
    assert_matches("CaseDetail", r.json())
    return r.json()


def inventory(app) -> dict:
    with app.state.sim_sessionmaker() as db:
        return {(r.batch_id, r.location): r.status for r in db.scalars(select(Inventory))}


def sim_counts(app) -> dict:
    with app.state.sim_sessionmaker() as db:
        return {"holds": db.scalar(select(func.count()).select_from(Hold)),
                "lines": sorted((ln.shipment_id, ln.batch_id) for ln in db.scalars(select(ShipmentLine)))}


def by(items, key="batch_id"):
    return {i[key]: i for i in items}


def test_golden_path(env):
    app, client, token = env
    case_id = submit(client, token)
    run(client, token, case_id)

    inv = inventory(app)  # read the sim DB directly, not the case record
    assert inv[("FG-1041", "DC-EAST")] == "HELD"
    assert inv[("FG-1043", "DC-EAST")] == "HELD"
    assert inv[("FG-1042", "DC-EAST")] == inv[("FG-1042", "PLANT-1")] == "HELD"
    assert inv[("FG-1040", "PLANT-1")] == "AVAILABLE"   # Oat Crunch Bar label already declares soy
    assert inv[("FG-1039", "DC-EAST")] == "AVAILABLE"   # made from the earlier lot VL-2290
    assert ("L-552", "FG-1043") in sim_counts(app)["lines"]  # removal not executed without approval

    case = detail(client, token, case_id)
    assert case["status"] == "AWAITING_APPROVAL" and case["contained_at"] is None
    decisions = {d["batch_id"]: d["decision"] for d in case["batch_decisions"]}
    assert decisions == {"FG-1040": "NO_IMPACT", "FG-1041": "HOLD_RELABEL", "FG-1042": "HOLD_RELABEL", "FG-1043": "CLAIM_CONFLICT"}
    assert case["extraction"]["allergens_added"] == [{"allergen": "soy", "rule_id": "ALG-SOY-LECITHIN"}]
    assert all(f["evidence"] for f in case["extraction"]["fields"].values() if f["status"] == "FOUND")

    holds = [a for a in case["actions"] if a["type"] == "PLACE_HOLD"]
    assert sorted((a["target"]["batch_id"], a["target"]["location"]) for a in holds) == [
        ("FG-1041", "DC-EAST"), ("FG-1042", "DC-EAST"), ("FG-1042", "PLANT-1"), ("FG-1043", "DC-EAST")]
    assert all(a["status"] == "VERIFIED" and not a["requires_approval"] for a in holds)
    removals = [a for a in case["actions"] if a["type"] == "REMOVE_FROM_SHIPMENT"]
    assert [(a["target"], a["status"], a["requires_approval"]) for a in removals] == [
        ({"batch_id": "FG-1043", "shipment_id": "L-552"}, "PENDING_APPROVAL", True)]
    trace = by(case["trace"]["batches"])
    assert trace["FG-1043"]["shipments"][0]["shipment_id"] == "L-552"
    assert trace["FG-1041"]["locations"] == [{"location": "DC-EAST", "qty": 480, "status": "HELD"}]

    summaries = client.get("/api/cases", headers=token("marco.ship")).json()
    assert_matches("CaseSummary", summaries[0])
    assert summaries[0]["pending_approvals"] == 1

    report = client.get(f"/api/cases/{case_id}/report", headers=token("daniel.qam")).json()
    assert_matches("CaseReport", report)
    assert by(report["batches"])["FG-1043"]["final_state"] == "HELD_PENDING_REMOVAL"
    assert by(report["batches"])["FG-1041"] == {"batch_id": "FG-1041", "decision": "HOLD_RELABEL", "final_state": "HELD", "verified": True}

    events = client.get(f"/api/cases/{case_id}/timeline", headers=token("priya.qa")).json()
    for e in events:
        assert_matches("AuditEvent", e)
    kinds = [e["kind"] for e in events]
    for kind in ("NOTICE_RECEIVED", "RUN_STARTED", "STEP_STARTED", "EXTRACTION_COMPLETED", "RULE_FIRED", "ADAPTER_CALL",
                 "TRACE_COMPLETED", "ACTION_CREATED", "APPROVAL_REQUESTED", "VERIFICATION", "STATUS_CHANGED", "REPORT_GENERATED"):
        assert kind in kinds, kind
    assert all(e["prev_hash"] == prev["hash"] for prev, e in zip(events, events[1:]))  # hash chain intact
    assert [e["payload"]["to"] for e in events if e["kind"] == "STATUS_CHANGED"] == ["ANALYZING", "AWAITING_APPROVAL"]


def test_audit_chain_verifies_and_detects_tampering(env):
    app, client, token = env
    case_id = submit(client, token)
    run(client, token, case_id)
    url = f"/api/cases/{case_id}/audit/verify"
    ok = client.get(url, headers=token("marco.ship")).json()
    assert_matches("AuditVerification", ok)
    assert ok["valid"] and ok["events"] > 10 and ok["first_invalid_event_id"] is None
    assert_error(client.get(url, headers=token("valley.ingredients")), 403, "FORBIDDEN")

    with app.state.sessionmaker() as db:
        event = db.scalars(select(AuditEvent).where(AuditEvent.case_id == case_id).order_by(AuditEvent.id)).all()[3]
        event.payload = {**event.payload, "edited": True}
        db.commit()
        tampered = f"e_{event.id:06d}"
    bad = client.get(url, headers=token("priya.qa")).json()
    assert bad == {"valid": False, "events": ok["events"], "first_invalid_event_id": tampered}


def test_fault_switch_ends_escalated_never_contained(env):
    app, client, token = env
    assert client.put("/api/demo/faults", json={"wms_silent_hold_failure": True}, headers=token("admin")).json() == {"ok": True}
    case_id = submit(client, token)
    run(client, token, case_id)

    case = detail(client, token, case_id)
    assert case["status"] == "ESCALATED" and case["contained_at"] is None
    failed = [a for a in case["actions"] if a["status"] == "VERIFY_FAILED"]
    # one location per batch is silently skipped: DC-EAST is the first location of all three held batches
    assert sorted(a["target"]["batch_id"] for a in failed) == ["FG-1041", "FG-1042", "FG-1043"]
    assert inventory(app)[("FG-1042", "PLANT-1")] == "HELD"
    with app.state.sessionmaker() as db:
        attempts = db.scalars(select(Verification.attempt).where(Verification.action_id == failed[0]["id"])).all()
        assert attempts == [1, 2]  # re-read, retried once, re-read
    events = client.get(f"/api/cases/{case_id}/timeline", headers=token("priya.qa")).json()
    assert "CONTAINED" not in [e["payload"].get("to") for e in events if e["kind"] == "STATUS_CHANGED"]
    assert any(e["kind"] == "ESCALATED" and e["payload"]["reason"] == "VERIFY_FAILED" for e in events)

    # fault cleared: a second run re-verifies, the idempotent retry now sticks, and the case recovers
    client.put("/api/demo/faults", json={"wms_silent_hold_failure": False}, headers=token("admin"))
    run(client, token, case_id)
    case = detail(client, token, case_id)
    assert case["status"] == "AWAITING_APPROVAL"
    assert all(a["status"] == "VERIFIED" for a in case["actions"] if a["type"] == "PLACE_HOLD")


def test_running_twice_creates_no_duplicates(env):
    app, client, token = env
    case_id = submit(client, token)
    run(client, token, case_id)
    first, sim_first = detail(client, token, case_id), sim_counts(app)
    run(client, token, case_id)
    second, sim_second = detail(client, token, case_id), sim_counts(app)

    assert [a["id"] for a in first["actions"]] == [a["id"] for a in second["actions"]]
    assert sim_first == sim_second and sim_first["holds"] == 4
    assert second["status"] == "AWAITING_APPROVAL"
    events = client.get(f"/api/cases/{case_id}/timeline", headers=token("priya.qa")).json()
    assert [e["kind"] for e in events].count("RUN_STARTED") == 2
    assert [e["kind"] for e in events].count("ACTION_CREATED") == 7  # 4 holds, 1 removal, 2 relabel tickets
    assert [e["kind"] for e in events].count("EXTRACTION_COMPLETED") == 1  # extract did not repeat


def test_resume_after_crash_mid_act_creates_no_duplicates(env):
    """A run that died during act resumes it; action keys and sim Idempotency-Keys prevent duplicates."""
    app, client, token = env
    case_id = submit(client, token)
    run(client, token, case_id)
    before, sim_before = detail(client, token, case_id), sim_counts(app)
    with app.state.sessionmaker() as db:
        case = db.get(Case, case_id)
        case.steps = {"extract": "DONE", "trace": "DONE", "decide": "DONE"}  # as if it crashed inside act
        db.commit()
    run(client, token, case_id)
    after = detail(client, token, case_id)
    assert sorted(a["id"] for a in after["actions"]) == sorted(a["id"] for a in before["actions"])
    assert sim_counts(app) == sim_before and after["status"] == "AWAITING_APPROVAL"


def test_concurrent_run_is_rejected(env):
    app, client, token = env
    case_id = submit(client, token)
    with app.state.sessionmaker() as db:
        db.get(Case, case_id).running_run_id = "r_other"
        db.commit()
    assert_error(client.post(f"/api/cases/{case_id}/run", headers=token("priya.qa")), 409, "CONFLICT")


def test_agent_remove_line_without_approval_is_policy_violation(env):
    app, client, token = env
    case_id = submit(client, token)
    run(client, token, case_id)
    before = sim_counts(app)
    with app.state.sessionmaker() as db:
        removal = db.scalar(select(Action).where(Action.case_id == case_id, Action.type == "REMOVE_FROM_SHIPMENT"))
        assert removal.status == "PENDING_APPROVAL"
        wms = WmsClient(SimHttp(app.state.sim_http, "k"), ApprovalGate(db, case_id, "labellock-agent"))
        with pytest.raises(ApiError) as e:
            wms.remove_line(removal.id)
        assert (e.value.status, e.value.code) == (409, "POLICY_VIOLATION")
        assert db.scalar(select(AuditEvent).where(AuditEvent.case_id == case_id, AuditEvent.kind == "POLICY_VIOLATION"))
    assert sim_counts(app) == before


def test_unrecorded_notice_escalates_without_acting(env):
    app, client, token = env
    case_id = submit(client, token, body=BODY + "\n\nP.S. different text, so no recorded extraction")
    run(client, token, case_id)
    case = detail(client, token, case_id)
    assert case["status"] == "ESCALATED"
    assert "CRITICAL_FIELD_UNRESOLVED" in case["extraction"]["uncertainty_flags"]
    assert case["trace"] is None
    # the only action is a drafted question back to the (verified) supplier, waiting for approval
    assert [(a["type"], a["status"], a["requires_approval"]) for a in case["actions"]] == [
        ("SEND_SUPPLIER_QUERY", "PENDING_APPROVAL", True)]
    assert set(inventory(app).values()) == {"AVAILABLE"}


def test_unverified_gmail_sender_escalates_without_acting(env):
    app, client, token = env
    r = client.post("/api/notices/ingest-email", headers=token("priya.qa"), json={
        "gmail_message_id": "m1", "thread_id": "t1", "from": "Someone <x@unknown.example>", "subject": SUBJECT,
        "body_text": BODY, "received_at": "2026-10-23T09:00:00Z",
        "attachments": [{"filename": "RM-114_spec_rev4.pdf", "mime_type": "application/pdf",
                         "content_base64": base64.b64encode(PDF).decode()}]})
    case_id = r.json()["case_id"]
    run(client, token, case_id)
    case = detail(client, token, case_id)
    assert case["status"] == "ESCALATED" and case["actions"] == []
    assert case["batch_decisions"]  # still analysed, so QA sees what it would affect
    assert set(inventory(app).values()) == {"AVAILABLE"}


def test_role_checks_on_case_apis(env):
    app, client, token = env
    case_id = submit(client, token)
    assert_error(client.get("/api/cases", headers=token("valley.ingredients")), 403, "FORBIDDEN")
    assert_error(client.get(f"/api/cases/{case_id}", headers=token("admin")), 403, "FORBIDDEN")
    assert_error(client.get(f"/api/cases/{case_id}/report", headers=token("marco.ship")), 403, "FORBIDDEN")
    assert_error(client.post(f"/api/cases/{case_id}/run", headers=token("marco.ship")), 403, "FORBIDDEN")
    assert client.get(f"/api/cases/{case_id}/timeline", headers=token("marco.ship")).status_code == 200
    assert_error(client.get("/api/cases/c_nope", headers=token("priya.qa")), 404, "NOT_FOUND")
    assert_error(client.put("/api/demo/faults", json={"wms_silent_hold_failure": True}, headers=token("daniel.qam")), 403, "FORBIDDEN")


def test_demo_controls_need_demo_mode_and_reset_clears_cases(env, tmp_path):
    app, client, token = env
    case_id = submit(client, token)
    run(client, token, case_id)
    assert client.post("/api/demo/reset", headers=token("admin")).json() == {"ok": True}
    assert client.get("/api/cases", headers=token("priya.qa")).json() == []
    assert set(inventory(app).values()) == {"AVAILABLE"}

    app.state.settings = Settings(**{**app.state.settings.__dict__, "demo_mode": False})
    assert_error(client.post("/api/demo/reset", headers=token("admin")), 404, "NOT_FOUND")


def test_uncertain_extraction_holds_and_escalates_without_restricted_actions(env, monkeypatch):
    """Policy, independent of what the model happens to flag: uncertain stock is held, a human decides the rest."""
    import agent.llm as llm_mod
    replay = llm_mod.MockLLM.extract
    monkeypatch.setattr(llm_mod.MockLLM, "extract",
                        lambda self, **kw: replay(self, **kw) | {"uncertainty_flags": ["LLM_UNCERTAIN"]})
    app, client, token = env
    case_id = submit(client, token)
    run(client, token, case_id)
    case = detail(client, token, case_id)
    assert case["status"] == "ESCALATED"
    assert {d["batch_id"]: d["decision"] for d in case["batch_decisions"]} == {
        "FG-1040": "NO_IMPACT", "FG-1041": "UNCERTAIN_ESCALATE", "FG-1042": "UNCERTAIN_ESCALATE", "FG-1043": "UNCERTAIN_ESCALATE"}
    holds = {(a["target"]["batch_id"], a["target"]["location"]): a["status"] for a in case["actions"] if a["type"] == "PLACE_HOLD"}
    assert holds == {("FG-1041", "DC-EAST"): "VERIFIED", ("FG-1042", "DC-EAST"): "VERIFIED",
                     ("FG-1042", "PLANT-1"): "VERIFIED", ("FG-1043", "DC-EAST"): "VERIFIED"}
    assert not [a for a in case["actions"] if a["type"] == "REMOVE_FROM_SHIPMENT"]  # restricted: waits for a human
    assert inventory(app)[("FG-1040", "PLANT-1")] == "AVAILABLE"
