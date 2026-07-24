#!/usr/bin/env python3
"""Drive one `codex app-server` process over newline-delimited JSON-RPC.

One process per delegation, alive for the delegation's lifetime so Codex keeps
its thread/context across follow-up turns. This is a thin adapter, not a JSON-RPC
framework: it speaks only the handful of methods the router needs and maps the
native notifications it cares about into a small set of normalized events.

Verified against codex-cli 0.144.6:
  - transport is one JSON object per line on stdout; stderr is separate.
  - auth resolves from ~/.codex (codexHome) -> ChatGPT subscription preserved.
  - `sandbox` is the STRING "read-only" | "workspace-write" | "danger-full-access"
    (the generated v2 schema's {type:"readOnly"} object is rejected at runtime).
  - `approvalPolicy:"never"` means no server->client approval round-trips, so a
    non-interactive turn never blocks waiting for us to approve a command.
"""
import json
import os
import queue
import signal
import threading
import time
from dataclasses import dataclass, field


DEFAULT_CMD = ["codex", "app-server"]
NORMALIZED_KINDS = (
    "started",
    "activity_started",
    "activity_finished",
    "message",
    "completed",
    "failed",
)


class CodexError(Exception):
    """Protocol / lifecycle failure. Carries a short reason for the report."""

    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


class CodexTimeout(CodexError):
    def __init__(self, message):
        super().__init__("TIMEOUT", message)


@dataclass
class TurnResult:
    status: str  # "completed" | "failed"
    final_message: str
    events: list = field(default_factory=list)
    error: str = ""


def normalize(method, params):
    """Map a native app-server notification to a normalized event, or None.

    Unknown methods return None (ignored). Only fields Ajax consumes are read;
    extra fields are tolerated by construction.
    """
    if method == "turn/started":
        return ("started", {"turnId": params.get("turnId")})
    if method == "item/started":
        item = params.get("item") or {}
        return ("activity_started", {"itemType": _item_type(item), "id": item.get("id")})
    if method == "item/completed":
        item = params.get("item") or {}
        return ("activity_finished", {"itemType": _item_type(item), "id": item.get("id")})
    if method in ("item/agentMessage/delta", "item/plan/delta"):
        return ("message", {"delta": params.get("delta") or params.get("text") or ""})
    if method == "turn/completed":
        turn = params.get("turn") or {}
        return ("completed", {"status": turn.get("status")})
    if method == "error":
        return ("failed", {"error": _stringify(params)})
    return None


