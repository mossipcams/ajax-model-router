#!/usr/bin/env python3
"""Harness-boundary routing decision. Never substitutes provider or model."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import model_registry as registry


ACTIONS = ("USE_NATIVE", "DELEGATE", "STOP")
CALLERS = registry.CALLERS
TRANSPORTS = registry.TRANSPORTS


def transport_available(transport: str, *, which=shutil.which) -> bool:
    command = registry.transport_command(transport)
    if not command:
        return False
    return which(command) is not None


def decide(
    *,
    caller_harness: str | None = None,
    target_transport: str | None = None,
    model: str,
    allowed_scope=None,
    which=shutil.which,
    # Back-compat aliases from the prior CURRENT/TARGET_HARNESS naming.
    current_harness: str | None = None,
    target_harness: str | None = None,
) -> dict:
    """Return a ROUTING_DECISION dict.

    caller_harness must come from the install adapter binding (CLI), never
    from task text or free model self-declaration. A caller need not be a
    supported DELEGATE transport (e.g. claude → cursor).
    """
    caller = (caller_harness or current_harness or "").strip().lower()
    transport = (target_transport or target_harness or "").strip().lower()
    model_id = (model or "").strip()
    scope = list(allowed_scope or [])

    def decision(action, reason, model_out="NONE"):
        return {
            "ACTION": action,
            "CALLER_HARNESS": caller or "NONE",
            "TARGET_TRANSPORT": transport or "NONE",
            "MODEL": model_out,
            "ALLOWED_SCOPE": scope,
            "REASON": reason,
            # Back-compat mirrors for older readers.
            "CURRENT_HARNESS": caller or "NONE",
            "TARGET_HARNESS": transport or "NONE",
        }

    if caller not in CALLERS:
        return decision(
            "STOP",
            f"caller harness {caller!r} is not bound "
            "(use a Cursor, Codex, Claude, or Pi install adapter)",
        )
    if transport not in TRANSPORTS:
        return decision(
            "STOP",
            f"target transport {transport!r} is not a supported Ajax transport",
        )

    # USE_NATIVE only when the caller *is* the transport and they match.
    # Claude/other are callers only — they never short-circuit to USE_NATIVE.
    if caller == transport and caller in TRANSPORTS:
        return decision(
            "USE_NATIVE",
            f"caller matches transport ({caller}); use native delegation "
            "and bypass Ajax Model Router",
            model_out=model_id or "NONE",
        )

    if not model_id or model_id.upper() == "NONE":
        return decision(
            "STOP",
            "cross-harness / cross-transport request requires an exact MODEL id",
        )

    if not registry.model_belongs(transport, model_id):
        return decision(
            "STOP",
            f"model {model_id!r} does not belong to target transport {transport}",
        )

    if not transport_available(transport, which=which):
        return decision(
            "STOP",
            f"target transport for {transport} is unavailable; refusing substitution",
            model_out=model_id,
        )

    return decision(
        "DELEGATE",
        f"{caller} → {transport} via Ajax Model Router",
        model_out=model_id,
    )


def format_decision(decision: dict) -> str:
    if decision["ALLOWED_SCOPE"]:
        scope_block = "\n" + "\n".join(
            f"    - {item}" for item in decision["ALLOWED_SCOPE"]
        )
    else:
        scope_block = " []"
    return (
        "ROUTING_DECISION:\n"
        f"  ACTION: {decision['ACTION']}\n"
        f"  CALLER_HARNESS: {decision['CALLER_HARNESS']}\n"
        f"  TARGET_TRANSPORT: {decision['TARGET_TRANSPORT']}\n"
        f"  MODEL: {decision['MODEL']}\n"
        f"  ALLOWED_SCOPE:{scope_block}\n"
        f"  REASON: {decision['REASON']}\n"
    )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Emit one harness-boundary ROUTING_DECISION."
    )
    parser.add_argument(
        "--caller-harness",
        "--current-harness",
        dest="caller_harness",
        required=True,
        choices=CALLERS,
        help="Immutable install binding; never from task text",
    )
    parser.add_argument(
        "--target-transport",
        "--target-harness",
        dest="target_transport",
        required=True,
        choices=TRANSPORTS,
        help="Ajax-supported DELEGATE transport",
    )
    parser.add_argument("--model", required=True, help="Exact provider model ID")
    parser.add_argument(
        "--allowed",
        action="append",
        default=[],
        help="Allowed write path (repeatable)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of YAML-ish text",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    decision = decide(
        caller_harness=args.caller_harness,
        target_transport=args.target_transport,
        model=args.model,
        allowed_scope=args.allowed,
    )
    if args.json:
        print(json.dumps(decision, indent=2, sort_keys=True))
    else:
        print(format_decision(decision), end="")
    if decision["ACTION"] == "STOP":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
