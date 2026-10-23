import json
import shutil

import pytest
from sqlalchemy import select

from sim.db import Inventory, ShipmentLine
from sim.seed import STUB_DIR, SeedError, choose_seed_dir, load_and_validate, reset_sim
from tests.test_auth import assert_error

KEY = {"X-Sim-Key": "test-sim-key"}


@pytest.fixture
def sim(app, client, settings):
    """Fresh sim state per test."""
    reset_sim(app.state.sim_sessionmaker, settings.seed_dir)
    yield client
    reset_sim(app.state.sim_sessionmaker, settings.seed_dir)


def inv(app, batch_id, location):
    with app.state.sim_sessionmaker() as db:
        return db.get(Inventory, (batch_id, location)).status


def test_sim_requires_key(client):
    assert_error(client.get("/sim/labels/OCB-100"), 401, "UNAUTHENTICATED")
    assert_error(client.get("/sim/labels/OCB-100", headers={"X-Sim-Key": "wrong"}), 401, "UNAUTHENTICATED")


def test_erp_reads(sim):
    assert sim.get("/sim/erp/material-lots/VL-2291", headers=KEY).json()["material_id"] == "RM-114"
    assert_error(sim.get("/sim/erp/material-lots/NOPE", headers=KEY), 404, "NOT_FOUND")
    assert [p["sku"] for p in sim.get("/sim/erp/products", params={"material_id": "RM-114"}, headers=KEY).json()] == ["ASB-100", "HGB-200", "OCB-100"]
    batches = sim.get("/sim/erp/genealogy", params={"material_lot_id": "VL-2291"}, headers=KEY).json()
    assert [b["batch_id"] for b in batches] == ["FG-1040", "FG-1041", "FG-1042", "FG-1043"]
    assert sim.get("/sim/erp/batches/FG-1043", headers=KEY).json()["material_lot_ids"] == ["VL-2291", "VS-1180"]
    assert sim.get("/sim/labels/HGB-200", headers=KEY).json()["contains"] == ["milk"]


def test_hold_is_idempotent_and_changes_inventory(app, sim):
    body = {"batch_id": "FG-1041", "location": "DC-EAST", "reason": "allergen", "case_ref": "c_x"}
    first = sim.post("/sim/wms/holds", json=body, headers=KEY | {"Idempotency-Key": "k1"})
    again = sim.post("/sim/wms/holds", json=body, headers=KEY | {"Idempotency-Key": "k1"})
    assert (first.status_code, again.status_code) == (201, 200)
    assert first.json()["hold_id"] == again.json()["hold_id"]
    assert len(sim.get("/sim/wms/holds", params={"batch_id": "FG-1041"}, headers=KEY).json()) == 1
    assert inv(app, "FG-1041", "DC-EAST") == "HELD"
    assert_error(sim.post("/sim/wms/holds", json=body | {"location": "PLANT-1"}, headers=KEY | {"Idempotency-Key": "k1"}), 409, "CONFLICT")
    assert_error(sim.post("/sim/wms/holds", json=body, headers=KEY), 422, "VALIDATION_ERROR")  # no Idempotency-Key

    released = sim.post(f"/sim/wms/holds/{first.json()['hold_id']}/release", headers=KEY)
    assert released.json()["status"] == "RELEASED"
    assert inv(app, "FG-1041", "DC-EAST") == "AVAILABLE"


def test_silent_hold_failure_leaves_one_location_available(app, sim):
    assert sim.put("/sim/admin/faults", json={"wms_silent_hold_failure": True}, headers=KEY).json() == {"ok": True}
    for loc in ("DC-EAST", "PLANT-1"):
        r = sim.post("/sim/wms/holds", json={"batch_id": "FG-1042", "location": loc, "reason": "r", "case_ref": "c"},
                     headers=KEY | {"Idempotency-Key": f"k-{loc}"})
        assert r.status_code == 201  # reports success either way
    assert (inv(app, "FG-1042", "DC-EAST"), inv(app, "FG-1042", "PLANT-1")) == ("AVAILABLE", "HELD")


def test_remove_line_is_idempotent(app, sim):
    h = KEY | {"Idempotency-Key": "rm1"}
    first = sim.post("/sim/wms/shipments/L-552/remove-line", json={"batch_id": "FG-1043"}, headers=h)
    again = sim.post("/sim/wms/shipments/L-552/remove-line", json={"batch_id": "FG-1043"}, headers=h)
    assert first.status_code == again.status_code == 200
    assert first.json() == again.json()
    lines = sim.get("/sim/wms/shipments/L-552", headers=KEY).json()["lines"]
    assert lines == [{"batch_id": "FG-1040", "qty": 100}]
    assert sim.get("/sim/wms/shipments", params={"batch_id": "FG-1043"}, headers=KEY).json() == []


def test_stub_is_used_when_seed_dir_missing_or_incomplete(tmp_path):
    assert choose_seed_dir(tmp_path / "absent") == STUB_DIR
    (tmp_path / "suppliers.json").write_text("[]")
    assert choose_seed_dir(tmp_path) == STUB_DIR


def test_invalid_seed_fails_loudly_with_every_problem(tmp_path):
    seed = tmp_path / "seed"
    shutil.copytree(STUB_DIR, seed)
    inventory = json.loads((seed / "inventory.json").read_text())
    inventory[0]["status"] = "LOST"
    inventory[1]["qty"] = "600"
    (seed / "inventory.json").write_text(json.dumps(inventory))
    genealogy = json.loads((seed / "genealogy.json").read_text())
    genealogy.append({"batch_id": "FG-9999", "material_lot_id": "VL-2291"})
    (seed / "genealogy.json").write_text(json.dumps(genealogy))

    assert choose_seed_dir(seed) == seed  # complete, so it is used (no silent fallback)
    with pytest.raises(SeedError) as e:
        load_and_validate(seed)
    msg = str(e.value)
    assert "inventory.json[0].status" in msg and "inventory.json[1].qty" in msg and "FG-9999" in msg


def test_reset_restores_seed_state(app, sim):
    sim.post("/sim/wms/shipments/L-552/remove-line", json={"batch_id": "FG-1043"}, headers=KEY | {"Idempotency-Key": "x"})
    assert sim.post("/sim/admin/reset", headers=KEY).json()["ok"] is True
    with app.state.sim_sessionmaker() as db:
        assert db.get(ShipmentLine, ("L-552", "FG-1043")) is not None
        assert db.scalar(select(Inventory).where(Inventory.status == "HELD")) is None
