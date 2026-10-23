"""M2: notice reads, approvals queue, approve executes and verifies, reject, dispositions, release requests."""
import base64

from sqlalchemy import select

from api.db import Case
from sim.db import Hold, ShipmentLine
from tests.conftest import assert_matches
from tests.test_agent import BODY, PDF, SUBJECT, by, detail, env, inventory, run, submit  # noqa: F401 (env is a fixture)
from tests.test_auth import assert_error


def removal_of(case: dict) -> dict:
    return next(a for a in case["actions"] if a["type"] == "REMOVE_FROM_SHIPMENT")


def events(client, token, case_id) -> list[dict]:
    return client.get(f"/api/cases/{case_id}/timeline", headers=token("priya.qa")).json()


def test_inbox_and_notice_reads(env):
    app, client, token = env
    case_id = submit(client, token)
    inbox = client.get("/api/inbox", headers=token("priya.qa")).json()
    assert [i["case_id"] for i in inbox] == [case_id]
    assert_matches("InboxItem", inbox[0])
    assert inbox[0]["supplier"] == "Valley Ingredients" and inbox[0]["has_attachment"] is True

    mine = client.get("/api/notices", params={"mine": "true"}, headers=token("valley.ingredients")).json()
    assert_matches("NoticeSummary", mine[0])
    notice_id = mine[0]["id"]
    notice = client.get(f"/api/notices/{notice_id}", headers=token("valley.ingredients")).json()
    assert_matches("Notice", notice)
    assert notice["body"] == BODY and notice["attachment"]["filename"] == "RM-114_spec_rev4.pdf"
    pdf = client.get(f"/api/notices/{notice_id}/attachment", headers=token("daniel.qam"))
    assert pdf.content == PDF and pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["x-content-type-options"] == "nosniff"

    assert_error(client.get("/api/notices", params={"mine": "false"}, headers=token("valley.ingredients")), 422, "VALIDATION_ERROR")
    assert_error(client.get("/api/inbox", headers=token("valley.ingredients")), 403, "FORBIDDEN")
    assert_error(client.get(f"/api/notices/{notice_id}", headers=token("marco.ship")), 403, "FORBIDDEN")
    assert_error(client.get("/api/notices/n_missing", headers=token("priya.qa")), 404, "NOT_FOUND")


def test_supplier_cannot_see_other_suppliers_notices(env):
    app, client, token = env
    r = client.post("/api/notices/ingest-email", headers=token("priya.qa"), json={
        "gmail_message_id": "m-other", "thread_id": "t", "from": "x@unknown.example", "subject": "s", "body_text": "b",
        "received_at": "2026-10-23T09:00:00Z",
        "attachments": [{"filename": "a.pdf", "mime_type": "application/pdf", "content_base64": base64.b64encode(PDF).decode()}]})
    notice_id = r.json()["notice_id"]
    assert client.get("/api/notices", params={"mine": "true"}, headers=token("valley.ingredients")).json() == []
    assert_error(client.get(f"/api/notices/{notice_id}", headers=token("valley.ingredients")), 404, "NOT_FOUND")
    assert_error(client.get(f"/api/notices/{notice_id}/attachment", headers=token("valley.ingredients")), 404, "NOT_FOUND")


def test_approving_removal_executes_verifies_and_contains(env):
    app, client, token = env
    case_id = submit(client, token)
    run(client, token, case_id)

    queue = client.get("/api/approvals", params={"status": "PENDING_APPROVAL"}, headers=token("priya.qa")).json()
    assert len(queue) == 1
    assert_matches("Action", queue[0])
    action_id = queue[0]["id"]
    assert_error(client.post(f"/api/actions/{action_id}/approve", json={}, headers=token("priya.qa")), 403, "FORBIDDEN")

    r = client.post(f"/api/actions/{action_id}/approve", json={"comment": "Pull it from L-552"}, headers=token("daniel.qam"))
    assert r.status_code == 200, r.text
    assert_matches("Action", r.json())
    assert r.json()["status"] == "APPROVED"  # execution is queued; the run happens in the background

    with app.state.sim_sessionmaker() as sdb:
        assert sdb.get(ShipmentLine, ("L-552", "FG-1043")) is None   # really gone from the WMS
        assert sdb.get(ShipmentLine, ("L-552", "FG-1040")) is not None
    case = detail(client, token, case_id)
    assert removal_of(case)["status"] == "VERIFIED"
    assert case["status"] == "CONTAINED" and case["contained_at"]
    report = client.get(f"/api/cases/{case_id}/report", headers=token("daniel.qam")).json()
    assert_matches("CaseReport", report)
    assert by(report["batches"])["FG-1043"] == {"batch_id": "FG-1043", "decision": "CLAIM_CONFLICT",
                                                 "final_state": "REMOVED_FROM_SHIPMENT", "verified": True}
    assert report["metrics"]["seconds_to_contained"] is not None
    kinds = [(e["kind"], e["payload"].get("to")) for e in events(client, token, case_id)]
    assert ("APPROVAL_DECIDED", None) in kinds and ("STATUS_CHANGED", "CONTAINED") in kinds

    assert_error(client.post(f"/api/actions/{action_id}/approve", json={}, headers=token("daniel.qam")), 409, "CONFLICT")
    assert client.get("/api/approvals", params={"status": "PENDING_APPROVAL"}, headers=token("daniel.qam")).json() == []


