#!/usr/bin/env python3
"""Run router delegates through acpx (ACP client) for cursor, codex, and pi."""

import argparse
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from acpx_events import normalize_record, parse_jsonl_line
from subagent_status import TERMINAL_STATES, SubagentStatusTracker, emit_ndjson


ROOT = Path(__file__).resolve().parents[1]
PROFILE_BY_TOOL = {"cursor": "cursor", "codex": "codex", "pi": "pi"}


def debug_log_path(raw_log):
    return raw_log.parent / "debug.log"


def emit_debug(log_path, message):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[ajax-router] {timestamp} {message}\n"
    sys.stderr.write(line)
    sys.stderr.flush()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as handle:
        handle.write(line)


def failed_report(report, reason, summary, *, raw_log=None, debug_log=None):
    if debug_log and raw_log:
        action = f"Inspect {debug_log} and {raw_log}"
    elif raw_log:
        action = f"Inspect {raw_log}"
    else:
        action = "Inspect the preserved raw log"
    text = f"""DELEGATE_REPORT:
  STATUS: FAILED
  CHANGED_FILES: []
  VERIFICATION: []
  CONCERNS:
    - TYPE: {reason}
      DETAIL: {summary}
      RECOMMENDED_ACTION: {action}
"""
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(text)
    sys.stdout.write(text)


def terminate_group(process, grace):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.terminate()
        except OSError:
            return
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        try:
            os.killpg(process.pid, 0)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                process.wait(timeout=0.05)
            except subprocess.TimeoutExpired:
                pass
            return
        time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.kill()
        except OSError:
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
    begin = "ROUTER_REPORT_BEGIN"
    end = "ROUTER_REPORT_END"
    start = text.find(begin)
    stop = text.find(end)
    if start >= 0 and stop > start:
        inner = text[start + len(begin) : stop].strip("\n")
        text = f"{begin}\n{inner}\n{end}\n"
    message = raw_log.with_suffix(raw_log.suffix + ".message")
    message.write_text(text)
    return extract_report(message, report)


def acpx_path():
    return shutil.which("acpx")


def build_acpx_base(args, cwd, executable):
    return [
        executable,
        "--approve-all",
        "--non-interactive-permissions",
        "fail",
        "--format",
        "json",
        "--json-strict",
        "--cwd",
        str(cwd),
        "--model",
        args.model,
        "--timeout",
        str(args.timeout_seconds),
    ]


def build_acpx_command(base, tool, prompt_path):
    profile = PROFILE_BY_TOOL[tool]
    return base + [profile, "exec", "--file", str(prompt_path)]


