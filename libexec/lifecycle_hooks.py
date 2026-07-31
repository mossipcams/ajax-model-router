#!/usr/bin/env python3
"""Internal router lifecycle hooks — deterministic only, never invoke an LLM."""

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

DELEGATE_WRAPPER = """You are a bounded implementation worker for a parent agent.
Current directory is the task worktree.
Never commit, push, merge, rebase, create branches, or change branches.

Complete exactly one bounded task from the packet below.
Edit only Allowed files / Scope.allowed. Do not touch Forbidden changes.
Follow Code anchors when provided.
Make the smallest allowed edit needed.
Select and run verification appropriate to the change. Testing is one method,
not a required workflow. Do not skip verification.
Stop if any Stop condition is hit, or if the patch would exceed roughly 400 changed lines.
No drive-by cleanup, renames, formatting sweeps, or broad refactors.

Return exactly the router's DELEGATE_REPORT schema between these marker lines:
ROUTER_REPORT_BEGIN
<DELEGATE_REPORT YAML>
ROUTER_REPORT_END
Identify what was verified and the result. Do not write a long narrative unless
a material concern requires explanation.

"""


class HookError(RuntimeError):
    """Deterministic lifecycle hook failure."""


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


def before_dispatch(ctx):
    """Normalize metadata/paths, prepare snapshot dir, reject bad context early."""
    working = Path(ctx["working_directory"])
    if not working.is_dir():
        raise HookError(f"working_directory does not exist: {working}")
    # Do not mutate process cwd; subprocess hooks pass working_directory explicitly.

    root = _git_root(working)
    if root != working.resolve():
        raise HookError(
            f"working_directory must be the git toplevel ({root}), got {working.resolve()}"
        )

    snapshot = Path(ctx["snapshot_directory"])
    snapshot.mkdir(parents=True, exist_ok=True)

    evidence = ctxlib.load_evidence(ctx)
    if evidence.get("root") and not _roots_equal(evidence["root"], working.resolve()):
        raise HookError("evidence index root mismatch; refusing reuse")
    evidence["root"] = str(working.resolve())
    ctxlib.save_evidence(ctx, evidence)

    if ctx["dispatch_level"] == "direct" and not ctx.get("user_request", "").strip():
        raise HookError("direct dispatch requires user_request")
    if ctx["dispatch_level"] == "full" and not ctx.get("packet_path", "").strip():
        raise HookError("full dispatch requires packet_path")
    if ctx["dispatch_level"] == "compact":
        if not ctx.get("goal", "").strip() and not ctx.get("user_request", "").strip():
            raise HookError("compact dispatch requires goal or user_request")
        if not ctx["allowed_files"]:
            raise HookError("compact dispatch requires allowed_files")

    if not ctx["allowed_files"]:
        raise HookError("allowed_files must be non-empty for write dispatch")

    ctx["status"] = "BEFORE_DISPATCH_OK"
    return ctx


def _section(title, body_lines):
    body = "\n".join(body_lines).rstrip()
    if not body:
        body = "(none)"
    return f"## {title}\n\n{body}\n"


def _bullet_or_lines(items):
    if not items:
        return ["(none)"]
    return [item if item.startswith("- ") else f"- {item}" for item in items]


def _verification_body(ctx):
    """Parent-supplied verification expectations; optional for direct."""
    methods = ctx.get("verification_methods") or []
    commands = ctx.get("verification_commands") or []
    reason = (ctx.get("verification_reason") or "").strip()
    lines = []
    if methods:
        lines.append("methods:")
        for method in methods:
            lines.append(f"  - {method}")
    if commands:
        lines.append("commands:")
        lines.extend(_bullet_or_lines(commands))
    if reason:
        lines.append(f"reason: {reason}")
    if not lines:
        lines = [
            "methods: delegate-selected after repository inspection",
            "reason: parent did not pre-specify verification; choose the smallest method that validates acceptance",
        ]
    return lines


