"""Small provider adapters for native delegate JSONL streams."""

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


def _message_event(source, record):
    text = _text(record)
    report_text = (
        text
        if "ROUTER_REPORT_BEGIN" in text and "ROUTER_REPORT_END" in text
        else ""
    )
    return NormalizedEvent("message/progress", source, record, text, report_text)


def normalize_record(source, record):
    if not isinstance(record, dict):
        return None
    event_type = record.get("type")
    if source == "pi":
        if event_type == "agent_start":
            return NormalizedEvent("started", source, record)
        if event_type == "agent_settled":
            return NormalizedEvent("completed", source, record)
        if event_type in {"tool_execution_start"}:
            return NormalizedEvent("activity/tool started", source, record)
        if event_type in {"tool_execution_end"}:
            return NormalizedEvent("activity/tool finished", source, record)
        if event_type in {"message_start", "message_update", "message_end", "message"}:
            return _message_event(source, record)
        if event_type in {"error", "agent_error"}:
            return NormalizedEvent("failed", source, record, error=_text(record))
        return None

    if source == "cursor":
        if event_type == "system" and record.get("subtype") in {"init", "started"}:
            return NormalizedEvent("started", source, record)
        if event_type == "tool_call":
            subtype = str(record.get("subtype", "")).lower()
            if subtype in {"start", "started", "begin", "pending"}:
                return NormalizedEvent("activity/tool started", source, record)
            if subtype in {"end", "ended", "complete", "completed", "success"}:
                return NormalizedEvent("activity/tool finished", source, record)
            return _message_event(source, record)
        if event_type in {"assistant", "message", "text", "content", "progress"}:
            return _message_event(source, record)
        if event_type in {"error", "failed"}:
            return NormalizedEvent("failed", source, record, error=_text(record))
        if event_type == "result":
            text = _text(record)
            report_text = (
                text
                if "ROUTER_REPORT_BEGIN" in text and "ROUTER_REPORT_END" in text
                else ""
            )
            failed = bool(record.get("is_error")) or str(record.get("subtype", "")).lower() in {
                "error",
                "failed",
            }
            return NormalizedEvent(
                "failed" if failed else "completed",
                source,
                record,
                text,
                report_text,
                text if failed else "",
            )
    return None
