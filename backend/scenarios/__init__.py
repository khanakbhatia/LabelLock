"""Eval scenarios: notices with expected outcomes. See runner.py."""
import json
from pathlib import Path

SCENARIOS = Path(__file__).with_name("scenarios.json")


def load_scenarios() -> list[dict]:
    return json.loads(SCENARIOS.read_text(encoding="utf-8"))
