#!/usr/bin/env python3
"""Stdio JSON-RPC filter wrapping cursor-agent/agent for acpx Cursor delegates.

Intercepts cursor/* extension requests from the agent (stdout toward acpx) and
answers them locally so acpx never sees unsupported extMethod calls.
"""

from __future__ import annotations

import errno
import json
import os
import select
import signal
import subprocess
import sys
import threading
import time


DIAG_PREFIX = "[cursor-acp-filter]"
CURSOR_EXT_METHODS = frozenset({
    "cursor/task",
    "cursor/ask_question",
    "cursor/create_plan",
    "cursor/update_todos",
    "cursor/generate_image",
})
DEFAULT_DRAIN_TIMEOUT_SECONDS = 30.0

TASK_REJECT_REASON = (
    "Nested subagents are unsupported in router delegates; continue in-process."
)


class PipeFailure(Exception):
    def __init__(self, operation, direction, error, *, child_pid=None):
        self.operation = operation
        self.direction = direction
        self.error = error
        self.child_pid = child_pid
        super().__init__(str(error))


def drain_timeout_seconds():
    raw = (os.environ.get("CURSOR_ACP_FILTER_DRAIN_TIMEOUT") or "").strip()
    if not raw:
        return DEFAULT_DRAIN_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_DRAIN_TIMEOUT_SECONDS
    return max(0.1, value)


def log_diagnostic(message, *, operation="", direction="", error=None, child_pid=None, exit_code=None, signal_num=None):
    parts = [DIAG_PREFIX, message]
    if operation:
        parts.append(f"operation={operation}")
    if direction:
        parts.append(f"direction={direction}")
    if error is not None:
        parts.append(f"error={error}")
        err_no = getattr(error, "errno", None)
        if err_no is not None:
            parts.append(f"errno={err_no}")
    if child_pid is not None:
        parts.append(f"child_pid={child_pid}")
    if exit_code is not None:
        parts.append(f"exit_code={exit_code}")
    if signal_num is not None:
        parts.append(f"signal={signal_num}")
    line = " ".join(parts) + "\n"
    sys.stderr.write(line)
    sys.stderr.flush()


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


def is_unknown_cursor_ext_request(record):
    if not isinstance(record, dict):
        return False
    if record.get("id") is None:
        return False
    method = record.get("method")
    return isinstance(method, str) and method.startswith("cursor/") and method not in CURSOR_EXT_METHODS


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


