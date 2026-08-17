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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from acpx_events import normalize_record, parse_jsonl_line


ROOT = Path(__file__).resolve().parents[1]
PROFILE_BY_TOOL = {"cursor": "cursor", "codex": "codex", "pi": "pi"}


def failed_report(report, reason, summary):
    text = f"""DELEGATE_REPORT:
  STATUS: FAILED
  CHANGED_FILES: []
  VERIFICATION: []
  CONCERNS:
    - TYPE: {reason}
      DETAIL: {summary}
      RECOMMENDED_ACTION: Inspect the preserved raw log
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


def build_acpx_command(base, tool, subcommand, prompt_path, session=None):
    profile = PROFILE_BY_TOOL[tool]
    command = base + [profile, subcommand]
    if session:
        command.extend(["-s", session])
    command.extend(["--file", str(prompt_path)])
    return command


def planned_invocations(args):
    profile = PROFILE_BY_TOOL[args.tool]
    follow_ups = list(args.follow_up)
    if follow_ups and args.tool != "pi":
        raise ValueError("--follow-up is only supported for Pi")
    if args.tool == "pi" and args.resume:
        raise ValueError("Pi resume is not a router mode")

    prompt_dir = args.prompt.parent
    turns = [(args.prompt, "prompt" if args.resume or follow_ups else "exec", args.resume)]
    for index, text in enumerate(follow_ups):
        path = prompt_dir / f"follow-up-{index}.txt"
        path.write_text(text)
        turns.append((path, "prompt", args.resume))

    preflight = []
    if follow_ups and not args.resume:
        preflight.append(("sessions", "ensure", None))
    return profile, preflight, turns


def run_acpx_process(command, args, raw, deadline):
    events = queue.Queue()
    report_text = ""
    assistant_text = []
    failure = ""
    failure_reason = "ACP_EVENT_FAILED"
    terminal = False
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
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

    eof = set()
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                terminate_group(process, args.term_grace_seconds)
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
    if exit_code == 3:
        return {
            "exit_code": 124,
            "failure_reason": "TIMEOUT",
            "failure": f"{args.tool} delegation timed out after {args.timeout_seconds:g} seconds",
        }
    if exit_code == 130:
        return {
            "exit_code": 130,
            "failure_reason": "CANCELLED",
            "failure": f"{args.tool} delegation cancelled",
        }
    if failure:
        return {
            "exit_code": 1,
            "failure_reason": failure_reason,
            "failure": failure,
        }
    if exit_code not in (0,) and not terminal:
        return {
            "exit_code": exit_code or 1,
            "failure_reason": "ACP_EVENT_FAILED",
            "failure": f"acpx exited with status {exit_code}",
        }
    if not terminal:
        return {
            "exit_code": 1,
            "failure_reason": "MISSING_TERMINAL_EVENT",
            "failure": "delegate produced no terminal ACP event",
        }
    combined = "".join(assistant_text)
    crash = _cursor_step_crash(combined)
    if crash:
        return {
            "exit_code": 1,
            "failure_reason": "ACP_EVENT_FAILED",
            "failure": crash,
        }
    if not report_text:
        report_text = combined if _report_text(combined) else ""
    if not report_text:
        return {
            "exit_code": 1,
            "failure_reason": "MISSING_STRUCTURED_REPORT",
            "failure": "delegate produced no structured report text",
        }
    return {"exit_code": exit_code, "report_text": report_text}


def _cursor_step_crash(text):
    if "RetriableError" in text or "Failed to run step, exceeded max retries" in text:
        return text.strip() or "Cursor ACP failed to run step"
    return ""


def _report_text(text):
    if "ROUTER_REPORT_BEGIN" in text and "ROUTER_REPORT_END" in text:
        return text
    return ""


def run_acpx(args):
    executable = acpx_path()
    if not executable:
        args.raw_log.parent.mkdir(parents=True, exist_ok=True)
        args.raw_log.write_text("missing delegate CLI: acpx\n")
        failed_report(args.report, "MISSING_TOOL", "acpx is unavailable")
        return 127

    try:
        profile, preflight, turns = planned_invocations(args)
    except ValueError as error:
        raise error

    cwd = Path.cwd()
    base = build_acpx_base(args, cwd, executable)
    args.raw_log.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + args.timeout_seconds
    last_report = ""

    with args.raw_log.open("w") as raw:
        for kind, subcommand, _session in preflight:
            command = base + [profile, "sessions", subcommand]
            outcome = run_acpx_process(command, args, raw, deadline)
            if outcome.get("failure"):
                failed_report(args.report, outcome["failure_reason"], outcome["failure"])
                return outcome.get("exit_code", 1)

        for prompt_path, subcommand, session in turns:
            command = build_acpx_command(base, args.tool, subcommand, prompt_path, session)
            outcome = run_acpx_process(command, args, raw, deadline)
            if outcome.get("failure"):
                failed_report(args.report, outcome["failure_reason"], outcome["failure"])
                return outcome.get("exit_code", 1)
            last_report = outcome.get("report_text") or last_report

    code = extract_report_text(last_report, args.raw_log, args.report)
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
    parser.add_argument("--resume")
    parser.add_argument("--follow-up", action="append", default=[])
    args = parser.parse_args()
    if not 0 < args.timeout_seconds <= 86400:
        parser.error("--timeout-seconds must be between 0 and 86400")
    if not 0 <= args.term_grace_seconds <= 30:
        parser.error("--term-grace-seconds must be between 0 and 30")

    try:
        return run_acpx(args)
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OSError as error:
        print(f"delegate runner failed: {error}", file=sys.stderr)
        raise SystemExit(1)
