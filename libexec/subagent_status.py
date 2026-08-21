"""Normalize acpx child ACP streams into Ajax Chat subagent_status events."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable

from acpx_events import _tool_status, _update_body, parse_jsonl_line

TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})
STATES = TERMINAL_STATES | frozenset(
    {
        "queued",
        "starting",
        "running",
        "tool_call",
        "waiting_for_permission",
        "stalled",
    }
)


def utc_now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " ".join(filter(None, (_text(item) for item in value)))
    if not isinstance(value, dict):
        return ""
    for key in ("text", "title", "name", "path", "description", "message", "detail"):
        text = _text(value.get(key))
        if text:
            return text
    return ""


def _effective_tool_body(body):
    if not isinstance(body, dict):
        return {}
    nested = body.get("toolCall")
    if isinstance(nested, dict):
        merged = dict(nested)
        for key, value in body.items():
            if key != "toolCall":
                merged.setdefault(key, value)
        return merged
    return body


def _paths_from_locations(body):
    paths = []
    locations = body.get("locations")
    if isinstance(locations, list):
        for item in locations:
            if isinstance(item, dict):
                path = _text(item.get("path") or item.get("uri") or item.get("file"))
                if path:
                    paths.append(path)
    return paths


def _tool_detail(body):
    body = _effective_tool_body(body if isinstance(body, dict) else {})
    title = _text(body.get("title"))
    tool = _text(body.get("toolName") or body.get("tool") or body.get("kind"))
    path = _text(body.get("path") or body.get("file") or body.get("uri"))
    for loc_path in _paths_from_locations(body):
        if loc_path and loc_path not in (path, title):
            path = f"{path} {loc_path}".strip() if path else loc_path
    if title:
        parts = [title]
        if path and path not in title:
            parts.append(path)
    else:
        parts = [part for part in (tool, path) if part]
    if parts:
        return " ".join(parts)
    return _text(body) or "tool activity"


def map_acp_record(record, *, current_state="running"):
    """Map one raw ACP JSON object to (state, detail) or None when unchanged."""
    if not isinstance(record, dict):
        return None

    if record.get("method") == "session/request_permission":
        params = record.get("params") or {}
        detail = _tool_detail(params) or "Permission required"
        return "waiting_for_permission", detail

    if record.get("method") == "session/update":
        body = _update_body(record.get("params") or {})
        update = str(body.get("sessionUpdate", ""))
        if update == "agent_message_chunk":
            return "running", "Generating response"
        if update in {"agent_thought_chunk", "plan_update"}:
            return "running", "Planning"
        if update in {"tool_call", "tool_call_update"}:
            status = _tool_status(body)
            detail = _tool_detail(body)
            if status in {"awaiting_permission", "waiting_for_permission", "needs_permission"}:
                return "waiting_for_permission", detail
            if status in {"pending", "in_progress", "running", "started"}:
                if current_state == "tool_call" and (not detail or detail == "tool activity"):
                    return None
                return "tool_call", detail
            if status in {"completed", "finished", "success"}:
                if current_state == "tool_call":
                    return "running", "Tool finished"
                return None
        if update in {"permission_request", "request_permission"}:
            return "waiting_for_permission", _tool_detail(body) or "Permission required"
        return None

    if "error" in record:
        error = record.get("error") or {}
        message = error.get("message") if isinstance(error, dict) else str(error)
        return "failed", message or "ACP error"

    result = record.get("result")
    if result is not None and record.get("id") is not None:
        if isinstance(result, dict) and result.get("stopReason"):
            return "completed", "Finished"
        if isinstance(result, dict) and result.get("status") in {"failed", "cancelled"}:
            state = "cancelled" if result.get("status") == "cancelled" else "failed"
            return state, str(result.get("error") or result.get("status"))
    return None


@dataclass
class SubagentStatusTracker:
    run_id: str
    parent_task_id: str
    harness: str
    model: str
    task: str
    emit: Callable[[dict], None] | None = None
    stall_seconds: float = 60.0
    state: str = "queued"
    detail: str = ""
    last_event_monotonic: float = field(default_factory=time.monotonic)

    def __post_init__(self):
        if self.state not in STATES:
            raise ValueError(f"invalid initial state: {self.state}")

    def event(self, state, detail=""):
        if state not in STATES:
            raise ValueError(f"invalid state: {state}")
        override_completed = (
            self.state == "completed" and state in {"failed", "cancelled"}
        )
        if self.state in TERMINAL_STATES:
            if state not in TERMINAL_STATES:
                return None
            if not override_completed:
                if state == self.state and detail == self.detail:
                    return None
                return None
        elif state == self.state and detail == self.detail:
            return None
        self.state = state
        self.detail = detail
        self.last_event_monotonic = time.monotonic()
        payload = {
            "type": "subagent_status",
            "runId": self.run_id,
            "parentTaskId": self.parent_task_id,
            "harness": self.harness,
            "model": self.model,
            "task": self.task,
            "state": state,
            "detail": detail,
            "timestamp": utc_now_iso(),
        }
        if self.emit:
            self.emit(payload)
        return payload

    def handle_stdout_line(self, line):
        record = parse_jsonl_line(line)
        if record is None:
            return None
        mapped = map_acp_record(record, current_state=self.state)
        if mapped is None:
            return None
        state, detail = mapped
        return self.event(state, detail)

    def maybe_stalled(self, now=None):
        now = now if now is not None else time.monotonic()
        if self.state in TERMINAL_STATES:
            return None
        if now - self.last_event_monotonic < self.stall_seconds:
            return None
        detail = self.detail or "No activity"
        return self.event("stalled", detail)

    def terminal(self, state, detail=""):
        if state not in TERMINAL_STATES:
            raise ValueError(f"terminal state required, got {state!r}")
        return self.event(state, detail)


def emit_ndjson(payload, stream=None):
    stream = stream or sys.stdout
    stream.write(json.dumps(payload, separators=(",", ":")) + "\n")
    stream.flush()


def is_subagent_status_line(line):
    record = parse_jsonl_line(line)
    return isinstance(record, dict) and record.get("type") == "subagent_status"


def forward_subagent_status_lines(lines: Iterable[str], stream=None):
    """Write subagent_status NDJSON lines to stream; return non-status tail."""
    tail = []
    for line in lines:
        if is_subagent_status_line(line):
            stream = stream or sys.stdout
            stream.write(line if line.endswith("\n") else line + "\n")
            stream.flush()
        else:
            tail.append(line)
    return tail
