#!/usr/bin/env python3
"""Stdio JSON-RPC filter wrapping cursor-agent/agent for acpx Cursor delegates.

Intercepts cursor/* extension requests from the agent (stdout toward acpx) and
answers them locally so acpx never sees unsupported extMethod calls.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading


CURSOR_EXT_METHODS = frozenset({
    "cursor/task",
    "cursor/ask_question",
    "cursor/create_plan",
    "cursor/update_todos",
    "cursor/generate_image",
})

TASK_REJECT_REASON = (
    "Nested subagents are unsupported in router delegates; continue in-process."
)


def parse_json_line(line):
    try:
        value = json.loads(line)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def is_cursor_ext_request(record):
    if not isinstance(record, dict):
        return False
    if record.get("id") is None:
        return False
    return record.get("method") in CURSOR_EXT_METHODS


def build_result(method, params):
    if method == "cursor/task":
        return {
            "outcome": {
                "outcome": "rejected",
                "reason": TASK_REJECT_REASON,
            }
        }
    if method == "cursor/ask_question":
        return {"outcome": {"outcome": "skipped"}}
    if method == "cursor/create_plan":
        return {
            "outcome": {
                "outcome": "rejected",
                "reason": "Planning mode is unsupported in router delegates.",
            }
        }
    if method == "cursor/update_todos":
        todos = []
        if isinstance(params, dict):
            raw = params.get("todos")
            if isinstance(raw, list):
                todos = raw
        return {"outcome": {"outcome": "accepted", "todos": todos}}
    if method == "cursor/generate_image":
        return {
            "outcome": {
                "outcome": "rejected",
                "reason": "Image generation is unsupported in router delegates.",
            }
        }
    return {"outcome": {"outcome": "rejected", "reason": "Unsupported cursor extension."}}


def response_for_request(record):
    method = record.get("method")
    params = record.get("params")
    return {
        "jsonrpc": "2.0",
        "id": record.get("id"),
        "result": build_result(method, params),
    }


def resolve_real_agent():
    explicit = (os.environ.get("CURSOR_ACP_FILTER_REAL_AGENT") or "").strip()
    if explicit:
        return explicit
    for name in ("cursor-agent", "agent"):
        path = shutil_which(name)
        if path and not _is_filter_entrypoint(path):
            return path
    return ""


def _is_filter_entrypoint(path):
    try:
        resolved = os.path.realpath(path)
    except OSError:
        return False
    return resolved == os.path.realpath(__file__)


def shutil_which(name, path=None):
    path = os.environ.get("PATH", "") if path is None else path
    for entry in path.split(os.pathsep):
        if not entry:
            continue
        candidate = os.path.join(entry, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def iter_fd_lines(fd):
    """Yield decoded NDJSON lines as soon as bytes arrive (no 8KiB readahead)."""
    buf = b""
    while True:
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        buf += chunk
        while True:
            npos = buf.find(b"\n")
            if npos < 0:
                break
            line, buf = buf[: npos + 1], buf[npos + 1 :]
            yield line.decode("utf-8", "replace")
    if buf:
        yield buf.decode("utf-8", "replace")


def write_fd(fd, payload, lock):
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    with lock:
        while data:
            try:
                n = os.write(fd, data)
            except OSError:
                return
            if n <= 0:
                return
            data = data[n:]


def run_filter(agent_command, agent_args):
    agent = subprocess.Popen(
        [agent_command, *agent_args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    stdin_lock = threading.Lock()
    stdout_lock = threading.Lock()
    stderr_lock = threading.Lock()

    def write_agent(payload):
        if agent.stdin is None:
            return
        write_fd(agent.stdin.fileno(), payload, stdin_lock)

    def write_client(payload):
        write_fd(sys.stdout.fileno(), payload, stdout_lock)

    def pump_client_to_agent():
        try:
            for line in iter_fd_lines(sys.stdin.fileno()):
                write_agent(line if line.endswith("\n") else line + "\n")
        finally:
            try:
                if agent.stdin is not None:
                    agent.stdin.close()
            except OSError:
                pass

    def pump_agent_stderr():
        try:
            for line in iter_fd_lines(agent.stderr.fileno()):
                write_fd(sys.stderr.fileno(), line if line.endswith("\n") else line + "\n", stderr_lock)
        finally:
            try:
                agent.stderr.close()
            except OSError:
                pass

    def pump_agent_to_client():
        try:
            for line in iter_fd_lines(agent.stdout.fileno()):
                record = parse_json_line(line)
                if is_cursor_ext_request(record):
                    write_agent(json.dumps(response_for_request(record)) + "\n")
                    continue
                write_client(line if line.endswith("\n") else line + "\n")
        finally:
            try:
                agent.stdout.close()
            except OSError:
                pass

    threads = [
        threading.Thread(target=pump_client_to_agent, daemon=True),
        threading.Thread(target=pump_agent_to_client, daemon=True),
        threading.Thread(target=pump_agent_stderr, daemon=True),
    ]
    for thread in threads:
        thread.start()
    exit_code = agent.wait()
    try:
        sys.stdin.close()
    except OSError:
        pass
    for thread in threads:
        thread.join(timeout=1)
    return exit_code


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    real_agent = resolve_real_agent()
    if not real_agent:
        print("cursor_acp_filter: real cursor-agent/agent binary not found", file=sys.stderr)
        return 127
    return run_filter(real_agent, argv)


if __name__ == "__main__":
    raise SystemExit(main())
