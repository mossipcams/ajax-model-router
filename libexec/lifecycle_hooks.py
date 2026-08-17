#!/usr/bin/env python3
"""Thin router execute hooks — safety + transport only, never invoke an LLM for routing."""

from __future__ import annotations

import json
import os
import re
import subprocess
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import lifecycle_context as ctxlib
import router_state

ROOT = Path(__file__).resolve().parents[1]

DISPATCH_WRAPPER = """You are a bounded implementation worker for a parent agent.
Current directory is the task worktree.
You are already the selected implementation worker. Implement in-process.
Never spawn native Cursor Task, best-of-n, or any other subagent.
Never merge, rebase, force-push, or switch branches.
If the user explicitly requested a commit or pull request, you may create a branch when needed, commit, push, and run `gh pr create` after the repository's local verification gate. Otherwise never commit, push, or create branches.

Implement the requested outcome.
Allowed scope:
{scope}
Acceptance criteria:
{acceptance}
Investigate the repository as needed.
Choose the implementation approach.
Run appropriate verification.
Return changed files, verification results, and remaining concerns.
Stop if completing the task requires expanding beyond the allowed scope.

Return exactly this report between marker lines:
ROUTER_REPORT_BEGIN
DELEGATE_REPORT:
  STATUS: COMPLETE | BLOCKED | FAILED
  CHANGED_FILES: [<paths>]
  VERIFICATION:
    - TYPE: test | existing_test | build | typecheck | lint | static_analysis | integration | browser | manual | other
      COMMAND: <command or NONE>
      RESULT: pass | fail | skipped | blocked
      DETAILS: <short result note>
  CONCERNS: []
ROUTER_REPORT_END

"""


class HookError(RuntimeError):
    """Deterministic execute-hook failure."""


def _run_dir(ctx):
    path = Path(ctx["snapshot_directory"]) / "run"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _git_root(working_directory):
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=working_directory,
        text=True,
        capture_output=True,
        check=True,
    )
    return Path(result.stdout.strip()).resolve()


def _with_cwd(directory, fn):
    previous = Path.cwd()
    os.chdir(directory)
    try:
        return fn()
    finally:
        os.chdir(previous)


def _roots_equal(left, right):
    return Path(left).resolve() == Path(right).resolve()


def _bullet_lines(items):
    if not items:
        return "- (none)"
    return "\n".join(f"- {item}" for item in items)


def before_execute(ctx):
    """Normalize paths, prepare snapshot dir, reject unsafe context early."""
    working = Path(ctx["working_directory"])
    if not working.is_dir():
        raise HookError(f"working_directory does not exist: {working}")

    root = _git_root(working)
    if root != working.resolve():
        raise HookError(
            f"working_directory must be the git toplevel ({root}), got {working.resolve()}"
        )

    if ctx["agent"] == "parent":
        raise HookError("parent agent does not use write execute hooks")

    if not ctx["allowed_files"]:
        raise HookError("allowed_files must be non-empty for write execute")

    if not (ctx.get("user_request") or "").strip() and not ctx["acceptance"]:
        raise HookError("user_request or acceptance is required")

    snapshot = Path(ctx["snapshot_directory"])
    snapshot.mkdir(parents=True, exist_ok=True)

    evidence = ctxlib.load_evidence(ctx)
    if evidence.get("root") and not _roots_equal(evidence["root"], working.resolve()):
        raise HookError("evidence index root mismatch; refusing reuse")
    evidence["root"] = str(working.resolve())
    ctxlib.save_evidence(ctx, evidence)

    # Build outcome prompt once; parent owns planning, delegate owns investigation.
    run = _run_dir(ctx)
    prompt = DISPATCH_WRAPPER.format(
        scope=_bullet_lines(ctx["allowed_files"]),
        acceptance=_bullet_lines(ctx["acceptance"]),
    )
    request = (ctx.get("user_request") or "").strip()
    if request:
        prompt += f"Requested outcome:\n{request}\n\n"
    if ctx.get("verify"):
        prompt += "Verification expectation:\n" + _bullet_lines(ctx["verify"]) + "\n"

    prompt_path = run / "prompt.txt"
    prompt_path.write_text(prompt)
    ctx["artifacts"]["prompt_path"] = str(prompt_path)
    ctx["status"] = "BEFORE_EXECUTE_OK"
    return ctx


