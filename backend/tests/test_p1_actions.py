"""P1: relabel tickets (direct), retailer notices and supplier queries (drafted, sent only after approval)."""
import base64

import pytest
from sqlalchemy import select

from adapters.sim import ApprovalGate, OutboxClient, SimHttp
from api.db import Action
from api.errors import ApiError
from scenarios import load_scenarios
from scenarios.runner import notice_parts
from sim.db import OutboxMessage, Ticket
from tests.conftest import assert_matches
from tests.test_agent import BODY, PDF, SUBJECT, detail, env, run, submit  # noqa: F401 (env is a fixture)
from tests.test_auth import assert_error


def scenario(sid: str) -> dict:
    return next(s for s in load_scenarios() if s["id"] == sid)


def submit_scenario(client, token, sid: str) -> str:
    subject, body, pdf = notice_parts(scenario(sid))
    r = client.post("/api/notices", data={"subject": subject, "body": body}, headers=token("valley.ingredients"),
                    files={"attachment": ("spec.pdf", pdf, "application/pdf")})
    assert r.status_code == 201, r.text
    return r.json()["case_id"]


def actions_of(case: dict, type_: str) -> list[dict]:
    return [a for a in case["actions"] if a["type"] == type_]


def sim_rows(app, model, case_id):
    with app.state.sim_sessionmaker() as db:
        return list(db.scalars(select(model).where(model.case_ref == case_id)))


def test_golden_path_opens_one_relabel_ticket_per_sku(env):
    app, client, token = env
    case_id = submit(client, token)
    run(client, token, case_id)
    case = detail(client, token, case_id)
    tickets = actions_of(case, "CREATE_RELABEL_TICKET")
    assert sorted(a["target"]["sku"] for a in tickets) == ["ASB-100", "HGB-200"]  # FG-1041 + FG-1042 share HGB-200
    assert all(a["status"] == "VERIFIED" and not a["requires_approval"] for a in tickets)
    hgb = next(a for a in tickets if a["target"]["sku"] == "HGB-200")
    assert "FG-1041" in hgb["result"]["summary"] and "FG-1042" in hgb["result"]["summary"]
    assert {t.sku for t in sim_rows(app, Ticket, case_id)} == {"ASB-100", "HGB-200"}  # really in the sim
    assert not actions_of(case, "SEND_RETAILER_NOTICE") and not actions_of(case, "SEND_SUPPLIER_QUERY")
    assert sim_rows(app, OutboxMessage, case_id) == []

    # tickets do not hold up containment: approving the removal still contains the case
    removal = actions_of(case, "REMOVE_FROM_SHIPMENT")[0]
    client.post(f"/api/actions/{removal['id']}/approve", headers=token("daniel.qam"))
    assert detail(client, token, case_id)["status"] == "CONTAINED"


def test_shipped_batch_gets_a_drafted_retailer_notice_sent_only_after_approval(env):
    app, client, token = env
    case_id = submit_scenario(client, token, "S08")  # FG-2302 already left on L-590 to Retailer DC 9
    run(client, token, case_id)
    case = detail(client, token, case_id)
    [notice] = actions_of(case, "SEND_RETAILER_NOTICE")
    assert notice["target"] == {"batch_id": "FG-2302", "shipment_id": "L-590", "to": "Retailer DC 9"}
    assert (notice["status"], notice["requires_approval"]) == ("PENDING_APPROVAL", True)
    assert "withdraw" in notice["result"]["body"] and "FG-2302" in notice["result"]["subject"]
    [draft] = sim_rows(app, OutboxMessage, case_id)
    assert (draft.status, draft.to) == ("DRAFT", "Retailer DC 9")  # drafted, not sent

    queue = client.get("/api/approvals", params={"status": "PENDING_APPROVAL"}, headers=token("daniel.qam")).json()
    assert notice["id"] in [a["id"] for a in queue]
    assert_error(client.post(f"/api/actions/{notice['id']}/approve", headers=token("priya.qa")), 403, "FORBIDDEN")
    client.post(f"/api/actions/{notice['id']}/approve", json={"comment": "Send it"}, headers=token("daniel.qam"))

    sent = next(a for a in detail(client, token, case_id)["actions"] if a["id"] == notice["id"])
    assert sent["status"] == "VERIFIED" and sent["result"]["sent_at"]
    assert sim_rows(app, OutboxMessage, case_id)[0].status == "SENT"
    assert detail(client, token, case_id)["status"] == "ESCALATED"  # shipped stock still needs a human


