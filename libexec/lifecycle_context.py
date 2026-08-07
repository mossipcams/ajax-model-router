#!/usr/bin/env python3
"""Normalized execution context for cross-harness DELEGATE transactions."""

from __future__ import annotations

import json
from pathlib import Path

import model_registry as registry

CALLERS = registry.CALLERS
TRANSPORTS = registry.TRANSPORTS
HARNESSES = TRANSPORTS  # legacy alias = supported transports only

STAGES = (
    "before_execute",
    "snapshot",
    "execute",
    "after_execute",
    "log_outcome",
)

# Stages that spend model tokens; everything before must fail closed first.
TOKEN_STAGES = frozenset({"execute"})

REQUIRED_FIELDS = (
    "task_id",
    "caller_harness",
    "target_transport",
    "model",
    "task",
    "allowed_files",
    "acceptance",
    "verification",
    "stop_if",
    "working_directory",
    "snapshot_directory",
)

EVIDENCE_NAME = "evidence.json"
CONTEXT_STATE_NAME = "context.json"


class ContextError(ValueError):
    """Invalid or incomplete execution context."""


def _require_str(value, field):
    if not isinstance(value, str):
        raise ContextError(f"{field} must be a string")
    return value


def _require_str_list(value, field):
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ContextError(f"{field} must be a list of strings")
    return list(value)


def normalize_path(path, *, base=None):
    """Normalize to an absolute path; reject empty and parent escapes in relatives."""
    if isinstance(path, Path):
        candidate = path
        if not candidate.is_absolute():
            if ".." in candidate.parts:
                raise ContextError(f"unsafe relative path: {candidate}")
            root = Path(base) if base else Path.cwd()
            candidate = root / candidate
        return candidate.resolve()
    text = _require_str(path, "path").strip()
    if not text:
        raise ContextError("path must be non-empty")
    candidate = Path(text)
    if not candidate.is_absolute():
        if ".." in candidate.parts:
            raise ContextError(f"unsafe relative path: {text}")
        root = Path(base) if base else Path.cwd()
        candidate = root / candidate
    return candidate.resolve()


def normalize_allowed_files(paths, working_directory):
    """Return repo-relative POSIX paths under working_directory."""
    root = normalize_path(working_directory)
    normalized = []
    for raw in _require_str_list(paths, "allowed_files"):
        path = Path(raw)
        if path.is_absolute():
            try:
                relative = path.resolve().relative_to(root)
            except ValueError as error:
                raise ContextError(f"allowed file outside working_directory: {raw}") from error
        else:
            if ".." in path.parts:
                raise ContextError(f"unsafe allowed file path: {raw}")
            relative = path
        text = relative.as_posix()
        if not text or text == ".":
            raise ContextError(f"invalid allowed file path: {raw}")
        normalized.append(text)
    return sorted(set(normalized))


def empty_artifacts():
    return {
        "prompt_path": "",
        "raw_log": "",
        "report_path": "",
        "delegate_output": {},
        "verification_results": [],
        "scope_violations": [],
        "changed_files": [],
        "delta_json": "",
        "delta_patch": "",
        "token_usage": "UNKNOWN",
        "provider_metadata": {},
        "routing_decision": {},
    }


def load_context(path):
    path = Path(path)
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ContextError(f"invalid context JSON: {error}") from error
    return validate_context(data)


