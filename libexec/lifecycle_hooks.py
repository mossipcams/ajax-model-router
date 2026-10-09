#!/usr/bin/env python3
"""Thin router execute hooks — safety + transport only, never invoke an LLM for routing."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import lifecycle_context as ctxlib
import route_health
import router_state
from subagent_status import is_subagent_status_line

ROOT = Path(__file__).resolve().parents[1]

PROMPT_HEAD = """You are already the selected implementation worker. Implement in-process.
Never spawn native Cursor Task, best-of-n, or any other subagent.
Never merge, rebase, force-push, or switch branches. Commit, push, branch, or open a PR only if the user explicitly asked, after the local verification gate. Open the PR with the repository's documented PR command (for example `scripts/gh-pr-create` when its AGENTS.md or docs require it); use raw `gh pr create` only when none is documented.

Implement the requested outcome.
"""

PROMPT_TAIL = """Investigate the repository as needed.
Choose the implementation approach.
Run appropriate verification.
Stop if completing the task requires expanding beyond the allowed scope.

End with only this report:
ROUTER_REPORT_BEGIN
DELEGATE_REPORT:
  STATUS: COMPLETE | BLOCKED | FAILED
  CHANGED_FILES: [<paths>]
  VERIFICATION:
    - TYPE: test | build | lint | typecheck | integration | manual | other
      COMMAND: <command or NONE>
      RESULT: pass | fail | skipped | blocked
      DETAILS: <short>
  CONCERNS: []
ROUTER_REPORT_END
"""


# Local models (Swift via pi) run slowly: in 77 logged runs, 13 of 22 runs past 30 tool
# calls timed out vs 2 of 22 at 10-20. A soft call budget turns a hard-kill timeout
# (no report) into a BLOCKED report the parent can escalate. Recalibrate from the
# `stats` line in debug.log (see README "Calibrating Swift budgets").
LOCAL_MODEL_PREFIX = "local/"
LOCAL_TOOL_CALL_BUDGET = 30
BUDGET_NOTE = (
    f"Budget: about {LOCAL_TOOL_CALL_BUDGET} tool calls. If you are not close to done "
    "by then, stop, leave the tree consistent, and report BLOCKED with what remains "
    "in CONCERNS.\n"
)
RESUME_NOTE = (
    "Resume: an earlier attempt was cut off by a provider error and the worktree may "
    "hold its partial edits. Inspect them, keep what is good, and finish.\n\n"
)


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


def _clean(items):
    """Strip, drop empties, dedupe while keeping order."""
    return list(dict.fromkeys(i.strip() for i in items if i and i.strip()))


def build_prompt(ctx):
    """Compact delegate prompt: only non-empty sections, task before report."""
    parts = [PROMPT_HEAD]
    request = (ctx.get("user_request") or "").strip()
    if request:
        parts.append(f"Task:\n{request}\n")
    instructions = (ctx.get("instructions") or "").strip()
    if instructions:
        parts.append(f"Additional instructions:\n{instructions}\n")
    for title, items in (
        ("Scope (edit only these)", ctx["allowed_files"]),
        ("Acceptance", ctx["acceptance"]),
        (
            "Revision findings (previous round rejected; the worktree still holds its edits; fix every finding)",
            ctx.get("revision_findings") or [],
        ),
        ("Verify with", ctx.get("verify") or []),
    ):
        items = _clean(items)
        if items:
            parts.append(f"{title}:\n{_bullet_lines(items)}\n")
    parts.append(PROMPT_TAIL)
    prompt = "\n".join(parts)
    # ponytail: keyed on the initial model; a fallback route keeps the note, harmlessly.
    if (ctx.get("model") or "").startswith(LOCAL_MODEL_PREFIX):
        prompt = prompt.replace(PROMPT_TAIL, BUDGET_NOTE + PROMPT_TAIL, 1)
    return prompt


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
    prompt = build_prompt(ctx)

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
        "claude": "claude",
        "minimax": "pi",
        "glm": "pi",
    }
    if tool not in mapping:
        raise HookError(f"unsupported tool/agent for execute: {tool!r}")
    return mapping[tool]


def _run_id(ctx):
    retry = int(ctx.get("retry_count") or 0)
    base = f"run_{ctx['task_id']}"
    return f"{base}_{retry}" if retry else base


def _task_label(ctx):
    return ctx["task_id"]


# Report concern types meaning the tool never got to work (quota, auth, missing CLI).
UNAVAILABLE_TYPES = frozenset({"TOOL_UNAVAILABLE", "MISSING_TOOL"})


def _failure_type(ctx):
    """First CONCERNS TYPE of a FAILED runner report, else ''.

    A runner failure exits nonzero; a FAILED report from a clean exit was written by
    the delegate itself, so its TYPE is not trusted to drive retry or route health.
    """
    if ctx["artifacts"].get("provider_metadata", {}).get("exit_code") == 0:
        return ""
    report = Path(ctx["artifacts"].get("report_path") or "")
    text = report.read_text() if report.is_file() else ""
    match = re.search(r"^\s*-\s*TYPE:\s*(\S+)", text, re.MULTILINE)
    return match.group(1) if "STATUS: FAILED" in text and match else ""


def _unavailable_reason(ctx):
    kind = _failure_type(ctx)
    return kind if kind in UNAVAILABLE_TYPES else ""


def _keep_attempt_logs(ctx, attempt):
    """Move this attempt's logs aside so the next attempt starts clean."""
    run = _run_dir(ctx)
    kept = {}
    for name in ("raw_log", "debug_log", "report_path"):
        path = Path(ctx["artifacts"].get(name) or "")
        if path.is_file():
            target = run / f"attempt-{attempt}-{ctx['agent']}-{path.name}"
            path.replace(target)
            kept[name] = str(target)
    return kept


