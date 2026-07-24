#!/usr/bin/env python3
import argparse
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codex_app_server
from delegate_events import normalize_record, parse_jsonl_line


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
        command.extend(["--output-format", "stream-json", "--stream-partial-output"])
        command.append(prompt)
        return command
    if resume:
        raise ValueError("Pi resume is not a router mode")
    # ponytail: packet is the contract; AGENTS.md / skill catalogs push the
    # worker into parent-orchestrator re-reads. Ceiling: misses project
    # conventions not in the packet. Upgrade: put those in the packet.
    return [
        executable,
        "--mode",
        "rpc",
        "--model",
        model,
        "--no-session",
        "--no-context-files",
        "--no-skills",
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


def extract_report_text(text, raw_log, report):
    message = raw_log.with_suffix(raw_log.suffix + ".message")
    message.write_text(text)
    return extract_report(message, report)


def _native_command(args, prompt):
    command = command_for(args.tool, args.model, prompt, args.resume)
    if args.tool == "pi" and args.resume:
        raise ValueError("Pi resume is not a router mode")
    return command


def run_native(args, prompt):
    command = _native_command(args, prompt)
    follow_ups = list(args.follow_up)
    if follow_ups and args.tool != "pi":
        raise ValueError("--follow-up is only supported for Pi")

    args.raw_log.parent.mkdir(parents=True, exist_ok=True)
    events = queue.Queue()
    report_text = ""
    failure = ""
    failure_reason = "NATIVE_EVENT_FAILED"
    terminal = False
    follow_up_index = 0
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        text=True,
        bufsize=1,
    )

    def pump(name, stream):
        try:
            for line in stream:
                events.put((name, line))
        finally:
            events.put((name, None))

    threads = [
        threading.Thread(target=pump, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=pump, args=("stderr", process.stderr), daemon=True),
    ]
    for thread in threads:
        thread.start()

    def send(kind, message):
        try:
            process.stdin.write(json.dumps({"id": f"delegate-{kind}", "type": kind, "message": message}) + "\n")
            process.stdin.flush()
            return True
        except (BrokenPipeError, OSError):
            return False

    def close_stdin():
        if process.stdin and not process.stdin.closed:
            process.stdin.close()

    if not send("prompt", prompt):
        failure = "delegate stdin closed before prompt was accepted"
        failure_reason = "NATIVE_EVENT_FAILED"
    deadline = time.monotonic() + args.timeout_seconds
    eof = set()
    try:
        with args.raw_log.open("w") as raw:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    terminate_group(process, args.term_grace_seconds)
                    failed_report(
                        args.report,
                        "TIMEOUT",
                        f"{args.tool} delegation timed out after {args.timeout_seconds:g} seconds",
                    )
                    return 124
                try:
                    stream, line = events.get(timeout=min(0.1, remaining))
                except queue.Empty:
                    line = None
                    stream = None
                if stream is not None:
                    if line is None:
                        eof.add(stream)
                    elif stream == "stderr":
                        raw.write("[stderr] " + line)
                        raw.flush()
                    else:
                        raw.write(line)
                        raw.flush()
                        record = parse_jsonl_line(line)
                        if record is None:
                            continue
                        event = normalize_record(args.tool, record)
                        if event is None:
                            continue
                        if event.report_text:
                            report_text = event.report_text
                        if event.kind == "failed":
                            failure = event.error or "native delegate event reported failure"
                            failure_reason = "NATIVE_EVENT_FAILED"
                            terminal = True
                            close_stdin()
                        elif event.kind == "completed":
                            terminal = True
                            if follow_up_index < len(follow_ups):
                                if not send("follow_up", follow_ups[follow_up_index]):
                                    failure = "delegate stdin closed before follow-up was accepted"
                                    failure_reason = "NATIVE_EVENT_FAILED"
                                follow_up_index += 1
                                terminal = False
                            elif args.tool == "pi":
                                close_stdin()
                if process.poll() is not None:
                    if terminal or failure:
                        break
                    if "stdout" in eof and "stderr" in eof:
                        failure = "delegate exited without a terminal native event"
                        failure_reason = "MISSING_TERMINAL_EVENT"
                        break
                if terminal and args.tool == "cursor":
                    break
                if failure:
                    break
    except KeyboardInterrupt:
        terminate_group(process, args.term_grace_seconds)
        failed_report(args.report, "CANCELLED", f"{args.tool} delegation cancelled")
        return 130
    finally:
        if process.poll() is None:
            close_stdin()
            try:
                process.wait(timeout=max(1.0, args.term_grace_seconds))
            except subprocess.TimeoutExpired:
                terminate_group(process, args.term_grace_seconds)
        for thread in threads:
            thread.join(timeout=1)
        for stream in (process.stdin, process.stdout, process.stderr):
            try:
                stream.close()
            except (AttributeError, OSError):
                pass

    if failure:
        failed_report(args.report, failure_reason, failure)
        return 1
    if not terminal:
        failed_report(args.report, "MISSING_TERMINAL_EVENT", "delegate produced no terminal native event")
        return 1
    if not report_text:
        failed_report(args.report, "MISSING_STRUCTURED_REPORT", "delegate produced no structured report text")
        return 1
    code = extract_report_text(report_text, args.raw_log, args.report)
    return code or process.returncode


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
    parser.add_argument("--follow-up", action="append", default=[])
    args = parser.parse_args()
    if not 0 < args.timeout_seconds <= 86400:
        parser.error("--timeout-seconds must be between 0 and 86400")
    if not 0 <= args.term_grace_seconds <= 30:
        parser.error("--term-grace-seconds must be between 0 and 30")

    prompt = args.prompt.read_text()

    if args.tool == "codex":
        return run_codex(args, prompt)

    if args.tool in {"pi", "cursor"}:
        try:
            return run_native(args, prompt)
        except ValueError as error:
            parser.error(str(error))

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
