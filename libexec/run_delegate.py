#!/usr/bin/env python3
import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


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
    return [executable, "-p", "--model", model, "--no-session", prompt]


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", choices=("cursor", "pi"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--raw-log", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=900)
    parser.add_argument("--term-grace-seconds", type=float, default=5)
    parser.add_argument("--resume")
    args = parser.parse_args()
    if not 0 < args.timeout_seconds <= 86400:
        parser.error("--timeout-seconds must be between 0 and 86400")
    if not 0 <= args.term_grace_seconds <= 30:
        parser.error("--term-grace-seconds must be between 0 and 30")

    prompt = args.prompt.read_text()
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

    extracted = subprocess.run(
        [ROOT / "scripts" / "extract-report", args.raw_log, args.report],
        text=True,
        capture_output=True,
    )
    sys.stdout.write(extracted.stdout)
    sys.stderr.write(extracted.stderr)
    if extracted.returncode:
        return extracted.returncode
    return status


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OSError as error:
        print(f"delegate runner failed: {error}", file=sys.stderr)
        raise SystemExit(1)