def run_acpx_process(command, args, raw, deadline):
    events = queue.Queue()
    report_text = ""
    assistant_text = []
    failure = ""
    failure_reason = "ACP_EVENT_FAILED"
    terminal = False
    tracker = None
    if args.run_id and args.parent_task_id:
        tracker = SubagentStatusTracker(
            args.run_id,
            args.parent_task_id,
            args.tool,
            args.model,
            args.task or args.tool,
            emit=emit_ndjson,
            stall_seconds=args.stall_seconds,
        )
        tracker.event("queued", "Waiting to start")
        tracker.event("starting", "Launching delegate")
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            text=True,
            bufsize=1,
        )
    except OSError as error:
        if tracker:
            tracker.terminal("failed", f"Launch failed: {error}")
        return {
            "exit_code": 1,
            "failure_reason": "ACP_EVENT_FAILED",
            "failure": f"failed to launch acpx: {error}",
        }

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

    eof = set()
    if tracker:
        tracker.event("running", "Delegate active")
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                terminate_group(process, args.term_grace_seconds)
                if tracker:
                    tracker.terminal(
                        "failed",
                        f"Timed out after {args.timeout_seconds:g} seconds",
                    )
                return {
                    "exit_code": 124,
                    "failure_reason": "TIMEOUT",
                    "failure": f"{args.tool} delegation timed out after {args.timeout_seconds:g} seconds",
                }
            try:
                stream, line = events.get(timeout=min(0.1, remaining))
            except queue.Empty:
                stream = None
                line = None
                if tracker:
                    tracker.maybe_stalled()
            if stream is not None:
                if line is None:
                    eof.add(stream)
                elif stream == "stderr":
                    raw.write("[stderr] " + line)
                    raw.flush()
                    if line.startswith("[acpx] error:"):
                        failure = line.strip()
                        failure_reason = "ACP_EVENT_FAILED"
                        terminal = True
                else:
                    raw.write(line)
                    raw.flush()
                    if tracker:
                        tracker.handle_stdout_line(line)
                    record = parse_jsonl_line(line)
                    if record is None:
                        continue
                    event = normalize_record(record)
                    if event is None:
                        continue
                    if event.text:
                        assistant_text.append(event.text)
                    if event.report_text:
                        report_text = event.report_text
                    if event.kind == "failed":
                        failure = event.error or "acpx ACP event reported failure"
                        failure_reason = "ACP_EVENT_FAILED"
                        terminal = True
                    elif event.kind == "completed":
                        terminal = True
            if process.poll() is not None and "stdout" in eof and "stderr" in eof:
                if not terminal and not failure:
                    failure = "delegate exited without a terminal ACP event"
                    failure_reason = "MISSING_TERMINAL_EVENT"
                break
            if (terminal or failure) and "stderr" in eof:
                break
    except KeyboardInterrupt:
        terminate_group(process, args.term_grace_seconds)
        if tracker:
            tracker.terminal("cancelled", "Delegation cancelled")
        return {
            "exit_code": 130,
            "failure_reason": "CANCELLED",
            "failure": f"{args.tool} delegation cancelled",
        }
    finally:
        if process.poll() is None:
            try:
                process.wait(timeout=max(1.0, args.term_grace_seconds))
            except subprocess.TimeoutExpired:
                terminate_group(process, args.term_grace_seconds)
        for thread in threads:
            thread.join(timeout=1)
        for stream in (process.stdin, process.stdout, process.stderr):
            try:
                if stream:
                    stream.close()
            except (AttributeError, OSError):
                pass

    exit_code = process.returncode if process.returncode is not None else 1

    def finish(outcome):
        if tracker:
            reason = outcome.get("failure_reason", "")
            if reason == "CANCELLED":
                tracker.terminal("cancelled", outcome.get("failure", "Cancelled"))
            elif reason == "TIMEOUT":
                tracker.terminal("failed", outcome.get("failure", "Timed out"))
            elif reason in {"ACP_EVENT_FAILED", "MISSING_TERMINAL_EVENT", "MISSING_STRUCTURED_REPORT"}:
                tracker.terminal("failed", outcome.get("failure", reason))
            elif outcome.get("report_text"):
                if tracker.state != "completed":
                    tracker.terminal("completed", "Delegate finished")
            else:
                tracker.terminal("failed", outcome.get("failure", "Delegate failed"))
        return outcome

    if exit_code == 3:
        return finish({
            "exit_code": 124,
            "failure_reason": "TIMEOUT",
            "failure": f"{args.tool} delegation timed out after {args.timeout_seconds:g} seconds",
        })
    if exit_code == 130:
        return finish({
            "exit_code": 130,
            "failure_reason": "CANCELLED",
            "failure": f"{args.tool} delegation cancelled",
        })
    if failure:
        return finish({
            "exit_code": 1,
            "failure_reason": failure_reason,
            "failure": failure,
        })
    if exit_code not in (0,) and not terminal:
        return finish({
            "exit_code": exit_code or 1,
            "failure_reason": "ACP_EVENT_FAILED",
            "failure": f"acpx exited with status {exit_code}",
        })
    if not terminal:
        return finish({
            "exit_code": 1,
            "failure_reason": "MISSING_TERMINAL_EVENT",
            "failure": "delegate produced no terminal ACP event",
        })
    combined = "".join(assistant_text)
    crash = _cursor_step_crash(combined)
    if crash:
        return finish({
            "exit_code": 1,
            "failure_reason": "ACP_EVENT_FAILED",
            "failure": crash,
        })
    if not report_text:
        report_text = combined if _report_text(combined) else ""
    if not report_text:
        return finish({
            "exit_code": 1,
            "failure_reason": "MISSING_STRUCTURED_REPORT",
            "failure": "delegate produced no structured report text",
        })
    return finish({"exit_code": exit_code, "report_text": report_text})


