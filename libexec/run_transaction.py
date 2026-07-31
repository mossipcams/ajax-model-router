#!/usr/bin/env python3
"""Ordered lifecycle transaction runner for router delegation."""

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
        description="Run deterministic router lifecycle stages for one delegation transaction."
    )
    parser.add_argument(
        "--context",
        type=Path,
        required=True,
        help="Path to normalized lifecycle context JSON",
    )
    parser.add_argument(
        "--from-stage",
        default=ctxlib.STAGES[0],
        choices=ctxlib.STAGES,
        help="First stage to run (default: before_dispatch)",
    )
    parser.add_argument(
        "--until-stage",
        default="before_review",
        choices=ctxlib.STAGES,
        help="Last stage to run inclusive (default: before_review / AWAITING_REVIEW)",
    )
    parser.add_argument(
        "--gate-result",
        choices=("ACCEPT", "REVISE", "DISCARD", "STOP"),
        help="Parent Review Gate verdict; required when running after_review",
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
            # Fail closed: never spend tokens without a validated prompt on disk.
            prompt = Path(ctx.get("artifacts", {}).get("prompt_path") or "")
            if not prompt.is_file():
                raise HookError(
                    "refusing delegate: prompt missing (validate_dispatch must succeed first)"
                )
            if "validate_dispatch" not in ctx.get("completed_stages", []) and name == "delegate":
                # Allow resume mid-flight only when prior run recorded validation.
                if ctx.get("status") not in {"DISPATCH_VALID", "SNAPSHOT_OK", "SNAPSHOT_REUSED", "DELEGATED"}:
                    if "validate_dispatch" not in executed and "validate_dispatch" not in ctx.get(
                        "completed_stages", []
                    ):
                        raise HookError("refusing delegate before validate_dispatch")

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
    if "after_review" in stages and not (ctx.get("gate_result") or "").strip():
        print(
            "transaction failed: after_review requires --gate-result or context.gate_result",
            file=sys.stderr,
        )
        return 2

    # Persist under snapshot_directory so resume shares one transaction state.
    state_path = Path(ctx["snapshot_directory"]) / ctxlib.CONTEXT_STATE_NAME
    if state_path.is_file() and args.from_stage != ctxlib.STAGES[0]:
        # Resume: merge parent-supplied overrides onto saved state.
        try:
            saved = ctxlib.load_context(state_path)
        except ctxlib.ContextError:
            saved = None
        if saved:
            for key in (
                "gate_result",
                "escalation_reason",
                "escalation_destination",
                "failure_classification",
                "duration_seconds",
                "token_usage",
                "calibration_log",
                "retry_count",
            ):
                if key in ctx and ctx[key] not in (None, ""):
                    if key == "token_usage":
                        saved["artifacts"]["token_usage"] = ctx[key]
                    else:
                        saved[key] = ctx[key]
            # Keep latest parent classification fields when re-supplied.
            for key in ("dispatch_level", "risk", "model", "provider", "tool"):
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
        print(f"transaction failed: {error}", file=sys.stderr)
        return 1

    result = {
        "status": ctx.get("status"),
        "executed_stages": executed,
        "completed_stages": ctx.get("completed_stages"),
        "dispatch_level": ctx.get("dispatch_level"),
        "snapshot_directory": ctx.get("snapshot_directory"),
        "review_bundle_path": ctx.get("artifacts", {}).get("review_bundle_path") or "",
        "review_artifact_path": ctx.get("artifacts", {}).get("review_artifact_path") or "",
        "context_path": str(Path(ctx["snapshot_directory"]) / ctxlib.CONTEXT_STATE_NAME),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