def _worktree_changed(ctx):
    """True when the working tree differs from the pre-execute snapshot."""
    snapshot_dir = Path(ctx["snapshot_directory"])

    def capture_probe():
        router_state.capture(snapshot_dir, "probe", quiet=True)

    _with_cwd(ctx["working_directory"], capture_probe)
    pre = router_state.load_manifest(snapshot_dir, "pre")["files"]
    probe = router_state.load_manifest(snapshot_dir, "probe")["files"]
    return bool(router_state.classify(pre, probe)[-1])


def _parse_route(entry):
    agent, _, model = entry.partition("/")
    agent, model = agent.strip().lower(), model.strip()
    if agent not in ("cursor", "codex", "pi", "claude") or not model:
        raise HookError(f"fallback_chain entries must be agent/model, got {entry!r}")
    return agent, model


def _report_status(ctx):
    report = Path(ctx["artifacts"].get("report_path") or "")
    text = report.read_text() if report.is_file() else ""
    match = re.search(r"STATUS:\s*(\w+)", text)
    return match.group(1) if match else ""


def execute(ctx):
    """Dispatch; on an unavailable tool with an untouched tree, walk fallback_chain.

    Results feed the route-health cache so routing skips known-dead routes. Some
    adapters (pi) swallow provider errors and just end the turn, so a failure
    that left the tree untouched is confirmed with a probe before falling back.
    """
    provider_retried = False
    while True:
        _execute_once(ctx)
        route = f"{ctx['agent']}/{ctx['model']}"
        status = _report_status(ctx)
        if status == "COMPLETE":
            route_health.record(route, True, "dispatch completed")
            break
        if status != "FAILED":
            break
        reason = _unavailable_reason(ctx)
        changed = _worktree_changed(ctx)
        if _failure_type(ctx) == "PROVIDER_ERROR":
            # Transient model-server error, not a model failure: retry the same
            # route once (keeping partial edits); a second one marks the route down.
            if not provider_retried:
                provider_retried = True
                attempt = len(ctx["artifacts"]["fallback_attempts"])
                kept = _keep_attempt_logs(ctx, attempt)
                ctx["artifacts"]["fallback_attempts"].append(
                    {"agent": ctx["agent"], "model": ctx["model"], "reason": "PROVIDER_ERROR", **kept}
                )
                if changed:
                    prompt = Path(ctx["artifacts"]["prompt_path"])
                    prompt.write_text(prompt.read_text().replace(PROMPT_TAIL, RESUME_NOTE + PROMPT_TAIL, 1))
                sys.stderr.write(f"[ajax-router] {route} provider error; retrying once\n")
                continue
            reason = "PROVIDER_ERROR"
        if not reason and not changed:
            healthy, detail = route_health.probe(route)
            if not healthy:
                reason = "TOOL_UNAVAILABLE"
                sys.stderr.write(f"[ajax-router] {route} probe failed: {detail}\n")
        if reason:
            route_health.record(route, False, reason)
        down = route_health.unavailable()
        while ctx.get("fallback_chain") and ctx["fallback_chain"][0] in down:
            skipped = ctx["fallback_chain"].pop(0)
            sys.stderr.write(f"[ajax-router] skipping {skipped}: recently unavailable\n")
        if not reason or not ctx.get("fallback_chain") or changed:
            break
        agent, model = _parse_route(ctx["fallback_chain"].pop(0))
        attempt = len(ctx["artifacts"]["fallback_attempts"])
        kept = _keep_attempt_logs(ctx, attempt)
        ctx["artifacts"]["fallback_attempts"].append(
            {"agent": ctx["agent"], "model": ctx["model"], "reason": reason, **kept}
        )
        sys.stderr.write(
            f"[ajax-router] {ctx['agent']}/{ctx['model']} unavailable ({reason}); "
            f"falling back to {agent}/{model}\n"
        )
        ctx["agent"], ctx["model"], ctx["tool"] = agent, model, agent
    ctx["status"] = "EXECUTED"
    return ctx