def build_direct_dispatch(ctx):
    parts = [
        f"DISPATCH_LEVEL: direct\n",
        f"TASK_ID: {ctx['task_id']}\n",
        f"RISK: {ctx['risk']}\n",
        _section("User request", [ctx.get("user_request", "").strip() or "(missing)"]),
        _section("Allowed files", _bullet_or_lines(ctx["allowed_files"])),
        _section("Acceptance criteria", _bullet_or_lines(ctx["acceptance"])),
        _section("Verification", _verification_body(ctx)),
        _section("Stop conditions", _bullet_or_lines(ctx.get("stop_conditions", []))),
    ]
    return "".join(parts)


def build_compact_dispatch(ctx):
    goal = ctx.get("goal", "").strip() or ctx.get("user_request", "").strip()
    parts = [
        "PACKET_STATUS: READY\n",
        "UNRESOLVED_UNCERTAINTY: NONE\n",
        "BLOCKERS: []\n",
        "DISPATCH_LEVEL: compact\n",
        _section("Task", [goal]),
        _section("Allowed files", _bullet_or_lines(ctx["allowed_files"])),
        _section("Forbidden changes", _bullet_or_lines(ctx.get("forbidden_changes", []))),
        _section("Acceptance", _bullet_or_lines(ctx["acceptance"])),
        _section("Constraints", _bullet_or_lines(ctx.get("constraints", []) or ["NONE"])),
        _section("Verification", _verification_body(ctx)),
        _section("Stop if", _bullet_or_lines(ctx.get("stop_conditions", []))),
    ]
    # Optional useful anchors only — never Context evidence or Test-first.
    if ctx.get("code_anchors"):
        parts.append(_section("Code anchors", _bullet_or_lines(ctx["code_anchors"])))
    return "".join(parts)


def build_dispatch(ctx):
    run = _run_dir(ctx)
    level = ctx["dispatch_level"]
    if level == "direct":
        body = build_direct_dispatch(ctx)
        dispatch_path = run / "dispatch.direct.md"
    elif level == "compact":
        body = build_compact_dispatch(ctx)
        dispatch_path = run / "dispatch.compact.md"
    else:
        packet = Path(ctx["packet_path"])
        if not packet.is_absolute():
            packet = Path(ctx["working_directory"]) / packet
        if not packet.is_file():
            raise HookError(f"packet_path not found: {packet}")
        body = packet.read_text()
        dispatch_path = run / "dispatch.full.md"
        dispatch_path.write_text(body)

    ctxlib.enforce_dispatch_limits(body, level)
    if level != "full":
        dispatch_path.write_text(body)

    prompt = DELEGATE_WRAPPER + body
    ctxlib.enforce_dispatch_limits(prompt, level)
    prompt_path = run / "prompt.txt"
    prompt_path.write_text(prompt)

    ctx["artifacts"]["dispatch_path"] = str(dispatch_path)
    ctx["artifacts"]["prompt_path"] = str(prompt_path)
    ctx["status"] = "DISPATCH_BUILT"
    return ctx


def validate_dispatch(ctx):
    dispatch_path = Path(ctx["artifacts"]["dispatch_path"])
    if not dispatch_path.is_file():
        raise HookError("dispatch_path missing; run build_dispatch first")
    check = ROOT / "scripts" / "check-dispatch"
    result = subprocess.run(
        [str(check), ctx["dispatch_level"], str(dispatch_path)],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "check-dispatch failed").strip()
        raise HookError(detail)
    ctx["status"] = "DISPATCH_VALID"
    return ctx


def snapshot(ctx):
    """Create or reuse pre-dispatch snapshot."""
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
    # Prefer the manifest root (resolved git toplevel) for reuse checks.
    manifest = router_state.load_manifest(snapshot_dir, "pre")
    evidence_root = manifest.get("root") or root
    evidence["root"] = evidence_root
    ctxlib.record_artifact(evidence, "pre_snapshot", root=evidence_root, path=pre_path)
    # Keep context aligned with snapshot root so later compares match.
    ctx["working_directory"] = evidence_root
    ctxlib.save_evidence(ctx, evidence)
    ctx["status"] = "SNAPSHOT_OK"
    return ctx


