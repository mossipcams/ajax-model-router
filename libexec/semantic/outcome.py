"""Extend router-log with optional semantic routing event sidecar."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def default_events_path(tsv_log: str | Path) -> Path:
    tsv = Path(tsv_log)
    return tsv.parent / "routing-events.jsonl"


def append_routing_event(
    *,
    tsv_log: str | Path,
    requested_agent: str,
    actual_agent: str,
    decision: dict[str, Any] | None = None,
    explanation: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write one JSONL routing event beside the TSV log."""
    events_path = default_events_path(tsv_log)
    events_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "requested_agent": requested_agent,
        "actual_agent": actual_agent,
        "decision": decision,
        "explanation": explanation,
    }
    if extra:
        record.update(extra)
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return events_path