def test_rejected_notice_is_never_sent(env):
    app, client, token = env
    case_id = submit_scenario(client, token, "S08")
    run(client, token, case_id)
    [notice] = actions_of(detail(client, token, case_id), "SEND_RETAILER_NOTICE")
    client.post(f"/api/actions/{notice['id']}/reject", json={"reason": "Call the retailer instead"}, headers=token("daniel.qam"))
    run(client, token, case_id)
    assert sim_rows(app, OutboxMessage, case_id)[0].status == "DRAFT"


@pytest.mark.parametrize("sid,reason", [("S12", "VL-9999"), ("S13", "RM-305"), ("S14", "missing")])
def test_unusable_notice_drafts_a_supplier_query(env, sid, reason):
    app, client, token = env
    case_id = submit_scenario(client, token, sid)
    run(client, token, case_id)
    case = detail(client, token, case_id)
    [query] = actions_of(case, "SEND_SUPPLIER_QUERY")
    assert case["status"] == "ESCALATED"
    assert query["target"]["to"] == "supplier-portal:s_valley" and query["status"] == "PENDING_APPROVAL"
    assert reason in query["result"]["body"]
    client.post(f"/api/actions/{query['id']}/approve", headers=token("daniel.qam"))
    assert sim_rows(app, OutboxMessage, case_id)[0].status == "SENT"


def test_no_query_to_an_unverified_sender(env):
    app, client, token = env
    r = client.post("/api/notices/ingest-email", headers=token("priya.qa"), json={
        "gmail_message_id": "m-vague", "thread_id": "t", "from": "Someone <x@unknown.example>", "subject": "Change",
        "body_text": "We are changing an ingredient soon.", "received_at": "2026-10-23T09:00:00Z",
        "attachments": [{"filename": "a.pdf", "mime_type": "application/pdf", "content_base64": base64.b64encode(PDF).decode()}]})
    case_id = r.json()["case_id"]
    run(client, token, case_id)
    case = detail(client, token, case_id)
    assert case["status"] == "ESCALATED" and actions_of(case, "SEND_SUPPLIER_QUERY") == []
    kinds = [e["kind"] for e in client.get(f"/api/cases/{case_id}/timeline", headers=token("priya.qa")).json()]
    assert "SUPPLIER_QUERY_SKIPPED" in kinds
    assert sim_rows(app, OutboxMessage, case_id) == []


def test_agent_cannot_send_a_draft_without_approval(env):
    app, client, token = env
    case_id = submit_scenario(client, token, "S08")
    run(client, token, case_id)
    with app.state.sessionmaker() as db:
        notice = db.scalar(select(Action).where(Action.case_id == case_id, Action.type == "SEND_RETAILER_NOTICE"))
        outbox = OutboxClient(SimHttp(app.state.sim_http, "k"), ApprovalGate(db, case_id, "labellock-agent"))
        with pytest.raises(ApiError) as e:
            outbox.send(notice.id, "SEND_RETAILER_NOTICE")
        assert e.value.code == "POLICY_VIOLATION"
    assert sim_rows(app, OutboxMessage, case_id)[0].status == "DRAFT"


def test_sim_tickets_and_outbox_are_idempotent(env):
    app, client, token = env
    key = {"X-Sim-Key": "k", "Idempotency-Key": "same"}
    t1 = client.post("/sim/tickets", json={"sku": "HGB-200", "summary": "s", "case_ref": "c"}, headers=key)
    t2 = client.post("/sim/tickets", json={"sku": "HGB-200", "summary": "s", "case_ref": "c"}, headers=key)
    assert (t1.status_code, t2.status_code) == (201, 200) and t1.json()["ticket_id"] == t2.json()["ticket_id"]
    m1 = client.post("/sim/outbox", json={"to": "x", "subject": "s", "body": "b", "case_ref": "c"}, headers=key)
    mid = m1.json()["message_id"]
    s1 = client.post(f"/sim/outbox/{mid}/send", headers={"X-Sim-Key": "k"}).json()
    s2 = client.post(f"/sim/outbox/{mid}/send", headers={"X-Sim-Key": "k"}).json()
    assert s1["status"] == s2["status"] == "SENT" and s1["sent_at"] == s2["sent_at"]
    assert_error(client.post("/sim/outbox", json={"to": "x", "subject": "s", "body": "b", "case_ref": "c"}), 401, "UNAUTHENTICATED")


def test_actions_still_match_the_contract(env):
    app, client, token = env
    case_id = submit_scenario(client, token, "S08")
    run(client, token, case_id)
    for a in detail(client, token, case_id)["actions"]:
        assert_matches("Action", a)