def _tool_for(ctx):
    tool = (ctx.get("tool") or ctx.get("provider") or "").strip().lower()
    mapping = {
        "cursor": "cursor",
        "cursor-delegate": "cursor",
        "pi": "pi",
        "pi-delegate": "pi",
        "codex": "codex",
        "codex-delegate": "codex",
        "minimax": "pi",
        "glm": "pi",
    }
    if tool not in mapping and tool not in ("cursor", "pi", "codex"):
        raise HookError(f"unsupported tool/provider for delegate: {tool!r}")
    return mapping.get(tool, tool)


def delegate(ctx):
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
        if ctx.get("sandbox"):
            command.extend(["--sandbox", ctx["sandbox"]])
        if ctx.get("reasoning_effort"):
            command.extend(["--reasoning-effort", ctx["reasoning_effort"]])

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
    # Token usage stays UNKNOWN unless a later parser finds provider facts.
    ctx["artifacts"]["token_usage"] = ctx["artifacts"].get("token_usage") or "UNKNOWN"
    if result.returncode not in (0,):
        # Transport may still have written a FAILED report; continue to after_delegate
        # only when report exists so scope/delta can still be captured.
        if not report.is_file():
            raise HookError(
                f"delegate transport failed ({result.returncode}): "
                f"{(result.stderr or result.stdout or '').strip()[:500]}"
            )
    ctx["status"] = "DELEGATED"
    return ctx