def _cursor_step_crash(text):
    if "RetriableError" in text or "Failed to run step, exceeded max retries" in text:
        return text.strip() or "Cursor ACP failed to run step"
    return ""


def _report_text(text):
    if "ROUTER_REPORT_BEGIN" in text and "ROUTER_REPORT_END" in text:
        return text
    return ""


def _log_failure(debug, args, outcome):
    emit_debug(
        debug,
        "failure "
        f"reason={outcome['failure_reason']} "
        f"message={outcome['failure']} "
        f"exit={outcome.get('exit_code', 1)} "
        f"raw_log={args.raw_log}",
    )
    failed_report(
        args.report,
        outcome["failure_reason"],
        outcome["failure"],
        raw_log=args.raw_log,
        debug_log=debug,
    )


def run_acpx(args):
    debug = debug_log_path(args.raw_log)
    executable = acpx_path()
    if not executable:
        args.raw_log.parent.mkdir(parents=True, exist_ok=True)
        args.raw_log.write_text("missing delegate CLI: acpx\n")
        emit_debug(debug, "MISSING_TOOL acpx is unavailable")
        failed_report(
            args.report,
            "MISSING_TOOL",
            "acpx is unavailable",
            raw_log=args.raw_log,
            debug_log=debug,
        )
        return 127

    cwd = Path.cwd()
    base = build_acpx_base(args, cwd, executable)
    args.raw_log.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + args.timeout_seconds
    command = build_acpx_command(base, args.tool, args.prompt)

    with args.raw_log.open("w") as raw:
        emit_debug(
            debug,
            "start "
            f"tool={args.tool} model={args.model} cwd={cwd} "
            f"timeout_seconds={args.timeout_seconds:g} "
            f"argv={' '.join(map(str, command))}",
        )
        outcome = run_acpx_process(command, args, raw, deadline)
        if outcome.get("failure"):
            _log_failure(debug, args, outcome)
            return outcome.get("exit_code", 1)
        last_report = outcome.get("report_text") or ""

    code = extract_report_text(last_report, args.raw_log, args.report)
    emit_debug(debug, f"extract-report exit={code}")
    if code == 0:
        emit_debug(debug, "complete")
    return code or 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", choices=tuple(PROFILE_BY_TOOL), required=True)
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
        help="retained for router contract; not forwarded to acpx ACP in this transport",
    )
    parser.add_argument(
        "--reasoning-effort",
        default="xhigh",
        help="retained for router contract; not forwarded to acpx ACP in this transport",
    )
    parser.add_argument("--run-id", help="unique child run id for subagent_status events")
    parser.add_argument(
        "--parent-task-id",
        help="parent chat/task id for subagent_status events",
    )
    parser.add_argument(
        "--task",
        default="",
        help="short task label for subagent_status events",
    )
    parser.add_argument(
        "--stall-seconds",
        type=float,
        default=60.0,
        help="seconds without ACP activity before emitting stalled",
    )
    args = parser.parse_args()
    if not 0 < args.timeout_seconds <= 86400:
        parser.error("--timeout-seconds must be between 0 and 86400")
    if not 0 <= args.term_grace_seconds <= 30:
        parser.error("--term-grace-seconds must be between 0 and 30")
    if not 0 < args.stall_seconds <= 3600:
        parser.error("--stall-seconds must be between 0 and 3600")

    return run_acpx(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OSError as error:
        print(f"delegate runner failed: {error}", file=sys.stderr)
        raise SystemExit(1)
