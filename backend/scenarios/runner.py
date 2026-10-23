"""Run the eval scenarios through the real API and agent, and score them.

    python -m scenarios.runner                    # mock mode: replay recorded extractions (free)
    python -m scenarios.runner --record-missing   # call Claude for notices with no recording yet, save them
    python -m scenarios.runner --only S01,S16     # a subset

Each scenario: demo reset -> faults -> submit notice (portal or Gmail) -> run agent -> read the case and the sim DB.
A recording run (or --save) writes scenarios/results/latest.json, which GET /api/metrics/roi reads.
"""
import argparse
import base64
import dataclasses
import json
import statistics
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

import agent.llm as llm_mod
from api.main import create_app
from api.notices import notice_content_hash
from api.settings import Settings, load_dotenv
from rules import AFFECTED
from scenarios import load_scenarios
from scenarios.pdf import make_pdf
from sim.db import Inventory
from sim.seed import STUB_DIR

BACKEND = Path(__file__).resolve().parents[1]
RESULTS = Path(__file__).with_name("results") / "latest.json"


def notice_parts(s: dict) -> tuple[str, str, bytes]:
    body = (BACKEND / s["body_file"]).read_text(encoding="utf-8") if "body_file" in s else s["body"]
    pdf = (BACKEND / s["pdf_file"]).read_bytes() if "pdf_file" in s else make_pdf(s["pdf_pages"])
    return s["subject"], body, pdf


def fixture_exists(s: dict) -> bool:
    subject, body, pdf = notice_parts(s)
    return (llm_mod.FIXTURES / f"{notice_content_hash(subject, body, [pdf]).removeprefix('sha256:')}.json").exists()


