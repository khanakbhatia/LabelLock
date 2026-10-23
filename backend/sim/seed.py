"""Load /data/seed/*.json (Khanak's dataset) into the sim DB, replacing what is there.

Falls back to backend/tests/fixtures/seed_stub/ only when the seed directory is missing or lacks
files. Data that is present but invalid fails loudly with every problem listed.
"""
import json
import logging
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from sim.db import (
    Batch, Genealogy, Inventory, Label, Material, MaterialLot, Product, Recipe, Shipment, ShipmentLine, SimBase,
    Supplier,
)

log = logging.getLogger("labellock.seed")

STUB_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "seed_stub"

# file -> (model, {field: type}, primary key fields). Order matters: referenced tables first.
SCHEMA = {
    "suppliers": (Supplier, {"supplier_id": str, "name": str}, ("supplier_id",)),
    "materials": (Material, {"material_id": str, "name": str, "supplier_id": str}, ("material_id",)),
    "material_lots": (MaterialLot, {"lot_id": str, "material_id": str, "received_at": str}, ("lot_id",)),
    "products": (Product, {"sku": str, "name": str, "label_version": str}, ("sku",)),
    "recipes": (Recipe, {"sku": str, "material_id": str}, ("sku", "material_id")),
    "labels": (Label, {"sku": str, "version": str, "ingredient_statement": str, "contains": list,
                       "may_contain": list, "claims": list}, ("sku", "version")),
    "batches": (Batch, {"batch_id": str, "sku": str, "produced_at": str}, ("batch_id",)),
    "genealogy": (Genealogy, {"batch_id": str, "material_lot_id": str}, ("batch_id", "material_lot_id")),
    "inventory": (Inventory, {"batch_id": str, "location": str, "qty": int, "status": str}, ("batch_id", "location")),
    "shipments": (Shipment, {"shipment_id": str, "destination": str, "departs_at": str, "status": str}, ("shipment_id",)),
    "shipment_lines": (ShipmentLine, {"shipment_id": str, "batch_id": str, "qty": int}, ("shipment_id", "batch_id")),
}

# (file, field) -> (referenced file, referenced field)
FOREIGN_KEYS = {
    ("materials", "supplier_id"): ("suppliers", "supplier_id"),
    ("material_lots", "material_id"): ("materials", "material_id"),
    ("recipes", "sku"): ("products", "sku"),
    ("recipes", "material_id"): ("materials", "material_id"),
    ("labels", "sku"): ("products", "sku"),
    ("batches", "sku"): ("products", "sku"),
    ("genealogy", "batch_id"): ("batches", "batch_id"),
    ("genealogy", "material_lot_id"): ("material_lots", "lot_id"),
    ("inventory", "batch_id"): ("batches", "batch_id"),
    ("shipment_lines", "shipment_id"): ("shipments", "shipment_id"),
    ("shipment_lines", "batch_id"): ("batches", "batch_id"),
}

ENUMS = {
    ("inventory", "status"): {"AVAILABLE", "HELD"},
    ("shipments", "status"): {"PLANNED", "LOADING", "DEPARTED", "DELIVERED"},
}


class SeedError(Exception):
    pass


def choose_seed_dir(seed_dir: Path) -> Path:
    missing = [f"{name}.json" for name in SCHEMA if not (seed_dir / f"{name}.json").exists()]
    if missing:
        log.warning("Seed dir %s missing %s; using stub %s", seed_dir, ", ".join(missing), STUB_DIR)
        return STUB_DIR
    return seed_dir


def load_and_validate(seed_dir: Path) -> dict[str, list[dict]]:
    data, problems = {}, []
    for name, (_, fields, pk) in SCHEMA.items():
        try:
            rows = json.loads((seed_dir / f"{name}.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            problems.append(f"{name}.json: cannot read: {e}")
            continue
        if not isinstance(rows, list):
            problems.append(f"{name}.json: expected a JSON array")
            continue
        seen = set()
        for i, row in enumerate(rows):
            where = f"{name}.json[{i}]"
            if not isinstance(row, dict):
                problems.append(f"{where}: expected an object")
                continue
            if set(row) != set(fields):
                problems.append(f"{where}: fields {sorted(row)} != expected {sorted(fields)}")
                continue
            for field, typ in fields.items():
                value = row[field]
                if not isinstance(value, typ) or isinstance(value, bool) or (typ is list and not all(isinstance(v, str) for v in value)):
                    problems.append(f"{where}.{field}: expected {typ.__name__}{' of strings' if typ is list else ''}")
            allowed = {f: v for (t, f), v in ENUMS.items() if t == name}
            for field, values in allowed.items():
                if row.get(field) not in values:
                    problems.append(f"{where}.{field}: {row.get(field)!r} not in {sorted(values)}")
            key = tuple(row[k] for k in pk)
            if key in seen:
                problems.append(f"{where}: duplicate key {key}")
            seen.add(key)
        data[name] = rows

    for (table, field), (ref_table, ref_field) in FOREIGN_KEYS.items():
        known = {r.get(ref_field) for r in data.get(ref_table, []) if isinstance(r, dict)}
        for i, row in enumerate(data.get(table, [])):
            if isinstance(row, dict) and field in row and row[field] not in known:
                problems.append(f"{table}.json[{i}].{field}: {row[field]!r} not found in {ref_table}.{ref_field}")
    products = {r["sku"]: r for r in data.get("products", []) if isinstance(r, dict) and "sku" in r}
    label_keys = {(r.get("sku"), r.get("version")) for r in data.get("labels", []) if isinstance(r, dict)}
    for sku, p in products.items():
        if (sku, p.get("label_version")) not in label_keys:
            problems.append(f"products.json: {sku} label_version {p.get('label_version')!r} has no labels.json row")

    if problems:
        raise SeedError(f"Seed data in {seed_dir} is invalid:\n  " + "\n  ".join(problems))
    return data


def reset_sim(sim_sessionmaker: sessionmaker[Session], seed_dir: Path) -> Path:
    """Drop and recreate every sim table, then load the seed. Returns the directory used."""
    source = choose_seed_dir(seed_dir)
    data = load_and_validate(source)  # validate before touching the DB
    engine = sim_sessionmaker.kw["bind"]
    SimBase.metadata.drop_all(engine)
    SimBase.metadata.create_all(engine)
    with sim_sessionmaker() as db:
        for name, (model, _, _) in SCHEMA.items():
            db.add_all(model(**row) for row in data[name])
        db.commit()
    log.info("Sim DB loaded from %s", source)
    return source
