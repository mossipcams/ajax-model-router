#!/usr/bin/env python3
"""Route health: which agent/model routes are known-down right now.

A cache of probe/dispatch results with a short TTL. Routing reads it (no
probing) to skip dead routes; the execute stage records failures and probes a
route only after it failed without touching the tree. `scripts/check-routes`
probes every registry route on demand.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TTL_SECONDS = 15 * 60
PROBE_TIMEOUT_SECONDS = 90
PROBE_PROMPT = "Reply with exactly: ok"


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
    """Run the real CLI with a tiny prompt; healthy means exit 0 and an 'ok' reply."""
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