class Env:
    """One app with throwaway databases; the stub seed always (scenarios are written against it)."""

    def __init__(self, workdir: Path):
        settings = Settings(database_url=f"sqlite:///{(workdir / 'app.db').as_posix()}",
                            sim_database_url=f"sqlite:///{(workdir / 'sim.db').as_posix()}",
                            upload_dir=workdir / "uploads", seed_dir=STUB_DIR, demo_mode=True, auth_secret="eval")
        self.app = create_app(settings)
        self.app.state.sim_http = TestClient(self.app)
        self.client = TestClient(self.app)
        self.tokens = {u: self.client.post("/api/auth/login", json={"username": u, "password": "demo"}).json()["token"]
                       for u in ("valley.ingredients", "priya.qa", "admin")}

    def h(self, user: str) -> dict:
        return {"Authorization": f"Bearer {self.tokens[user]}"}

    def close(self) -> None:
        self.app.state.sim_http.close()
        for sm in (self.app.state.sessionmaker, self.app.state.sim_sessionmaker):
            sm.kw["bind"].dispose()  # Windows cannot delete open SQLite files

    def set_llm_mode(self, mode: str) -> None:
        self.app.state.settings = dataclasses.replace(self.app.state.settings, llm_mode=mode)

    def inventory(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        with self.app.state.sim_sessionmaker() as db:
            for row in db.scalars(select(Inventory)):
                out.setdefault(row.batch_id, set()).add(row.status)
        return out


def run_one(env: Env, s: dict, llm: str) -> dict:
    c = env.client
    c.post("/api/demo/reset", headers=env.h("admin")).raise_for_status()
    c.put("/api/demo/faults", headers=env.h("admin"),
          json={"wms_silent_hold_failure": bool(s.get("faults", {}).get("wms_silent_hold_failure"))}).raise_for_status()
    subject, body, pdf = notice_parts(s)
    duplicate = None
    if s["source"] == "gmail":
        payload = {"gmail_message_id": f"{s['id']}-msg", "thread_id": f"{s['id']}-thread", "from": s["sender"],
                   "subject": subject, "body_text": body, "received_at": "2026-10-23T09:00:00Z",
                   "attachments": [{"filename": "spec.pdf", "mime_type": "application/pdf",
                                    "content_base64": base64.b64encode(pdf).decode()}]}
        r = c.post("/api/notices/ingest-email", json=payload, headers=env.h("priya.qa"))
        r.raise_for_status()
        case_id = r.json()["case_id"]
        if s.get("repeat_ingest"):
            again = c.post("/api/notices/ingest-email", json=payload, headers=env.h("priya.qa")).json()
            duplicate = again["duplicate"] and again["case_id"] == case_id
    else:
        r = c.post("/api/notices", data={"subject": subject, "body": body}, headers=env.h("valley.ingredients"),
                   files={"attachment": ("spec.pdf", pdf, "application/pdf")})
        r.raise_for_status()
        case_id = r.json()["case_id"]
    c.post(f"/api/cases/{case_id}/run", headers=env.h("priya.qa")).raise_for_status()
    case = c.get(f"/api/cases/{case_id}", headers=env.h("priya.qa")).json()
    result = score(s, case, env.inventory(), duplicate, len(c.get("/api/cases", headers=env.h("priya.qa")).json()))
    return result | {"llm": llm, "known_gap": s.get("known_gap")}


def score(s: dict, case: dict, inventory: dict[str, set[str]], duplicate: bool | None, case_count: int) -> dict:
    exp = s["expect"]
    actual = {d["batch_id"]: d["decision"] for d in case["batch_decisions"]}
    held = {a["target"]["batch_id"] for a in case["actions"] if a["type"] == "PLACE_HOLD"}
    problems = []

    if case["status"] not in exp["status"]:
        problems.append(f"status {case['status']} not in {exp['status']}")
    correct = 0
    for batch, allowed in exp["decisions"].items():
        if actual.get(batch) in allowed:
            correct += 1
        else:
            problems.append(f"{batch}: {actual.get(batch)} not in {allowed}")
    unexpected = sorted(set(actual) - set(exp["decisions"]))
    if unexpected:
        problems.append(f"unexpected batches traced: {unexpected}")
    false_holds = sorted(b for b in exp["untouched"] if b in held or "HELD" in inventory.get(b, set()))
    if false_holds:
        problems.append(f"held but should be untouched: {false_holds}")
    verified_holds = {a["target"]["batch_id"] for a in case["actions"] if a["type"] == "PLACE_HOLD" and a["status"] == "VERIFIED"}
    not_held = sorted(set(exp.get("must_hold", [])) - verified_holds)
    if not_held:
        problems.append(f"no verified protective hold on: {not_held}")
    if exp.get("verify_failed") and not any(a["status"] == "VERIFY_FAILED" for a in case["actions"]):
        problems.append("expected a VERIFY_FAILED action")
    if exp.get("duplicate") and not (duplicate and case_count == 1):
        problems.append("repeat ingest did not return the existing case")

    expected_affected = {b for b, allowed in exp["decisions"].items() if any(a in AFFECTED for a in allowed if a)}
    found = {b for b in expected_affected if actual.get(b) in AFFECTED}
    return {
        "id": s["id"], "title": s["title"], "passed": not problems, "problems": problems,
        "status": case["status"], "decisions": actual, "held": sorted(held),
        "removal_requested": sorted({a["target"]["batch_id"] for a in case["actions"] if a["type"] == "REMOVE_FROM_SHIPMENT"}),
        "expected_decisions": len(exp["decisions"]), "correct_decisions": correct,
        "expected_affected": len(expected_affected), "affected_found": len(found), "false_holds": len(false_holds),
        # escalating is right when ESCALATED is an allowed outcome; not escalating is right unless it was required
        "escalation_required": exp["status"] == ["ESCALATED"], "escalated": case["status"] == "ESCALATED",
        "escalation_correct": ("ESCALATED" in exp["status"]) if case["status"] == "ESCALATED" else exp["status"] != ["ESCALATED"],
        "agent_seconds": case["metrics"]["elapsed_seconds"],
        "extraction_model": (case["extraction"] or {}).get("model"),
    }


def summarize(results: list[dict], mode: str) -> dict:
    n = len(results)
    ratio = lambda a, b: round(a / b, 4) if b else None  # noqa: E731
    seconds = [r["live_agent_seconds"] for r in results if r.get("live_agent_seconds") is not None]
    relevant = [r for r in results if r["escalation_required"] or r["escalated"]]
    return {
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "llm_mode": mode,
        "metrics": {
            "scenarios": n,
            "passed": sum(r["passed"] for r in results),
            "pass_rate": ratio(sum(r["passed"] for r in results), n),
            "decision_accuracy": ratio(sum(r["correct_decisions"] for r in results), sum(r["expected_decisions"] for r in results)),
            "batch_recall": ratio(sum(r["affected_found"] for r in results), sum(r["expected_affected"] for r in results)),
            "false_holds": sum(r["false_holds"] for r in results),
            "escalation_accuracy": ratio(sum(r["escalation_correct"] for r in relevant), len(relevant)),
            "known_gaps": sum(bool(r.get("known_gap")) and not r["passed"] for r in results),
            "agent_median_seconds": round(statistics.median(seconds), 3) if seconds else None,
        },
        "results": results,
    }


def run_suite(only: list[str] | None = None, record_missing: bool = False, results_path: Path | None = None) -> dict:
    if record_missing:
        load_dotenv()  # ANTHROPIC_API_KEY from the repo .env, only when we may call Claude
    scenarios = [s for s in load_scenarios() if not only or s["id"] in only]
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(Path(tmp))
        try:
            for s in scenarios:
                # "live" only when Claude is really called; agent_seconds from replays are not real latency
                llm = "live" if record_missing and not fixture_exists(s) else "replay"
                env.set_llm_mode("record" if llm == "live" else "mock")
                results.append(run_one(env, s, llm))
        finally:
            env.close()
    # Real latency only comes from live Claude calls; a replay run keeps each scenario's last live measurement.
    prior = {}
    if results_path and results_path.exists():
        prior = {p["id"]: p.get("live_agent_seconds", p["agent_seconds"] if p.get("llm") == "live" else None)
                 for p in json.loads(results_path.read_text(encoding="utf-8"))["results"]}
    for res in results:
        res["live_agent_seconds"] = res["agent_seconds"] if res["llm"] == "live" else prior.get(res["id"])
    summary = summarize(results, "record-missing" if record_missing else "mock")
    if results_path:
        results_path.parent.mkdir(parents=True, exist_ok=True)
        results_path.write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--only", help="comma-separated scenario ids")
    p.add_argument("--record-missing", action="store_true", help="call Claude for notices with no recording (costs money)")
    p.add_argument("--save", action="store_true", help="write scenarios/results/latest.json (always on with --record-missing)")
    args = p.parse_args(argv)
    save = args.save or args.record_missing  # keep the last real run unless asked; replays have no real latency
    summary = run_suite(args.only.split(",") if args.only else None, args.record_missing, RESULTS if save else None)
    for r in summary["results"]:
        label = "PASS" if r["passed"] else ("GAP " if r["known_gap"] else "FAIL")
        print(f"{label} {r['id']} {r['status']:18} {r['title']}")
        for problem in r["problems"] if not r["passed"] else []:
            print(f"       - {problem}")
        if r["known_gap"] and not r["passed"]:
            print(f"       known gap: {r['known_gap']}")
    print(json.dumps(summary["metrics"], indent=1))
    unexpected = [r["id"] for r in summary["results"] if r["passed"] == bool(r["known_gap"])]
    if unexpected:
        print(f"Unexpected results (failure without a known gap, or a known gap now passing): {unexpected}")
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(main())
