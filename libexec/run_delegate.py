#!/usr/bin/env python3
import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codex_app_server


ROOT = Path(__file__).resolve().parents[1]


def failed_report(report, reason, summary):
    text = f"""DELEGATE_REPORT:
  STATUS: FAILED
  SUMMARY: {summary}
  FILES_CHANGED: []
  TEST_FIRST: NOT_PROVEN
  COMMAND_EVIDENCE: []
  STOP_CONDITIONS_HIT: [{reason}]
  REMAINING_RISKS: [Inspect the preserved raw log]
"""
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(text)
    sys.stdout.write(text)


EXECUTABLES = {"cursor": "cursor-agent", "pi": "pi"}


def command_for(tool, model, prompt, resume):
    executable = shutil.which(EXECUTABLES[tool])
    if not executable:
        return None
    if tool == "cursor":
        command = [executable, "-p", "-f", "--trust", "--model", model]
        if resume:
            command.extend(["--resume", resume])
        command.append(prompt)
        return command
    if resume:
        raise ValueError("Pi resume is not a router mode")
    # ponytail: packet is the contract; AGENTS.md / skill catalogs push the
    # worker into parent-orchestrator re-reads. Ceiling: misses project
    # conventions not in the packet. Upgrade: put those in the packet.
    return [
        executable,
        "-p",
        "--model",
        model,
        "--no-session",
        "--no-context-files",
        "--no-skills",
        prompt,
    ]


def terminate_group(process, grace):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def extract_report(raw_or_message, report):
    extracted = subprocess.run(
        [ROOT / "scripts" / "extract-report", raw_or_message, report],
        text=True,
        capture_output=True,
    )
    sys.stdout.write(extracted.stdout)
    sys.stderr.write(extracted.stderr)
    return extracted.returncode


def run_codex(args, prompt):
    """Codex uses `codex app-server` (native JSON-RPC), not a one-shot subprocess.

    The raw log holds the protocol JSONL (+ stderr under a marker); the worker's
    final agent message carries the DELEGATE_REPORT envelope, which is fed to the
    same extract-report/check-report contract as Pi/Cursor."""
    args.raw_log.parent.mkdir(parents=True, exist_ok=True)
    message_file = args.raw_log.with_suffix(args.raw_log.suffix + ".message")
    with args.raw_log.open("w") as raw:
        try:
            result = codex_app_server.run_delegation(
                prompt,
                cwd=Path.cwd(),
                model=args.model,
                raw_log=raw,
                sandbox=args.sandbox,
                reasoning_effort=args.reasoning_effort,
                timeout=args.timeout_seconds,
                term_grace_seconds=args.term_grace_seconds,
                resume_thread_id=args.resume,
            )
        except codex_app_server.CodexTimeout:
            failed_report(
                args.report,
                "TIMEOUT",
                f"codex delegation timed out after {args.timeout_seconds:g} seconds",
            )
            return 124
        except codex_app_server.CodexError as error:
            failed_report(args.report, error.reason, f"codex app-server: {error}")
            return 1
        except FileNotFoundError:
            raw.write("missing delegate CLI: codex app-server\n")
            failed_report(args.report, "MISSING_TOOL", "codex CLI is unavailable")
            return 127

    if result.status == "failed":
        failed_report(args.report, "CODEX_TURN_FAILED", result.error or "codex turn failed")
        return 1

    message_file.write_text(result.final_message or "")
    return extract_report(message_file, args.report)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", choices=("cursor", "pi", "codex"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--raw-log", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=900)
    parser.add_argument("--term-grace-seconds", type=float, default=5)
    parser.add_argument(
        "--sandbox",
        choices=("read-only", "workspace-write"),
        default="workspace-write",
        help="codex only: read-only for packet-critique, workspace-write for implementation",
    )
    parser.add_argument(
        "--reasoning-effort",
        default="xhigh",
        help="codex only: model_reasoning_effort (default xhigh)",
    )
    parser.add_argument("--resume")
    args = parser.parse_args()
    if not 0 < args.timeout_seconds <= 86400:
        parser.error("--timeout-seconds must be between 0 and 86400")
    if not 0 <= args.term_grace_seconds <= 30:
        parser.error("--term-grace-seconds must be between 0 and 30")

    prompt = args.prompt.read_text()

    if args.tool == "codex":
        return run_codex(args, prompt)

    try:
        command = command_for(args.tool, args.model, prompt, args.resume)
    except ValueError as error:
        parser.error(str(error))
    if command is None:
        args.raw_log.parent.mkdir(parents=True, exist_ok=True)
        args.raw_log.write_text(f"missing delegate CLI: {args.tool}\n")
        failed_report(args.report, "MISSING_TOOL", f"{args.tool} CLI is unavailable")
        return 127

    args.raw_log.parent.mkdir(parents=True, exist_ok=True)
    with args.raw_log.open("wb") as raw:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=raw,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            status = process.wait(timeout=args.timeout_seconds)
        except subprocess.TimeoutExpired:
            terminate_group(process, args.term_grace_seconds)
            try:
                process.wait(timeout=max(1.0, args.term_grace_seconds))
            except subprocess.TimeoutExpired:
                pass
            failed_report(
                args.report,
                "TIMEOUT",
                f"{args.tool} delegation timed out after {args.timeout_seconds:g} seconds",
            )
            return 124

    code = extract_report(args.raw_log, args.report)
    if code:
        return code
    return status


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OSError as error:
        print(f"delegate runner failed: {error}", file=sys.stderr)
        raise SystemExit(1)