def validate_context(data):
    if not isinstance(data, dict):
        raise ContextError("context must be a JSON object")

    data = dict(data)
    # Prefer new names; accept prior CURRENT/TARGET_HARNESS and agent aliases.
    if "caller_harness" not in data and "current_harness" in data:
        data["caller_harness"] = data["current_harness"]
    if "target_transport" not in data and "target_harness" in data:
        data["target_transport"] = data["target_harness"]
    if "target_transport" not in data and "agent" in data:
        agent = str(data.get("agent") or "").strip().lower()
        if agent in TRANSPORTS:
            data["target_transport"] = agent
    if "task" not in data and "user_request" in data:
        data["task"] = data.get("user_request") or ""
    if "verification" not in data and "verify" in data:
        data["verification"] = data.get("verify") or []
    if "stop_if" not in data:
        data["stop_if"] = list(data.get("stop_if") or [])

    missing = [field for field in REQUIRED_FIELDS if field not in data]
    if missing:
        raise ContextError(f"missing required fields: {', '.join(missing)}")

    ctx = {field: data[field] for field in REQUIRED_FIELDS}
    ctx["task_id"] = _require_str(ctx["task_id"], "task_id").strip()
    if not ctx["task_id"]:
        raise ContextError("task_id must be non-empty")

    caller = _require_str(ctx["caller_harness"], "caller_harness").strip().lower()
    if caller not in CALLERS:
        raise ContextError(f"caller_harness must be one of {CALLERS}")
    ctx["caller_harness"] = caller

    transport = _require_str(ctx["target_transport"], "target_transport").strip().lower()
    if transport not in TRANSPORTS:
        raise ContextError(f"target_transport must be one of {TRANSPORTS}")
    ctx["target_transport"] = transport

    # Mirrors for older hooks / outcome logging.
    ctx["current_harness"] = caller
    ctx["target_harness"] = transport

    ctx["model"] = _require_str(ctx["model"], "model")
    if not ctx["model"].strip():
        raise ContextError("model must be non-empty for DELEGATE transactions")
    ctx["model"] = ctx["model"].strip()

    ctx["task"] = _require_str(ctx["task"], "task")
    working = normalize_path(ctx["working_directory"])
    ctx["working_directory"] = str(working)
    snapshot = normalize_path(ctx["snapshot_directory"], base=working)
    ctx["snapshot_directory"] = str(snapshot)
    ctx["allowed_files"] = normalize_allowed_files(ctx["allowed_files"], working)
    ctx["acceptance"] = _require_str_list(ctx["acceptance"], "acceptance")
    ctx["verification"] = _require_str_list(ctx["verification"], "verification")
    ctx["stop_if"] = _require_str_list(ctx["stop_if"], "stop_if")

    for key in (
        "tool",
        "repository_id",
        "requested_harness",
        "gate_result",
        "failure_classification",
        "duration_seconds",
        "resume",
        "sandbox",
        "reasoning_effort",
        "outcome_log",
        "user_request",
        "fallback",
        "requested_agent",
        "agent",
        "risk",
    ):
        if key in data and data[key] is not None:
            ctx[key] = _require_str(data[key], key)

    for key in ("follow_up", "verify"):
        if key in data and data[key] is not None:
            ctx[key] = _require_str_list(data[key], key)

    ctx.setdefault("follow_up", [])
    ctx.setdefault("tool", ctx["target_transport"])
    ctx.setdefault("requested_harness", ctx["target_transport"])
    ctx.setdefault("agent", ctx["target_transport"])
    ctx.setdefault(
        "requested_agent", ctx.get("requested_harness") or ctx["target_transport"]
    )
    ctx.setdefault("verify", list(ctx["verification"]))
    ctx.setdefault("user_request", ctx["task"])
    ctx.setdefault("retry_count", int(data.get("retry_count", 0)))
    if not isinstance(ctx["retry_count"], int) or ctx["retry_count"] < 0:
        raise ContextError("retry_count must be a non-negative integer")

    ctx.setdefault("status", data.get("status", "NEW"))
    ctx.setdefault("completed_stages", list(data.get("completed_stages", [])))
    if not isinstance(ctx["completed_stages"], list):
        raise ContextError("completed_stages must be a list")

    artifacts = empty_artifacts()
    incoming = data.get("artifacts") or {}
    if not isinstance(incoming, dict):
        raise ContextError("artifacts must be an object")
    artifacts.update({key: incoming[key] for key in artifacts if key in incoming})
    ctx["artifacts"] = artifacts

    timeout = data.get("timeout_seconds", 900)
    if not isinstance(timeout, (int, float)) or not 0 < float(timeout) <= 86400:
        raise ContextError("timeout_seconds must be between 0 and 86400")
    ctx["timeout_seconds"] = float(timeout)

    return ctx


def save_context(ctx, path=None):
    path = Path(path or Path(ctx["snapshot_directory"]) / CONTEXT_STATE_NAME)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(ctx, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)
    return path


def evidence_path(ctx):
    return Path(ctx["snapshot_directory"]) / EVIDENCE_NAME


def load_evidence(ctx):
    path = evidence_path(ctx)
    if not path.exists():
        return {"version": 1, "root": ctx["working_directory"], "artifacts": {}}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ContextError(f"invalid evidence index: {error}") from error
    if not isinstance(data, dict):
        raise ContextError("evidence index must be an object")
    data.setdefault("version", 1)
    data.setdefault("root", ctx["working_directory"])
    data.setdefault("artifacts", {})
    return data


def save_evidence(ctx, evidence):
    path = evidence_path(ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)
    return path


def artifact_fresh(evidence, name, *, root, path):
    """True when a recorded deterministic artifact still points at a usable file."""
    entry = (evidence.get("artifacts") or {}).get(name)
    if not entry:
        return False
    if Path(entry.get("root") or "").resolve() != Path(root).resolve():
        return False
    recorded = entry.get("path")
    if not recorded or Path(recorded).resolve() != Path(path).resolve():
        return False
    return Path(recorded).is_file()


def record_artifact(evidence, name, *, root, path, meta=None):
    evidence.setdefault("artifacts", {})[name] = {
        "root": root,
        "path": str(path),
        "meta": meta or {},
    }
    return evidence


def stage_index(name):
    try:
        return STAGES.index(name)
    except ValueError as error:
        raise ContextError(f"unknown stage: {name}") from error
