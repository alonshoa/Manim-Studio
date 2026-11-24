"""Synthetic data for the time panel's UI test. No model calls."""

import json
import sys
import time
from pathlib import Path

from manim_studio.research import ResearchLog
from manim_studio.research_time import ResearchTiming

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.test_research_time import FakeClock

root = Path(sys.argv[1]).resolve()
root.mkdir(parents=True, exist_ok=True)
log = ResearchLog(root)
if log.database.exists():
    raise SystemExit("Refusing an existing ledger")
log.configure(True)
session = log.start_session("וקטורים — ניסיון 01")
other = log.start_session("מדדי מרכז — ניסיון 02")
clock = FakeClock()
clock.epoch = time.time() - 600
timing = ResearchTiming(root, clock)
started = timing.dispatch(
    "start",
    {
        "session_id": session,
        "client_id": "demo",
        "expected_revision": 0,
        "request_id": "seed-start",
    },
)
for sequence in range(1, 9):
    clock.advance(15)
    timing.dispatch(
        "heartbeat",
        {
            "session_id": session,
            "client_id": "demo",
            "interval_id": started["active"]["interval_id"],
            "sequence": sequence,
            "request_id": f"seed-heartbeat-{sequence}",
        },
    )
timing.dispatch(
    "stop",
    {
        "session_id": session,
        "client_id": "demo",
        "interval_id": started["active"]["interval_id"],
        "expected_revision": 1,
        "request_id": "seed-stop",
    },
)
timing.dispatch(
    "report",
    {
        "session_id": session,
        "category": "classification",
        "seconds": 35,
        "request_id": "seed-report",
    },
)
timing.dispatch(
    "observe_context",
    {
        "session_id": session,
        "client_id": "demo",
        "extension_version": "0.1.0",
        "model": {"model": "synthetic-demo", "version": "fixture"},
        "request_id": "seed-context",
    },
)
print(
    json.dumps({"session_id": session, "other_session_id": other}, ensure_ascii=False)
)
