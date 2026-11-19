#!/usr/bin/env python3
"""Route health: which agent/model routes are known-down right now.

A cache of probe/dispatch results with a short TTL. Routing reads it to skip
dead routes; the execute stage records failures and probes a route only after
it failed without touching the tree. `scripts/check-routes` probes every
registry route on demand.

Local routes (QWEN on llama-server) are the exception: the GPU is often taken
by training, so routing probes them live over HTTP on every decision. That
probe is cheap (a 1-token completion with a few-second timeout) and its result
overrides any cached entry for the route.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TTL_SECONDS = 15 * 60
PROBE_TIMEOUT_SECONDS = 90
PROBE_PROMPT = "Reply with exactly: ok"

# Local OpenAI-compatible servers, by agent/model route. Mirrors the Base URL
# column of the SKILL.md registry. AJAX_ROUTER_QWEN_URL overrides the default.
QWEN_ROUTE = "pi/local/swift-1.5-qwen-3.8-27b"
LOCAL_BASE_URLS = {QWEN_ROUTE: "http://127.0.0.1:18000/v1"}
LOCAL_PROBE_TIMEOUT_SECONDS = 8.0


def local_base_url(route: str) -> str | None:
    if route == QWEN_ROUTE and os.environ.get("AJAX_ROUTER_QWEN_URL"):
        return os.environ["AJAX_ROUTER_QWEN_URL"].rstrip("/")
    return LOCAL_BASE_URLS.get(route)


def probe_local(route: str, timeout: float | None = None) -> tuple[bool, str]:
    """Healthy means the server answers and generates one token within timeout.

    A bare /models check is not enough: with the GPU busy training, llama-server
    can still be listening but crawl or fail on the first real completion.
    """
    base = local_base_url(route)
    if not base:
        return False, f"no local endpoint for {route}"
    if timeout is None:
        timeout = float(os.environ.get("AJAX_ROUTER_LOCAL_PROBE_TIMEOUT") or LOCAL_PROBE_TIMEOUT_SECONDS)
    model = route.partition("/")[2].removeprefix("local/")
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "ok"}],
        "max_tokens": 1,
        "temperature": 0,
    }).encode()
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        # llama-server answers 503 while the model is (re)loading.
        return False, f"HTTP {error.code} from {base}"
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        reason = getattr(error, "reason", error)
        return False, f"unreachable {base}: {reason}"
    except json.JSONDecodeError:
        return False, f"non-JSON reply from {base}"
    if not payload.get("choices"):
        return False, f"no completion from {base}"
    return True, f"ok in {time.monotonic() - started:.1f}s"


def local_server_alive(route: str, timeout: float = 2.0) -> tuple[bool, str]:
    """llama-server /health: answers without a generation slot, so it is safe
    to call while a delegate is mid-generation. 200 = up, 503 = loading."""
    base = local_base_url(route)
    if not base:
        return True, "not a local route"
    root = base[: -len("/v1")] if base.endswith("/v1") else base
    try:
        with urllib.request.urlopen(f"{root}/health", timeout=timeout) as response:
            return response.status == 200, f"HTTP {response.status}"
    except urllib.error.HTTPError as error:
        return False, f"HTTP {error.code} from {root}/health"
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        return False, f"unreachable {root}: {getattr(error, 'reason', error)}"


def refresh_local(now: float | None = None) -> set[str]:
    """Probe every local route live, record results, return the ones that are down."""
    down = set()
    for route in LOCAL_BASE_URLS:
        ok, detail = probe_local(route)
        record(route, ok, detail, now=now)
        if not ok:
            down.add(route)
            sys.stderr.write(f"[ajax-router] {route} down: {detail}\n")
    return down


def cache_path() -> Path:
    override = os.environ.get("AJAX_ROUTER_HEALTH_CACHE")
    return Path(override) if override else Path.home() / ".ajax-router" / "route-health.json"


def load() -> dict:
    try:
        data = json.loads(cache_path().read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def record(route: str, ok: bool, detail: str = "", now: float | None = None) -> None:
    """Store one route result; a write failure never blocks routing."""
    data = load()
    data[route] = {"ok": ok, "checked": now or time.time(), "detail": detail[:300]}
    path = cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        temporary.replace(path)
    except OSError as error:
        sys.stderr.write(f"[ajax-router] route-health write failed: {error}\n")


def unavailable(now: float | None = None, ttl: float = TTL_SECONDS) -> set[str]:
    """agent/model routes whose latest result is a failure younger than ttl."""
    now = now or time.time()
    return {
        route
        for route, entry in load().items()
        if isinstance(entry, dict)
        and not entry.get("ok", True)
        and now - float(entry.get("checked") or 0) < ttl
    }


def probe_command(agent: str, model: str) -> list[str]:
    if agent == "pi":
        return ["pi", "-p", "--model", model, PROBE_PROMPT]
    if agent == "codex":
        return ["codex", "exec", "--skip-git-repo-check", "-m", model, PROBE_PROMPT]
    if agent == "cursor":
        return ["cursor-agent", "-p", "--trust", "--output-format", "text", "--model", model, PROBE_PROMPT]
    if agent == "claude":
        return ["claude", "-p", "--model", model, PROBE_PROMPT]
    raise ValueError(f"no probe for agent {agent!r}")


def probe(route: str, timeout: float = PROBE_TIMEOUT_SECONDS) -> tuple[bool, str]:
    """Run the real CLI with a tiny prompt; healthy means exit 0 and an 'ok' reply.

    Local routes use the direct HTTP probe instead: faster, and it tests the
    server rather than the pi harness.
    """
    if local_base_url(route):
        return probe_local(route)
    agent, _, model = route.partition("/")
    try:
        result = subprocess.run(
            probe_command(agent, model),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=tempfile.gettempdir(),
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return False, f"{agent} CLI not found"
    except subprocess.TimeoutExpired:
        return False, f"probe timed out after {timeout:g}s"
    output = (result.stdout or "") + (result.stderr or "")
    reply = (result.stdout or "").strip().lower()
    if result.returncode == 0 and reply.endswith("ok"):
        return True, "ok"
    tail = " ".join(output.strip().splitlines()[-2:])[:300]
    return False, f"exit {result.returncode}: {tail or 'no reply'}"


def probe_and_record(route: str) -> tuple[bool, str]:
    ok, detail = probe(route)
    record(route, ok, detail)
    return ok, detail


def check_all(routes: list[str]) -> dict[str, tuple[bool, str]]:
    with ThreadPoolExecutor(max_workers=len(routes) or 1) as pool:
        return dict(zip(routes, pool.map(probe_and_record, routes)))


def main(argv=None) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from semantic.policy import REGISTRY

    routes = ["/".join(REGISTRY[key]) for key in REGISTRY]
    results = check_all(routes)
    for key in REGISTRY:
        route = "/".join(REGISTRY[key])
        ok, detail = results[route]
        print(f"{'up  ' if ok else 'DOWN'}  {key:<8} {route:<32} {detail}")
    return 0 if any(ok for ok, _ in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