def _parse_report_compact(report_text):
    """Extract a compact dict from DELEGATE_REPORT — no narrative."""
    out = {
        "status": "UNKNOWN",
        "changed_files": [],
        "concerns": [],
        "verification": [],
        "stop_conditions_hit": [],
        "remaining_risks": [],
        "summary": "",
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
    summary = re.search(r"^\s*SUMMARY:\s*(.+)$", report_text, re.M)
    if summary:
        out["summary"] = summary.group(1).strip()
    out["changed_files"] = list_field("CHANGED_FILES") or list_field("FILES_CHANGED")
    out["stop_conditions_hit"] = list_field("STOP_CONDITIONS_HIT")
    out["remaining_risks"] = list_field("REMAINING_RISKS")
    out["concerns"] = list_field("CONCERNS")
    # Prefer remaining_risks as concerns when using legacy reports.
    if not out["concerns"] and out["remaining_risks"]:
        out["concerns"] = out["remaining_risks"]
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


def after_delegate(ctx):
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

    ctxlib.record_artifact(
        evidence,
        "delta",
        root=root,
        path=delta_json,
        meta={"changed_files": compact["changed_files"]},
    )
    ctxlib.save_evidence(ctx, evidence)
    ctx["status"] = "AFTER_DELEGATE_OK"
    return ctx


def run_verification(ctx):
    results = []
    evidence = ctxlib.load_evidence(ctx)
    cached = (evidence.get("artifacts") or {}).get("verification")
    verify_path = Path(ctx["snapshot_directory"]) / "verification.json"

    commands = list(ctx.get("verification_commands") or [])
    if not commands and ctx["dispatch_level"] == "full":
        dispatch = Path(ctx["artifacts"].get("dispatch_path") or "")
        if dispatch.is_file():
            text = dispatch.read_text()
            commands = _extract_section_commands(text, "Verification commands")
            if not commands:
                commands = _extract_section_commands(text, "Verification")

    if (
        cached
        and cached.get("root") == ctx["working_directory"]
        and Path(cached.get("path", "")).is_file()
        and not _verification_stale(cached, commands)
    ):
        results = json.loads(Path(cached["path"]).read_text())
        ctx["artifacts"]["verification_results"] = results
        ctx["status"] = "VERIFICATION_REUSED"
        return ctx

    for command in commands:
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

    verify_path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    ctxlib.record_artifact(
        evidence,
        "verification",
        root=ctx["working_directory"],
        path=verify_path,
        meta={"commands": commands},
    )
    ctxlib.save_evidence(ctx, evidence)
    ctx["artifacts"]["verification_results"] = results
    ctx["status"] = "VERIFICATION_OK"
    return ctx


def _verification_stale(cached, commands):
    return list((cached.get("meta") or {}).get("commands") or []) != list(commands)


def _extract_section_commands(text, heading):
    lines = text.splitlines()
    collecting = False
    items = []
    for line in lines:
        if line.strip() == f"## {heading}":
            collecting = True
            continue
        if collecting and line.startswith("## "):
            break
        if collecting:
            stripped = line.strip()
            if stripped.startswith("- "):
                items.append(stripped[2:].strip())
            elif stripped and stripped != "(none)":
                items.append(stripped)
    return items


def before_review(ctx):
    """Build the smallest review bundle; never include transcript or full packet."""
    run = _run_dir(ctx)
    delta_patch = Path(ctx["artifacts"].get("delta_patch") or "")
    patch_text = ""
    if delta_patch.is_file():
        # Cap hunk text so the bundle stays small; full patch remains on disk.
        patch_text = delta_patch.read_text()
        if len(patch_text) > 100_000:
            patch_text = patch_text[:100_000] + "\n...[truncated]...\n"

    bundle = {
        "task_id": ctx["task_id"],
        "dispatch_level": ctx["dispatch_level"],
        "user_request": ctx.get("user_request") or ctx.get("goal") or "",
        "acceptance": ctx["acceptance"],
        "changed_files": ctx["artifacts"].get("changed_files") or [],
        "delta_hunks": patch_text,
        "verification_results": ctx["artifacts"].get("verification_results") or [],
        "delegate_concerns": (ctx["artifacts"].get("delegate_output") or {}).get(
            "concerns"
        )
        or (ctx["artifacts"].get("delegate_output") or {}).get("remaining_risks")
        or [],
        "stop_conditions_hit": (ctx["artifacts"].get("delegate_output") or {}).get(
            "stop_conditions_hit"
        )
        or [],
        "scope_violations": ctx["artifacts"].get("scope_violations") or [],
        "delegate_status": (ctx["artifacts"].get("delegate_output") or {}).get("status"),
        "delegate_verification": (ctx["artifacts"].get("delegate_output") or {}).get(
            "verification"
        )
        or [],
        "delta_json": ctx["artifacts"].get("delta_json") or "",
        "snapshot_directory": ctx["snapshot_directory"],
    }
    # Explicit exclusions live only as absences: no transcript, packet, summaries.
    forbidden_keys = {
        "transcript",
        "raw_log",
        "packet",
        "repository_summary",
        "reasoning",
        "full_prompt",
    }
    overlap = forbidden_keys & set(bundle)
    if overlap:
        raise HookError(f"review bundle leaked excluded keys: {sorted(overlap)}")

    path = run / "review_bundle.json"
    path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n")
    ctx["artifacts"]["review_bundle_path"] = str(path)
    ctx["status"] = "AWAITING_REVIEW"
    return ctx


def after_review(ctx):
    gate = (ctx.get("gate_result") or "").strip().upper()
    if gate not in {"ACCEPT", "REVISE", "DISCARD", "STOP"}:
        raise HookError("after_review requires gate_result ACCEPT|REVISE|DISCARD|STOP")

    run = _run_dir(ctx)
    artifact = {
        "task_id": ctx["task_id"],
        "dispatch_level": ctx["dispatch_level"],
        "gate_result": gate,
        "retry_count": ctx.get("retry_count", 0),
        "escalation_reason": ctx.get("escalation_reason") or "NONE",
        "token_usage": ctx["artifacts"].get("token_usage") or "UNKNOWN",
        "scope_violations": ctx["artifacts"].get("scope_violations") or [],
        "changed_files": ctx["artifacts"].get("changed_files") or [],
        "review_bundle_path": ctx["artifacts"].get("review_bundle_path") or "",
    }
    path = run / "review_artifact.json"
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    ctx["artifacts"]["review_artifact_path"] = str(path)
    ctx["status"] = "AFTER_REVIEW_OK"
    return ctx


def log_calibration(ctx):
    gate = (ctx.get("gate_result") or "NOT_RUN").strip().upper()
    verification = ctx["artifacts"].get("verification_results") or []
    if not verification:
        verification_result = "NOT_RUN"
    elif all(item.get("exit_code") == 0 for item in verification):
        verification_result = "PASS"
    else:
        verification_result = "FAIL"

    repository_id = ctx.get("repository_id") or Path(ctx["working_directory"]).name
    command = [
        str(ROOT / "scripts" / "router-log"),
        "--repository-id",
        repository_id,
        "--task-id",
        ctx["task_id"],
        "--round",
        str(ctx.get("round", 1)),
        "--route-rule-id",
        ctx.get("route_rule_id") or "NONE",
        "--task-kind",
        ctx.get("task_kind") or "mechanical",
        "--risk-class",
        ctx["risk"].upper(),
        "--action",
        "REVIEW_GATE",
        "--lane",
        ctx.get("lane") or "NONE",
        "--model",
        ctx["model"],
        "--estimated-files",
        ctx.get("estimated_files") or str(len(ctx["allowed_files"])),
        "--estimated-lines",
        ctx.get("estimated_lines") or "UNKNOWN",
        "--critique-result",
        ctx.get("critique_result") or "NOT_RUN",
        "--gate-result",
        gate if gate in {"ACCEPT", "REVISE", "DISCARD", "STOP"} else "NOT_RUN",
        "--escalation-destination",
        ctx.get("escalation_destination") or "NONE",
        "--escalation-reason",
        ctx.get("escalation_reason") or "NONE",
        "--failure-classification",
        ctx.get("failure_classification") or "NONE",
        "--verification-result",
        verification_result,
        "--ci-result",
        ctx.get("ci_result") or "NOT_RUN",
        "--duration-seconds",
        ctx.get("duration_seconds") or "UNKNOWN",
        "--token-usage",
        ctx["artifacts"].get("token_usage") or "UNKNOWN",
    ]
    # Optional isolated log for tests.
    if ctx.get("calibration_log"):
        command[1:1] = ["--log", ctx["calibration_log"]]

    # Emit v3 verification metrics when known from the compact report.
    delegate_verification = (ctx["artifacts"].get("delegate_output") or {}).get(
        "verification"
    ) or []
    if delegate_verification:
        types = sorted(
            {
                item.get("type")
                for item in delegate_verification
                if isinstance(item, dict) and item.get("type")
            }
        )
        command.extend(
            [
                "--verification-types",
                ",".join(types) if types else "UNKNOWN",
                "--new-tests-added",
                "UNKNOWN",
                "--existing-tests-run",
                str(sum(1 for item in delegate_verification if item.get("type") == "existing_test")),
                "--manual-checks-run",
                str(sum(1 for item in delegate_verification if item.get("type") == "manual")),
                "--verification-passed",
                (
                    "true"
                    if verification_result == "PASS"
                    else "false"
                    if verification_result == "FAIL"
                    else "UNKNOWN"
                ),
                "--scope-violation",
                "true" if ctx["artifacts"].get("scope_violations") else "false",
                "--retry-count",
                str(ctx.get("retry_count", 0)),
            ]
        )

    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode != 0:
        raise HookError(
            f"router-log failed: {(result.stderr or result.stdout or '').strip()}"
        )
    ctx["status"] = "COMPLETE"
    return ctx


HOOKS = {
    "before_dispatch": before_dispatch,
    "build_dispatch": build_dispatch,
    "validate_dispatch": validate_dispatch,
    "snapshot": snapshot,
    "delegate": delegate,
    "after_delegate": after_delegate,
    "run_verification": run_verification,
    "before_review": before_review,
    "after_review": after_review,
    "log_calibration": log_calibration,
}
