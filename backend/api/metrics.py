"""ROI: measured figures (eval results, timed runs) kept apart from editable assumptions."""
import json
import statistics
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import require_roles
from api.db import Benchmark, User, get_db, new_id, now_iso
from api.errors import ApiError
from scenarios import load_scenarios

router = APIRouter(prefix="/api")
ROLES = ("qa_specialist", "qa_manager", "admin")


class BenchmarkBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str = Field(min_length=1)
    mode: Literal["manual", "agent"]
    seconds: float = Field(ge=0)
    batches_found: int = Field(ge=0)
    false_holds: int = Field(ge=0)
    operator: str = Field(min_length=1)


def benchmark_out(b: Benchmark) -> dict:
    return {"id": b.id, "created_at": b.created_at, "scenario_id": b.scenario_id, "mode": b.mode, "seconds": b.seconds,
            "batches_found": b.batches_found, "false_holds": b.false_holds, "operator": b.operator}


@router.post("/benchmarks", status_code=201)
def log_benchmark(body: BenchmarkBody, user: User = Depends(require_roles(*ROLES)), db: Session = Depends(get_db)):
    if body.scenario_id not in {s["id"] for s in load_scenarios()}:
        raise ApiError(422, "VALIDATION_ERROR", f"Unknown scenario {body.scenario_id}",
                       {"fields": [{"field": "body.scenario_id", "message": "not a scenario in backend/scenarios"}]})
    b = Benchmark(id=new_id("b"), created_at=now_iso(), **body.model_dump())
    db.add(b)
    db.commit()
    return benchmark_out(b)


def median(values: list[float]) -> float | None:
    return round(statistics.median(values), 3) if values else None


@router.get("/metrics/roi")
def roi(request: Request, user: User = Depends(require_roles(*ROLES)), db: Session = Depends(get_db)):
    settings = request.app.state.settings
    runs = list(db.scalars(select(Benchmark)))
    manual = [b.seconds for b in runs if b.mode == "manual"]
    agent = [b.seconds for b in runs if b.mode == "agent"]
    eval_metrics = {}
    if settings.eval_results_path.exists():
        last = json.loads(settings.eval_results_path.read_text(encoding="utf-8"))
        eval_metrics = {k: v for k, v in last["metrics"].items() if isinstance(v, (int, float)) or v is None}
        # only scenarios where Claude was really called; replayed extractions are not real agent latency
        agent += [r["live_agent_seconds"] for r in last["results"] if r.get("live_agent_seconds") is not None]
    assumptions = json.loads(settings.roi_assumptions_path.read_text(encoding="utf-8"))["assumptions"]
    return {
        "measured": {"manual_runs": len(manual), "agent_runs": len(agent),
                     "manual_median_seconds": median(manual), "agent_median_seconds": median(agent), "eval": eval_metrics},
        "assumptions": assumptions,
    }