def _stringify(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("message", "error", "detail"):
            if isinstance(value.get(key), str):
                return value[key]
    return json.dumps(value, sort_keys=True)


def _item_type(item):
    # Runtime uses `type`; tolerate `item_type` in case of schema/runtime skew.
    return item.get("type") or item.get("item_type")


def _final_message_from_turn(turn):
    """Last agentMessage item's text = the worker's final response."""
    text = ""
    for item in turn.get("items") or []:
        if _item_type(item) == "agentMessage":
            text = item.get("text") or text
    return text


class CodexAppServerSession:
    """A single app-server process: initialize, thread, turns, teardown."""

    def __init__(
        self,
        cwd,
        model,
        raw_log,
        sandbox="workspace-write",
        reasoning_effort="xhigh",
        approval_policy="never",
        cmd=None,
        term_grace_seconds=5.0,
    ):
        self.cwd = str(cwd)
        self.model = model
        self.sandbox = sandbox
        self.reasoning_effort = reasoning_effort
        self.approval_policy = approval_policy
        self.term_grace_seconds = term_grace_seconds
        self._cmd = cmd or _cmd_from_env()
        self._raw = raw_log
        self._proc = None
        self._q = queue.Queue()
        self._reader = None
        self._stderr_chunks = []
        self._stderr_thread = None
        self._next_id = 0
        self._thread_id = None
        self._active_turn_id = None

    # -- lifecycle ---------------------------------------------------------
    def start(self, timeout, resume_thread_id=None):
        import subprocess

        self._proc = subprocess.Popen(
            self._cmd,
            cwd=self.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stderr_thread.start()

        deadline = time.monotonic() + timeout
        self._request("initialize", {
            "clientInfo": {"name": "ajax-model-router", "title": "Ajax Model Router", "version": "1"},
        }, deadline)

        if resume_thread_id:
            result = self._request("thread/resume", {"threadId": resume_thread_id}, deadline)
            self._thread_id = _thread_id_from(result) or resume_thread_id
        else:
            result = self._request("thread/start", {
                "cwd": self.cwd,
                "model": self.model,
                "sandbox": self.sandbox,
                "approvalPolicy": self.approval_policy,
            }, deadline)
            self._thread_id = _thread_id_from(result)
        if not self._thread_id:
            raise CodexError("THREAD_START_FAILED", "app-server returned no thread id")
        return self._thread_id

    def run_turn(self, prompt, timeout):
        deadline = time.monotonic() + timeout
        result = self._request("turn/start", {
            "threadId": self._thread_id,
            "input": [{"type": "text", "text": prompt}],
            "model": self.model,
            "effort": self.reasoning_effort,
            "sandbox": self.sandbox,
            "approvalPolicy": self.approval_policy,
        }, deadline)
        self._active_turn_id = _turn_id_from(result)
        return self._consume_turn(deadline)

    def interrupt(self):
        if self._proc is None or self._proc.poll() is not None:
            return
        if self._thread_id and self._active_turn_id:
            try:
                self._send({"jsonrpc": "2.0", "id": self._new_id(), "method": "turn/interrupt",
                            "params": {"threadId": self._thread_id, "turnId": self._active_turn_id}})
            except OSError:
                pass
        # Give the native interrupt a short bounded window before we tear down.
        end = time.monotonic() + min(2.0, self.term_grace_seconds)
        while time.monotonic() < end and self._proc.poll() is None:
            time.sleep(0.05)
        self.close()

    def close(self):
        proc = self._proc
        if proc is None:
            return
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
        except OSError:
            pass
        if proc.poll() is None:
            _terminate_group(proc, self.term_grace_seconds)
        self._drain_stderr_to_log()

    # -- internals ---------------------------------------------------------
    def _consume_turn(self, deadline):
        events = []
        final_message = ""
        while True:
            item = self._next_message(deadline)
            if item is _EOF:
                # Process ended without a terminal turn event. Never hang.
                raise CodexError("UNEXPECTED_EXIT", "app-server exited before turn completion")
            method = item.get("method")
            params = item.get("params") or {}
            if method is None:
                # A stray response with no pending waiter; ignore.
                continue
            if "id" in item:
                # Server->client request. We run non-interactively; reject so the
                # turn can never block waiting on us.
                self._reject_server_request(item["id"])
                continue
            event = normalize(method, params)
            if event is not None:
                events.append(event)
            if method == "turn/completed":
                turn = params.get("turn") or {}
                status = turn.get("status") or "completed"
                final_message = _final_message_from_turn(turn) or final_message
                if status == "failed" or turn.get("error"):
                    return TurnResult("failed", final_message, events, _stringify(turn.get("error") or status))
                return TurnResult("completed", final_message, events)
            if method == "error":
                return TurnResult("failed", final_message, events, _stringify(params))

    def _request(self, method, params, deadline):
        request_id = self._new_id()
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        while True:
            item = self._next_message(deadline)
            if item is _EOF:
                raise CodexError("UNEXPECTED_EXIT", f"app-server exited during {method}")
            if item.get("id") == request_id and "method" not in item:
                if "error" in item:
                    raise CodexError("JSONRPC_ERROR", f"{method}: {_stringify(item['error'])}")
                return item.get("result") or {}
            if "id" in item and "method" in item:
                self._reject_server_request(item["id"])
            # Notifications that arrive before the response (e.g. thread/started)
            # are streamed to the log by the reader already; nothing to do here.

    def _reject_server_request(self, request_id):
        try:
            self._send({"jsonrpc": "2.0", "id": request_id,
                        "error": {"code": -32601, "message": "non-interactive delegate: request declined"}})
        except OSError:
            pass

    def _next_message(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CodexTimeout("codex app-server timed out")
        try:
            item = self._q.get(timeout=remaining)
        except queue.Empty:
            raise CodexTimeout("codex app-server timed out")
        return item

    def _send(self, obj):
        line = json.dumps(obj)
        self._proc.stdin.write(line + "\n")
        self._proc.stdin.flush()

    def _new_id(self):
        self._next_id += 1
        return self._next_id

    def _read_stdout(self):
        for line in self._proc.stdout:
            self._raw.write(line if line.endswith("\n") else line + "\n")
            self._raw.flush()
            stripped = line.strip()
            if not stripped:
                continue
            try:
                self._q.put(json.loads(stripped))
            except json.JSONDecodeError:
                # Malformed protocol line: keep it in the raw log, skip parsing.
                continue
        self._q.put(_EOF)

    def _read_stderr(self):
        for line in self._proc.stderr:
            self._stderr_chunks.append(line)

    def _drain_stderr_to_log(self):
        if self._stderr_thread:
            self._stderr_thread.join(timeout=1.0)
        if self._stderr_chunks:
            self._raw.write("=== STDERR ===\n")
            self._raw.writelines(self._stderr_chunks)
            self._raw.flush()
            self._stderr_chunks = []


_EOF = object()


def _cmd_from_env():
    raw = os.environ.get("CODEX_APP_SERVER_CMD")
    if not raw:
        return list(DEFAULT_CMD)
    return json.loads(raw)


def _thread_id_from(result):
    thread = result.get("thread") if isinstance(result, dict) else None
    if isinstance(thread, dict):
        return thread.get("id")
    return None


def _turn_id_from(result):
    turn = result.get("turn") if isinstance(result, dict) else None
    if isinstance(turn, dict):
        return turn.get("id")
    return None


def _terminate_group(proc, grace):
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def run_delegation(prompt, cwd, model, raw_log, *, sandbox="workspace-write",
                   reasoning_effort="xhigh", timeout=900.0, term_grace_seconds=5.0,
                   resume_thread_id=None, cmd=None):
    """Full one-turn delegation. Returns TurnResult; final_message carries the
    worker's DELEGATE_REPORT envelope. Guarantees no orphaned app-server."""
    session = CodexAppServerSession(
        cwd=cwd, model=model, raw_log=raw_log, sandbox=sandbox,
        reasoning_effort=reasoning_effort, cmd=cmd, term_grace_seconds=term_grace_seconds,
    )
    try:
        session.start(timeout, resume_thread_id=resume_thread_id)
        result = session.run_turn(prompt, timeout)
        result.events.append(("thread_id", {"threadId": session._thread_id}))
        return result
    except CodexTimeout:
        session.interrupt()
        raise
    finally:
        session.close()
