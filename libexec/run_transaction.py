#!/usr/bin/env python3
"""Ordered execute runner for thin router delegation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lifecycle_context as ctxlib
from lifecycle_hooks import HOOKS, HookError


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run deterministic safety stages for one router execute transaction."
    )
    parser.add_argument(
        "--context",
        type=Path,
        required=True,
        help="Path to normalized execution context JSON",
    )
    parser.add_argument(
        "--from-stage",
        default=ctxlib.STAGES[0],
        choices=ctxlib.STAGES,
        help="First stage to run (default: before_execute)",
    )
    parser.add_argument(
        "--until-stage",
        default="after_execute",
        choices=ctxlib.STAGES,
        help="Last stage to run inclusive (default: after_execute / AWAITING_ACCEPTANCE)",
    )
    parser.add_argument(
        "--gate-result",
        choices=("ACCEPT", "REVISE", "DISCARD", "STOP"),
        help="Parent acceptance verdict; optional for log_outcome",
    )
    parser.add_argument(
        "--dry-run-plan",
        action="store_true",
        help="Print the stage plan as JSON and exit without executing hooks",
    )
    return parser.parse_args(argv)


def stage_slice(from_stage, until_stage):
    start = ctxlib.stage_index(from_stage)
    end = ctxlib.stage_index(until_stage)
    if start > end:
        raise ctxlib.ContextError(
            f"--from-stage {from_stage} is after --until-stage {until_stage}"
        )
    return list(ctxlib.STAGES[start : end + 1])


def run_stages(ctx, stages):
    executed = []
    for name in stages:
        if name in ctxlib.TOKEN_STAGES:
            prompt = Path(ctx.get("artifacts", {}).get("prompt_path") or "")
            if not prompt.is_file():
                raise HookError(
                    "refusing execute: prompt missing (before_execute must succeed first)"
                )
            if "before_execute" not in ctx.get("completed_stages", []) and name == "execute":
                if "before_execute" not in executed and "before_execute" not in ctx.get(
                    "completed_stages", []
                ):
                    raise HookError("refusing execute before before_execute")

        hook = HOOKS[name]
        ctx = hook(ctx)
        executed.append(name)
        completed = list(ctx.get("completed_stages") or [])
        if name not in completed:
            completed.append(name)
        ctx["completed_stages"] = completed
        ctxlib.save_context(ctx)
    return ctx, executed


def main(argv=None):
    args = parse_args(argv)
    try:
        stages = stage_slice(args.from_stage, args.until_stage)
    except ctxlib.ContextError as error:
        print(f"transaction failed: {error}", file=sys.stderr)
        return 2

    if args.dry_run_plan:
        print(json.dumps({"stages": stages}, indent=2, sort_keys=True))
        return 0

    try:
        ctx = ctxlib.load_context(args.context)
    except ctxlib.ContextError as error:
        print(f"transaction failed: {error}", file=sys.stderr)
        return 2

    if args.gate_result:
        ctx["gate_result"] = args.gate_result

    state_path = Path(ctx["snapshot_directory"]) / ctxlib.CONTEXT_STATE_NAME
    if state_path.is_file() and args.from_stage != ctxlib.STAGES[0]:
        try:
            saved = ctxlib.load_context(state_path)
        except ctxlib.ContextError:
            saved = None
        if saved:
            for key in (
                "gate_result",
                "failure_classification",
                "duration_seconds",
                "outcome_log",
                "retry_count",
            ):
                if key in ctx and ctx[key] not in (None, ""):
                    saved[key] = ctx[key]
            for key in ("agent", "risk", "model", "tool", "requested_agent"):
                if args.context and key in json.loads(args.context.read_text()):
                    saved[key] = ctx[key]
            ctx = saved

    try:
        ctx, executed = run_stages(ctx, stages)
    except (HookError, ctxlib.ContextError, OSError, RuntimeError) as error:
        try:
            ctx["status"] = "FAILED"
            ctx["failure"] = str(error)
            ctxlib.save_context(ctx)
        except Exception:
            pass
        artifacts = ctx.get("artifacts") or {}
        paths = []
        for key in ("debug_log", "raw_log", "report_path"):
            path = artifacts.get(key)
            if path:
                paths.append(f"{key}={path}")
        message = f"transaction failed: {error}"
        if paths:
            message = f"{message} ({', '.join(paths)})"
        print(message, file=sys.stderr)
        return 1

    artifacts = ctx.get("artifacts") or {}
    delegate_output = artifacts.get("delegate_output") or {}
    result = {
        "status": ctx.get("status"),
        "executed_stages": executed,
        "completed_stages": ctx.get("completed_stages"),
        "agent": ctx.get("agent"),
        "risk": ctx.get("risk"),
        "snapshot_directory": ctx.get("snapshot_directory"),
        "delta_json": artifacts.get("delta_json") or "",
        "delta_patch": artifacts.get("delta_patch") or "",
        "scope_violations": artifacts.get("scope_violations") or [],
        "changed_files": artifacts.get("changed_files") or [],
        "raw_log": artifacts.get("raw_log") or "",
        "debug_log": artifacts.get("debug_log") or "",
        "report_path": artifacts.get("report_path") or "",
        "delegate_status": delegate_output.get("status") or "",
        "context_path": str(Path(ctx["snapshot_directory"]) / ctxlib.CONTEXT_STATE_NAME),
        "outcome_log_warning": ctx.get("outcome_log_warning") or "",
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