def error_response_for_unknown(record):
    method = record.get("method")
    return {
        "jsonrpc": "2.0",
        "id": record.get("id"),
        "error": {
            "code": -32601,
            "message": f"Method not found: {method}",
        },
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


def iter_fd_lines_until_stop(fd, stop, poll_seconds=0.1):
    """Yield NDJSON lines from fd until EOF, error, or stop is set."""
    buf = b""
    while not stop.is_set():
        try:
            ready, _, _ = select.select([fd], [], [], poll_seconds)
        except (OSError, ValueError):
            break
        if stop.is_set():
            break
        if not ready:
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError as exc:
            raise PipeFailure("read", "unknown", exc) from exc
        if not chunk:
            break
        buf += chunk
        while True:
            npos = buf.find(b"\n")
            if npos < 0:
                break
            line, buf = buf[: npos + 1], buf[npos + 1 :]
            yield line.decode("utf-8", "replace")
    if buf and not stop.is_set():
        yield buf.decode("utf-8", "replace")


def iter_fd_lines(fd):
    """Yield decoded NDJSON lines as soon as bytes arrive (no 8KiB readahead)."""
    buf = b""
    while True:
        try:
            chunk = os.read(fd, 4096)
        except OSError as exc:
            raise PipeFailure("read", "unknown", exc) from exc
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
            except OSError as exc:
                raise PipeFailure("write", "unknown", exc) from exc
            if n <= 0:
                raise PipeFailure("write", "unknown", OSError(errno.EIO, "write returned no progress"))
            data = data[n:]


class FilterState:
    def __init__(self, child):
        self.child = child
        self.stop = threading.Event()
        self.failure = None
        self.lock = threading.Lock()

    def note_failure(self, failure):
        with self.lock:
            if self.failure is None:
                self.failure = failure
            self.stop.set()

    def child_pid(self):
        return self.child.pid if self.child is not None else None


def terminate_child(agent, state):
    """SIGTERM then SIGKILL a child that may ignore stdin EOF."""
    if agent.poll() is not None:
        return agent.returncode
    try:
        agent.terminate()
        agent.wait(timeout=1)
    except subprocess.TimeoutExpired:
        try:
            agent.kill()
        except OSError:
            pass
        try:
            agent.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
    except OSError as exc:
        log_diagnostic(
            "terminate failed",
            operation="terminate",
            direction="parent_to_child",
            error=exc,
            child_pid=state.child_pid(),
        )
    return agent.returncode if agent.returncode is not None else 1


def run_filter(agent_command, agent_args):
    agent = subprocess.Popen(
        [agent_command, *agent_args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    state = FilterState(agent)
    stdin_lock = threading.Lock()
    stdout_lock = threading.Lock()
    stderr_lock = threading.Lock()

    def write_agent(payload, direction="client_to_agent"):
        if state.stop.is_set() or agent.stdin is None:
            return
        try:
            write_fd(agent.stdin.fileno(), payload, stdin_lock)
        except PipeFailure as failure:
            failure.direction = direction
            failure.child_pid = state.child_pid()
            state.note_failure(failure)
            log_diagnostic(
                "write failed",
                operation=failure.operation,
                direction=failure.direction,
                error=failure.error,
                child_pid=failure.child_pid,
            )

    def write_client(payload, direction="agent_to_client"):
        if state.stop.is_set():
            return
        try:
            write_fd(sys.stdout.fileno(), payload, stdout_lock)
        except PipeFailure as failure:
            failure.direction = direction
            failure.child_pid = state.child_pid()
            state.note_failure(failure)
            log_diagnostic(
                "write failed",
                operation=failure.operation,
                direction=failure.direction,
                error=failure.error,
                child_pid=failure.child_pid,
            )

    def pump_client_to_agent():
        direction = "client_to_agent"
        try:
            for line in iter_fd_lines_until_stop(sys.stdin.fileno(), state.stop):
                write_agent(line if line.endswith("\n") else line + "\n", direction)
        except PipeFailure as failure:
            failure.direction = direction
            failure.child_pid = state.child_pid()
            state.note_failure(failure)
            log_diagnostic(
                "read failed",
                operation=failure.operation,
                direction=failure.direction,
                error=failure.error,
                child_pid=failure.child_pid,
            )
        finally:
            try:
                if agent.stdin is not None:
                    agent.stdin.close()
            except OSError:
                pass

    def pump_agent_stderr():
        direction = "agent_stderr_to_client"
        try:
            for line in iter_fd_lines(agent.stderr.fileno()):
                if state.stop.is_set():
                    break
                write_fd(sys.stderr.fileno(), line if line.endswith("\n") else line + "\n", stderr_lock)
        except PipeFailure as failure:
            failure.direction = direction
            failure.child_pid = state.child_pid()
            state.note_failure(failure)
            log_diagnostic(
                "read failed",
                operation=failure.operation,
                direction=failure.direction,
                error=failure.error,
                child_pid=failure.child_pid,
            )
        finally:
            try:
                agent.stderr.close()
            except OSError:
                pass

    def handle_agent_line(line):
        record = parse_json_line(line)
        if is_cursor_ext_request(record):
            write_agent(json.dumps(response_for_request(record)) + "\n", "agent_to_agent")
            return
        if is_unknown_cursor_ext_request(record):
            method = record.get("method")
            log_diagnostic(
                "unknown cursor extension",
                operation="intercept",
                direction="agent_to_client",
                error=f"method={method}",
                child_pid=state.child_pid(),
            )
            write_agent(json.dumps(error_response_for_unknown(record)) + "\n", "agent_to_agent")
            return
        write_client(line if line.endswith("\n") else line + "\n", "agent_to_client")

    def pump_agent_to_client():
        direction = "agent_to_client"
        try:
            for line in iter_fd_lines(agent.stdout.fileno()):
                if state.stop.is_set():
                    break
                handle_agent_line(line)
        except PipeFailure as failure:
            failure.direction = direction
            failure.child_pid = state.child_pid()
            state.note_failure(failure)
            log_diagnostic(
                "read failed",
                operation=failure.operation,
                direction=failure.direction,
                error=failure.error,
                child_pid=failure.child_pid,
            )
        finally:
            try:
                agent.stdout.close()
            except OSError:
                pass

    def forward_signal(signum, _frame):
        state.stop.set()
        try:
            os.close(sys.stdin.fileno())
        except OSError:
            pass
        if agent.poll() is None:
            try:
                agent.send_signal(signum)
            except OSError as exc:
                log_diagnostic(
                    "signal forward failed",
                    operation="signal",
                    direction="parent_to_child",
                    error=exc,
                    child_pid=state.child_pid(),
                    signal_num=signum,
                )

    previous_sigint = signal.getsignal(signal.SIGINT)
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, forward_signal)
    signal.signal(signal.SIGTERM, forward_signal)

    threads = [
        threading.Thread(target=pump_client_to_agent, name="client_to_agent", daemon=False),
        threading.Thread(target=pump_agent_to_client, name="agent_to_client", daemon=False),
        threading.Thread(target=pump_agent_stderr, name="agent_stderr", daemon=False),
    ]
    for thread in threads:
        thread.start()

    while agent.poll() is None:
        if state.failure is not None:
            log_diagnostic(
                "forwarding failure; terminating child",
                operation="terminate",
                direction="shutdown",
                error=state.failure.error,
                child_pid=state.child_pid(),
            )
            terminate_child(agent, state)
            break
        time.sleep(0.05)

    exit_code = agent.returncode if agent.returncode is not None else 0
    state.stop.set()
    try:
        os.close(sys.stdin.fileno())
    except OSError:
        try:
            sys.stdin.close()
        except OSError:
            pass

    drain_deadline = time.monotonic() + drain_timeout_seconds()
    drain_timed_out = False
    for thread in threads:
        remaining = drain_deadline - time.monotonic()
        if remaining <= 0:
            drain_timed_out = True
            break
        thread.join(timeout=remaining)
        if thread.is_alive():
            drain_timed_out = True
            break

    if drain_timed_out:
        state.note_failure(PipeFailure("drain", "shutdown", TimeoutError("drain timeout exceeded")))
        log_diagnostic(
            "drain timeout exceeded",
            operation="drain",
            direction="shutdown",
            error="drain timeout exceeded",
            child_pid=state.child_pid(),
            exit_code=exit_code,
        )

    if state.failure is not None and agent.poll() is None:
        terminate_child(agent, state)

    signal.signal(signal.SIGINT, previous_sigint)
    signal.signal(signal.SIGTERM, previous_sigterm)

    if state.failure is not None:
        return 1
    if exit_code != 0:
        log_diagnostic(
            "child exited nonzero",
            operation="wait",
            direction="agent",
            child_pid=state.child_pid(),
            exit_code=exit_code,
        )
        return exit_code
    return 0


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    real_agent = resolve_real_agent()
    if not real_agent:
        print("cursor_acp_filter: real cursor-agent/agent binary not found", file=sys.stderr)
        return 127
    return run_filter(real_agent, argv)


if __name__ == "__main__":
    raise SystemExit(main())