def test_approve_without_body_is_accepted(env):
    app, client, token = env
    case_id = submit(client, token)
    run(client, token, case_id)
    action_id = removal_of(detail(client, token, case_id))["id"]
    assert client.post(f"/api/actions/{action_id}/approve", headers=token("daniel.qam")).json()["status"] == "APPROVED"


def test_rejecting_removal_escalates(env):
    app, client, token = env
    case_id = submit(client, token)
    run(client, token, case_id)
    action_id = removal_of(detail(client, token, case_id))["id"]
    assert_error(client.post(f"/api/actions/{action_id}/reject", json={}, headers=token("daniel.qam")), 422, "VALIDATION_ERROR")
    assert_error(client.post(f"/api/actions/{action_id}/reject", json={"reason": ""}, headers=token("daniel.qam")), 422, "VALIDATION_ERROR")
    r = client.post(f"/api/actions/{action_id}/reject", json={"reason": "Customer accepts relabel at DC"}, headers=token("daniel.qam"))
    assert r.json()["status"] == "REJECTED"
    case = detail(client, token, case_id)
    assert case["status"] == "ESCALATED"  # affected stock may now ship: a human must own that
    with app.state.sim_sessionmaker() as sdb:
        assert sdb.get(ShipmentLine, ("L-552", "FG-1043")) is not None


def test_approval_during_a_run_is_executed_by_the_next_run(env):
    app, client, token = env
    case_id = submit(client, token)
    run(client, token, case_id)
    action_id = removal_of(detail(client, token, case_id))["id"]
    with app.state.sessionmaker() as db:
        db.get(Case, case_id).running_run_id = "r_busy"
        db.commit()
    assert client.post(f"/api/actions/{action_id}/approve", headers=token("daniel.qam")).json()["status"] == "APPROVED"
    assert "EXECUTION_DEFERRED" in [e["kind"] for e in events(client, token, case_id)]
    with app.state.sessionmaker() as db:
        db.get(Case, case_id).running_run_id = None
        db.commit()
    run(client, token, case_id)
    assert detail(client, token, case_id)["status"] == "CONTAINED"


def test_release_needs_a_releasable_disposition_and_approval(env):
    app, client, token = env
    case_id = submit(client, token)
    run(client, token, case_id)
    release = {"batch_id": "FG-1041", "reason": "Relabelled with soy declaration"}

    err = assert_error(client.post(f"/api/cases/{case_id}/release-requests", json=release, headers=token("marco.ship")),
                       409, "POLICY_VIOLATION")
    assert "disposition" in err["message"]
    assert "POLICY_VIOLATION" in [e["kind"] for e in events(client, token, case_id)]

    disp = {"batch_id": "FG-1041", "disposition": "DESTROY", "evidence": "QA decision"}
    assert_error(client.post(f"/api/cases/{case_id}/dispositions", json=disp, headers=token("priya.qa")), 403, "FORBIDDEN")
    assert_error(client.post(f"/api/cases/{case_id}/dispositions", json=disp | {"disposition": "MAYBE"},
                             headers=token("daniel.qam")), 422, "VALIDATION_ERROR")
    assert_error(client.post(f"/api/cases/{case_id}/dispositions", json=disp | {"batch_id": "FG-9999"},
                             headers=token("daniel.qam")), 404, "NOT_FOUND")
    r = client.post(f"/api/cases/{case_id}/dispositions", json=disp, headers=token("daniel.qam"))
    assert r.status_code == 201
    assert_matches("Disposition", r.json())
    assert_error(client.post(f"/api/cases/{case_id}/release-requests", json=release, headers=token("marco.ship")),
                 409, "POLICY_VIOLATION")  # destroyed stock never goes back to AVAILABLE

    client.post(f"/api/cases/{case_id}/dispositions", headers=token("daniel.qam"),
                json={"batch_id": "FG-1041", "disposition": "RELABEL", "evidence": "Relabel run RL-77 checked by QA"})
    r = client.post(f"/api/cases/{case_id}/release-requests", json=release, headers=token("marco.ship"))
    assert r.status_code == 201, r.text
    assert_matches("Action", r.json())
    assert (r.json()["type"], r.json()["status"], r.json()["requested_by"]) == ("RELEASE_HOLD", "PENDING_APPROVAL", "marco.ship")
    assert inventory(app)[("FG-1041", "DC-EAST")] == "HELD"  # nothing released before approval
    assert_error(client.post(f"/api/cases/{case_id}/release-requests", json=release, headers=token("priya.qa")), 409, "CONFLICT")

    client.post(f"/api/actions/{r.json()['id']}/approve", headers=token("daniel.qam"))
    assert inventory(app)[("FG-1041", "DC-EAST")] == "AVAILABLE"
    with app.state.sim_sessionmaker() as sdb:
        assert {h.status for h in sdb.scalars(select(Hold).where(Hold.batch_id == "FG-1041"))} == {"RELEASED"}
    case = detail(client, token, case_id)
    released = next(a for a in case["actions"] if a["type"] == "RELEASE_HOLD")
    assert released["status"] == "VERIFIED"
    assert by(case["trace"]["batches"])["FG-1041"]["locations"][0]["status"] == "AVAILABLE"
    assert inventory(app)[("FG-1042", "DC-EAST")] == "HELD"  # other batches untouched
