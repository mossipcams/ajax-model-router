"""Deterministic facts collected before sensor inference."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from typing import Any

# Auth / security / session / PTY / data-loss signals. Deliberately broad:
# over-matching only removes the cheap lane (MINIMAX), which is the safe side.
_HIGH_RISK_TERMS = (
    "auth",
    "authenticat",
    "credential",
    "password",
    "secret",
    "token",
    "security",
    "session",
    "sso",
    "oauth",
    "jwt",
    "privilege",
    "permission",
    "sudo",
    "pty",
    "tty",
    "supervisor",
    "data loss",
    "data-loss",
    "rm -rf",
    "drop table",
    "truncate",
    "wipe",
)
_HIGH_RISK_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(term) for term in _HIGH_RISK_TERMS) + r")\b",
    re.IGNORECASE,
)


def detect_high_risk(*texts: str) -> bool:
    """Deterministic auth/security/session/PTY/data-loss risk scan."""
    return any(_HIGH_RISK_PATTERN.search(text) for text in texts if text)


@dataclass
class RoutingFacts:
    user_request: str = ""
    explicit_model: str = ""
    explicit_agent: str = ""
    user_asked_codex: bool = False
    recorded_spec_uncertainty: bool = False
    changed_files: list[str] = field(default_factory=list)
    changed_file_count: int = 0
    diff_line_count: int = 0
    file_extensions: list[str] = field(default_factory=list)
    is_retry: bool = False
    previous_model_key: str = ""
    previous_failure: str = ""
    test_command: str = ""
    known_subsystem: str = ""
    ci_state: str = ""
    high_risk: bool = False
    unavailable_routes: list[str] = field(default_factory=list)

    def is_high_risk(self) -> bool:
        """Payload flag plus deterministic scan of request and failure text."""
        return (
            self.high_risk
            or detect_high_risk(self.user_request)
            or detect_high_risk(self.previous_failure)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_request": self.user_request,
            "explicit_model": self.explicit_model,
            "explicit_agent": self.explicit_agent,
            "user_asked_codex": self.user_asked_codex,
            "recorded_spec_uncertainty": self.recorded_spec_uncertainty,
            "changed_files": list(self.changed_files),
            "changed_file_count": self.changed_file_count,
            "diff_line_count": self.diff_line_count,
            "file_extensions": list(self.file_extensions),
            "is_retry": self.is_retry,
            "previous_model_key": self.previous_model_key,
            "previous_failure": self.previous_failure,
            "test_command": self.test_command,
            "known_subsystem": self.known_subsystem,
            "ci_state": self.ci_state,
            "high_risk": self.is_high_risk(),
            "unavailable_routes": list(self.unavailable_routes),
        }


def _git(repo: str, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return ""
    except ValueError:
        return ""


def _extensions(paths: list[str]) -> list[str]:
    exts: set[str] = set()
    for path in paths:
        dot = path.rfind(".")
        slash = max(path.rfind("/"), path.rfind("\\"))
        if dot > slash and dot != -1:
            exts.add(path[dot + 1 :].lower())
    return sorted(exts)


def collect_facts(payload: dict[str, Any]) -> RoutingFacts:
    """Build facts from parent-provided payload; run git only when a repo is given."""
    repo = str(payload.get("repo") or "")
    changed_files = [str(p) for p in payload.get("changed_files", [])]
    if not changed_files and repo:
        diff = _git(repo, "diff", "--name-only", "HEAD")
        if diff:
            changed_files = [line for line in diff.splitlines() if line.strip()]

    diff_line_count = int(payload.get("diff_line_count") or 0)
    if not diff_line_count and repo:
        numstat = _git(repo, "diff", "--numstat", "HEAD")
        for line in numstat.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                diff_line_count += int(parts[0]) + int(parts[1])

    return RoutingFacts(
        user_request=str(payload.get("task") or payload.get("user_request") or ""),
        explicit_model=str(payload.get("explicit_model") or ""),
        explicit_agent=str(payload.get("explicit_agent") or ""),
        user_asked_codex=bool(payload.get("user_asked_codex", False)),
        recorded_spec_uncertainty=bool(payload.get("recorded_spec_uncertainty", False)),
        changed_files=changed_files,
        changed_file_count=int(payload.get("changed_file_count") or len(changed_files)),
        diff_line_count=diff_line_count,
        file_extensions=_extensions(changed_files),
        is_retry=bool(payload.get("is_retry", False)),
        previous_model_key=str(payload.get("previous_model_key") or ""),
        previous_failure=str(payload.get("previous_failure") or ""),
        test_command=str(payload.get("test_command") or ""),
        known_subsystem=str(payload.get("known_subsystem") or ""),
        ci_state=str(payload.get("ci_state") or ""),
        high_risk=bool(payload.get("high_risk", False)),
        unavailable_routes=[
            str(route) for route in payload.get("unavailable_routes", [])
        ],
    )
