import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from adapters.sim import ApprovalGate, ErpClient, SimHttp, WmsClient, idempotency_key
from api.db import Action, Approval, AuditEvent, Case, Notice, new_id, now_iso
from api.errors import ApiError
from sim.db import ShipmentLine
from sim.seed import reset_sim


def flaky(responses):
    """MockTransport returning the given responses (or raising exceptions) in order."""
    calls = []

    def handler(request):
        calls.append(request)
        item = responses[len(calls) - 1]
        if isinstance(item, Exception):
            raise item
        return item
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://sim"), calls


def test_get_retries_once_then_succeeds():
    client, calls = flaky([httpx.Response(503), httpx.Response(200, json={"lot_id": "VL-2291"})])
    log = []
    assert ErpClient(SimHttp(client, "k", log.append)).material_lot("VL-2291") == {"lot_id": "VL-2291"}
    assert len(calls) == 2 and calls[0].headers["X-Sim-Key"] == "k"
    assert log[0]["attempts"] == 2 and log[0]["error"] is None


def test_get_fails_after_retry_as_upstream_failed():
    client, calls = flaky([httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow")])
    with pytest.raises(ApiError) as e:
        ErpClient(SimHttp(client, "k")).genealogy("VL-2291")
    assert (e.value.status, e.value.code, len(calls)) == (502, "UPSTREAM_FAILED", 2)


def test_writes_do_not_retry_and_send_idempotency_key():
    client, calls = flaky([httpx.Response(500)])
    wms = WmsClient(SimHttp(client, "k"), gate=None)
    with pytest.raises(ApiError) as e:
        wms.place_hold("c_1", "FG-1041", "DC-EAST", "allergen")
    assert e.value.code == "UPSTREAM_FAILED" and len(calls) == 1
    target = {"batch_id": "FG-1041", "location": "DC-EAST"}
    assert calls[0].headers["Idempotency-Key"] == idempotency_key("c_1", "PLACE_HOLD", target)


def test_404_is_none_for_lookups_and_4xx_is_upstream_failed():
    client, _ = flaky([httpx.Response(404, json={}), httpx.Response(409, json={"error": {}})])
    http = SimHttp(client, "k")
    assert ErpClient(http).material_lot("NOPE") is None
    with pytest.raises(ApiError) as e:
        http.request("wms", "POST", "/sim/wms/holds", body={}, idem="x")
    assert e.value.code == "UPSTREAM_FAILED"


def test_idempotency_key_is_stable_and_target_sensitive():
    a = idempotency_key("c_1", "PLACE_HOLD", {"batch_id": "B", "location": "L"})
    assert a == idempotency_key("c_1", "PLACE_HOLD", {"location": "L", "batch_id": "B"})
    assert a != idempotency_key("c_1", "PLACE_HOLD", {"batch_id": "B", "location": "M"})
    assert a != idempotency_key("c_2", "PLACE_HOLD", {"batch_id": "B", "location": "L"})


@pytest.fixture
def case_with_removal(app, settings):
    reset_sim(app.state.sim_sessionmaker, settings.seed_dir)
    with app.state.sessionmaker() as db:
        notice = Notice(id=new_id("n"), source="supplier_portal", supplier_id="s_valley", subject="s", body="b",
                        received_at=now_iso(), content_hash="sha256:x")
        case = Case(id=new_id("c"), notice_id=notice.id, status="AWAITING_APPROVAL", uncertainty_flags=[], opened_at=now_iso())
        target = {"batch_id": "FG-1043", "shipment_id": "L-552"}
        action = Action(id=new_id("a"), case_id=case.id, type="REMOVE_FROM_SHIPMENT", target=target,
                        status="PENDING_APPROVAL", requires_approval=True, requested_by="labellock-agent",
                        idempotency_key=idempotency_key(case.id, "REMOVE_FROM_SHIPMENT", target), created_at=now_iso())
        db.add_all([notice, case, action])
        db.commit()
        return case.id, action.id


def make_wms(app, db, case_id):
    return WmsClient(SimHttp(TestClient(app), "test-sim-key"), ApprovalGate(db, case_id, "labellock-agent"))


def sim_line(app):
    with app.state.sim_sessionmaker() as sdb:
        return sdb.get(ShipmentLine, ("L-552", "FG-1043"))


@pytest.mark.parametrize("status", ["PENDING_APPROVAL", "REJECTED", "PROPOSED"])
def test_remove_line_without_approval_is_policy_violation(app, case_with_removal, status):
    case_id, action_id = case_with_removal
    with app.state.sessionmaker() as db:
        db.get(Action, action_id).status = status
        db.commit()
        with pytest.raises(ApiError) as e:
            make_wms(app, db, case_id).remove_line(action_id)
        assert (e.value.status, e.value.code) == (409, "POLICY_VIOLATION")
        event = db.scalar(select(AuditEvent).where(AuditEvent.case_id == case_id, AuditEvent.kind == "POLICY_VIOLATION"))
        assert event.payload["action_id"] == action_id
    assert sim_line(app) is not None  # sim untouched


def test_wrong_type_or_unknown_action_is_policy_violation(app, case_with_removal):
    case_id, action_id = case_with_removal
    with app.state.sessionmaker() as db:
        db.get(Action, action_id).status = "APPROVED"
        db.commit()
        wms = make_wms(app, db, case_id)
        for call in (lambda: wms.release_hold(action_id), lambda: wms.remove_line("a_missing")):
            with pytest.raises(ApiError) as e:
                call()
            assert e.value.code == "POLICY_VIOLATION"
    assert sim_line(app) is not None


@pytest.mark.parametrize("decided_by", [None, "priya.qa"])
def test_approved_status_without_a_qa_manager_approval_is_policy_violation(app, case_with_removal, decided_by):
    case_id, action_id = case_with_removal
    with app.state.sessionmaker() as db:
        db.get(Action, action_id).status = "APPROVED"  # status flipped, but no qa_manager decision on record
        if decided_by:
            db.add(Approval(action_id=action_id, decided_by=decided_by, decision="APPROVED", decided_at=now_iso()))
        db.commit()
        with pytest.raises(ApiError) as e:
            make_wms(app, db, case_id).remove_line(action_id)
        assert "no recorded approval" in e.value.message
    assert sim_line(app) is not None


def test_approved_removal_reaches_the_sim(app, case_with_removal):
    case_id, action_id = case_with_removal
    with app.state.sessionmaker() as db:
        db.get(Action, action_id).status = "APPROVED"
        db.add(Approval(action_id=action_id, decided_by="daniel.qam", decision="APPROVED", decided_at=now_iso()))
        db.commit()
        result = make_wms(app, db, case_id).remove_line(action_id)
    assert result["qty"] == 240
    assert sim_line(app) is None
