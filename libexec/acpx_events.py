"""Normalize acpx --format json ACP NDJSON lines for delegate runners."""

from dataclasses import dataclass
import json


@dataclass(frozen=True)
class NormalizedEvent:
    kind: str
    source: str
    raw: dict
    text: str = ""
    report_text: str = ""
    error: str = ""


def parse_jsonl_line(line):
    try:
        value = json.loads(line)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(filter(None, (_text(item) for item in value)))
    if not isinstance(value, dict):
        return ""
    for key in ("text", "delta", "content", "message", "result", "output", "error"):
        text = _text(value.get(key))
        if text:
            return text
    return ""


def _report_text(text):
    if "ROUTER_REPORT_BEGIN" in text and "ROUTER_REPORT_END" in text:
        return text
    return ""


def normalize_record(record):
    if not isinstance(record, dict):
        return None

    if record.get("method") == "session/update":
        params = record.get("params") or {}
        update = str(params.get("sessionUpdate", ""))
        if update == "agent_message_chunk":
            text = _text(params.get("content"))
            return NormalizedEvent(
                "message/progress",
                "acpx",
                record,
                text,
                _report_text(text),
            )
        if update in {"tool_call", "tool_call_update"}:
            status = str((params.get("status") or params.get("toolCall") or {}).get("status", "")).lower()
            if status in {"pending", "in_progress", "running", "started"}:
                return NormalizedEvent("activity/tool started", "acpx", record)
            if status in {"completed", "finished", "success"}:
                return NormalizedEvent("activity/tool finished", "acpx", record)
        if update in {"agent_thought_chunk", "plan_update"}:
            return NormalizedEvent("message/progress", "acpx", record, _text(params))
        return None

    if "error" in record:
        error = record.get("error") or {}
        message = error.get("message") if isinstance(error, dict) else str(error)
        return NormalizedEvent("failed", "acpx", record, error=message or "acpx ACP error")

    result = record.get("result")
    if result is not None and record.get("id") is not None:
        if isinstance(result, dict) and result.get("stopReason"):
            return NormalizedEvent("completed", "acpx", record)
        if isinstance(result, dict) and result.get("status") in {"failed", "cancelled"}:
            return NormalizedEvent(
                "failed",
                "acpx",
                record,
                error=str(result.get("error") or result.get("status")),
            )
    return None