def snapshot(ctx):
    """Create or reuse pre-execute snapshot."""
    snapshot_dir = Path(ctx["snapshot_directory"])
    pre_path = snapshot_dir / "pre.json"
    evidence = ctxlib.load_evidence(ctx)
    root = ctx["working_directory"]

    if ctxlib.artifact_fresh(evidence, "pre_snapshot", root=root, path=pre_path):
        try:
            manifest = router_state.load_manifest(snapshot_dir, "pre")
        except RuntimeError:
            manifest = None
        if manifest and _roots_equal(manifest.get("root"), root):
            ctx["status"] = "SNAPSHOT_REUSED"
            return ctx

    def capture_pre():
        router_state.capture(snapshot_dir, "pre", quiet=True)

    _with_cwd(root, capture_pre)
    manifest = router_state.load_manifest(snapshot_dir, "pre")
    evidence_root = manifest.get("root") or root
    evidence["root"] = evidence_root
    ctxlib.record_artifact(evidence, "pre_snapshot", root=evidence_root, path=pre_path)
    ctx["working_directory"] = evidence_root
    ctxlib.save_evidence(ctx, evidence)
    ctx["status"] = "SNAPSHOT_OK"
    return ctx


def _tool_for(ctx):
    tool = (ctx.get("tool") or ctx.get("agent") or "").strip().lower()
    mapping = {
        "cursor": "cursor",
        "pi": "pi",
        "codex": "codex",
        "minimax": "pi",
        "glm": "pi",
    }
    if tool not in mapping:
        raise HookError(f"unsupported tool/agent for execute: {tool!r}")
    return mapping[tool]


def execute(ctx):
    run = _run_dir(ctx)
    prompt_path = Path(ctx["artifacts"]["prompt_path"])
    if not prompt_path.is_file():
        raise HookError("prompt_path missing; refuse to spend tokens")
    raw_log = run / "raw.log"
    report = run / "report.yaml"
    tool = _tool_for(ctx)
    command = [
        str(ROOT / "scripts" / "run-delegate"),
        "--tool",
        tool,
        "--model",
        ctx["model"],
        "--prompt",
        str(prompt_path),
        "--raw-log",
        str(raw_log),
        "--report",
        str(report),
        "--timeout-seconds",
        str(ctx["timeout_seconds"]),
    ]
    if ctx.get("resume"):
        command.extend(["--resume", ctx["resume"]])
    for item in ctx.get("follow_up") or []:
        command.extend(["--follow-up", item])
    if tool == "codex":
        command.extend(["--sandbox", ctx.get("sandbox") or "workspace-write"])
        if ctx.get("reasoning_effort"):
            command.extend(["--reasoning-effort", ctx["reasoning_effort"]])
        else:
            command.extend(["--reasoning-effort", "xhigh"])

    result = subprocess.run(
        command,
        cwd=ctx["working_directory"],
        text=True,
        capture_output=True,
    )
    ctx["artifacts"]["raw_log"] = str(raw_log)
    ctx["artifacts"]["report_path"] = str(report)
    ctx["artifacts"]["provider_metadata"] = {
        "exit_code": result.returncode,
        "stdout_tail": (result.stdout or "")[-2000:],
        "stderr_tail": (result.stderr or "")[-2000:],
    }
    ctx["artifacts"]["token_usage"] = ctx["artifacts"].get("token_usage") or "UNKNOWN"
    if result.returncode not in (0,) and not report.is_file():
        raise HookError(
            f"delegate transport failed ({result.returncode}): "
            f"{(result.stderr or result.stdout or '').strip()[:500]}"
        )
    ctx["status"] = "EXECUTED"
    return ctx


def _parse_report_compact(report_text):
    """Extract a compact dict from DELEGATE_REPORT — no narrative."""
    out = {
        "status": "UNKNOWN",
        "changed_files": [],
        "concerns": [],
        "verification": [],
    }
    if not report_text:
        return out

    def list_field(name):
        match = re.search(rf"^\s*{name}:\s*\[(.*)\]\s*$", report_text, re.M)
        if not match:
            return []
        inner = match.group(1).strip()
        if not inner:
            return []
        return [part.strip().strip("'\"") for part in inner.split(",") if part.strip()]

    status = re.search(r"^\s*STATUS:\s*(\S+)", report_text, re.M)
    if status:
        out["status"] = status.group(1)
    out["changed_files"] = list_field("CHANGED_FILES") or list_field("FILES_CHANGED")
    out["concerns"] = list_field("CONCERNS")
    types = re.findall(
        r"^\s*- TYPE:\s*(test|existing_test|build|typecheck|lint|static_analysis|integration|browser|manual|other)\s*$",
        report_text,
        re.M,
    )
    results = re.findall(r"^\s*RESULT:\s*(pass|fail|skipped|blocked)\s*$", report_text, re.M)
    for index, kind in enumerate(types):
        entry = {"type": kind, "result": results[index] if index < len(results) else "unknown"}
        out["verification"].append(entry)
    return out