def _execute_once(ctx):
    run = _run_dir(ctx)
    prompt_path = Path(ctx["artifacts"]["prompt_path"])
    if not prompt_path.is_file():
        raise HookError("prompt_path missing; refuse to spend tokens")
    raw_log = run / "raw.log"
    debug_log = run / "debug.log"
    report = run / "report.yaml"
    ctx["artifacts"]["raw_log"] = str(raw_log)
    ctx["artifacts"]["debug_log"] = str(debug_log)
    ctx["artifacts"]["report_path"] = str(report)
    tool = _tool_for(ctx)
    run_id = (ctx.get("run_id") or "").strip() or _run_id(ctx)
    ctx["artifacts"]["run_id"] = run_id
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
        "--run-id",
        run_id,
        "--parent-task-id",
        ctx["task_id"],
        "--task",
        _task_label(ctx),
    ]
    if tool == "codex":
        command.extend(["--sandbox", ctx.get("sandbox") or "workspace-write"])
        if ctx.get("reasoning_effort"):
            command.extend(["--reasoning-effort", ctx["reasoning_effort"]])
        else:
            command.extend(["--reasoning-effort", "xhigh"])

    process = None
    stdout_tail_parts = []
    try:
        process = subprocess.Popen(
            command,
            cwd=ctx["working_directory"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=None,
            bufsize=1,
        )
        if process.stdout:
            while True:
                line = process.stdout.readline()
                if not line:
                    break
                if is_subagent_status_line(line):
                    sys.stdout.write(line)
                    sys.stdout.flush()
                else:
                    stdout_tail_parts.append(line)
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait()
    returncode = process.returncode if process is not None else 1
    stdout_tail = "".join(stdout_tail_parts)
    result = subprocess.CompletedProcess(
        args=command,
        returncode=returncode,
        stdout=stdout_tail,
        stderr="",
    )
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

    routing = ctx.get("routing_explanation") or ctx.get("routing_event")
    if routing:
        if isinstance(routing, dict):
            routing = json.dumps(routing, sort_keys=True)
        command.extend(["--routing-event", routing])

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