def after_execute(ctx):
    snapshot_dir = Path(ctx["snapshot_directory"])
    evidence = ctxlib.load_evidence(ctx)
    root = ctx["working_directory"]
    post_path = snapshot_dir / "post.json"

    if not ctxlib.artifact_fresh(evidence, "post_snapshot", root=root, path=post_path):

        def capture_post():
            router_state.capture(snapshot_dir, "post", quiet=True)

        _with_cwd(root, capture_post)
        manifest = router_state.load_manifest(snapshot_dir, "post")
        evidence_root = manifest.get("root") or root
        ctxlib.record_artifact(evidence, "post_snapshot", root=evidence_root, path=post_path)

    def inspect_delta():
        with redirect_stdout(StringIO()):
            router_state.inspect(snapshot_dir, ctx["allowed_files"])

    _with_cwd(root, inspect_delta)

    delta_json = snapshot_dir / "delta.json"
    delta_patch = snapshot_dir / "delta.patch"
    delta = json.loads(delta_json.read_text()) if delta_json.is_file() else {}
    ctx["artifacts"]["delta_json"] = str(delta_json)
    ctx["artifacts"]["delta_patch"] = str(delta_patch)
    ctx["artifacts"]["changed_files"] = list(delta.get("delegate_paths") or [])
    ctx["artifacts"]["scope_violations"] = list(delta.get("scope_violations") or [])

    report_path = Path(ctx["artifacts"].get("report_path") or "")
    report_text = report_path.read_text() if report_path.is_file() else ""
    compact = _parse_report_compact(report_text)
    compact["scope_violations"] = ctx["artifacts"]["scope_violations"]
    compact["changed_files"] = ctx["artifacts"]["changed_files"] or compact.get(
        "changed_files"
    )
    ctx["artifacts"]["delegate_output"] = compact

    # Parent-supplied VERIFY commands are expectations; run when present.
    results = []
    for command in ctx.get("verify") or []:
        if command in ("(none)",):
            continue
        completed = subprocess.run(
            command,
            cwd=ctx["working_directory"],
            shell=True,
            text=True,
            capture_output=True,
        )
        excerpt = ((completed.stdout or "") + (completed.stderr or ""))[-1000:]
        results.append(
            {
                "command": command,
                "exit_code": completed.returncode,
                "output_excerpt": excerpt,
            }
        )
    if results:
        verify_path = Path(ctx["snapshot_directory"]) / "verification.json"
        verify_path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
        ctx["artifacts"]["verification_results"] = results

    ctxlib.record_artifact(
        evidence,
        "delta",
        root=root,
        path=delta_json,
        meta={"changed_files": compact["changed_files"]},
    )
    ctxlib.save_evidence(ctx, evidence)
    ctx["status"] = "AWAITING_ACCEPTANCE"
    return ctx


def log_outcome(ctx):
    """Non-blocking outcome log. Missing fields are omitted; failures warn only."""
    gate = (ctx.get("gate_result") or "").strip().upper()
    success = "true" if gate == "ACCEPT" else "false" if gate in {"REVISE", "DISCARD", "STOP"} else ""
    revision_needed = "true" if gate == "REVISE" else "false" if gate in {"ACCEPT", "DISCARD", "STOP"} else ""
    escaped = ""
    if (ctx.get("failure_classification") or "").upper() == "ESCAPED_DEFECT":
        escaped = "true"

    command = [
        str(ROOT / "scripts" / "router-log"),
        "--requested-agent",
        ctx.get("requested_agent") or ctx["agent"],
        "--actual-agent",
        ctx["agent"],
    ]
    if success:
        command.extend(["--success", success])
    if revision_needed:
        command.extend(["--revision-needed", revision_needed])
    if escaped:
        command.extend(["--escaped-defect", escaped])
    cost = ctx["artifacts"].get("token_usage") or ""
    if cost and cost != "UNKNOWN":
        command.extend(["--cost", str(cost)])
    duration = ctx.get("duration_seconds") or ""
    if duration and duration != "UNKNOWN":
        command.extend(["--duration", str(duration)])
    if ctx.get("outcome_log"):
        command[1:1] = ["--log", ctx["outcome_log"]]

    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode != 0:
        # Logging must not block execution.
        ctx["outcome_log_warning"] = (result.stderr or result.stdout or "router-log failed").strip()
    ctx["status"] = "COMPLETE" if gate == "ACCEPT" else ctx.get("status") or "LOGGED"
    return ctx


HOOKS = {
    "before_execute": before_execute,
    "snapshot": snapshot,
    "execute": execute,
    "after_execute": after_execute,
    "log_outcome": log_outcome,
}
