"""Deterministic facts collected before SLM inference."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RoutingFacts:
    """Objective facts the router already knows — not inferred by the SLM."""

    user_request: str = ""
    explicit_model: str = ""
    explicit_agent: str = ""
    user_asked_codex: bool = False
    recorded_spec_uncertainty: bool = False
    repository: str = ""
    working_directory: str = ""
    branch: str = ""
    changed_files: list[str] = field(default_factory=list)
    file_extensions: list[str] = field(default_factory=list)
    diff_line_count: int = 0
    changed_file_count: int = 0
    known_subsystem: str = ""
    test_command: str = ""
    ci_state: str = ""
    task_source: str = ""
    is_retry: bool = False
    retry_count: int = 0
    previous_model: str = ""
    previous_model_key: str = ""
    previous_failure: str = ""
    previous_agent: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_request": self.user_request,
            "explicit_model": self.explicit_model,
            "explicit_agent": self.explicit_agent,
            "user_asked_codex": self.user_asked_codex,
            "recorded_spec_uncertainty": self.recorded_spec_uncertainty,
            "repository": self.repository,
            "working_directory": self.working_directory,
            "branch": self.branch,
            "changed_files": list(self.changed_files),
            "file_extensions": list(self.file_extensions),
            "diff_line_count": self.diff_line_count,
            "changed_file_count": self.changed_file_count,
            "known_subsystem": self.known_subsystem,
            "test_command": self.test_command,
            "ci_state": self.ci_state,
            "task_source": self.task_source,
            "is_retry": self.is_retry,
            "retry_count": self.retry_count,
            "previous_model": self.previous_model,
            "previous_model_key": self.previous_model_key,
            "previous_failure": self.previous_failure,
            "previous_agent": self.previous_agent,
        }


def _git_branch(cwd: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return ""


def _git_diff_stats(cwd: Path) -> tuple[int, int]:
    try:
        result = subprocess.run(
            ["git", "diff", "--numstat", "HEAD"],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=True,
        )
        lines = 0
        files = 0
        for row in result.stdout.splitlines():
            parts = row.split("\t")
            if len(parts) >= 3:
                files += 1
                try:
                    lines += int(parts[0]) + int(parts[1])
                except ValueError:
                    pass
        return lines, files
    except (subprocess.CalledProcessError, OSError):
        return 0, 0


def _extensions(paths: list[str]) -> list[str]:
    exts: set[str] = set()
    for path in paths:
        suffix = Path(path).suffix.lower()
        if suffix:
            exts.add(suffix.lstrip("."))
    return sorted(exts)


def collect_facts(payload: dict[str, Any] | None = None) -> RoutingFacts:
    """Build facts from an optional analyze-task payload and best-effort git."""
    payload = payload or {}
    facts = RoutingFacts()

    facts.user_request = str(payload.get("user_request") or payload.get("task") or "")
    facts.explicit_model = str(payload.get("explicit_model") or payload.get("model") or "")
    facts.explicit_agent = str(payload.get("explicit_agent") or payload.get("agent") or "")
    facts.user_asked_codex = bool(payload.get("user_asked_codex", False))
    facts.recorded_spec_uncertainty = bool(
        payload.get("recorded_spec_uncertainty", False)
    )
    facts.known_subsystem = str(payload.get("known_subsystem") or "")
    facts.test_command = str(payload.get("test_command") or "")
    facts.ci_state = str(payload.get("ci_state") or "")
    facts.task_source = str(payload.get("task_source") or "router")
    facts.is_retry = bool(payload.get("is_retry", False))
    facts.retry_count = int(payload.get("retry_count") or 0)
    facts.previous_model = str(payload.get("previous_model") or "")
    facts.previous_model_key = str(payload.get("previous_model_key") or "")
    facts.previous_failure = str(payload.get("previous_failure") or "")
    facts.previous_agent = str(payload.get("previous_agent") or "")

    cwd_text = str(payload.get("working_directory") or payload.get("cwd") or ".")
    cwd = Path(cwd_text).resolve()
    facts.working_directory = str(cwd)
    facts.repository = str(payload.get("repository") or facts.working_directory)

    changed = payload.get("changed_files") or payload.get("allowed_files") or []
    if isinstance(changed, list):
        facts.changed_files = [str(item) for item in changed]
    facts.changed_file_count = len(facts.changed_files)
    facts.file_extensions = _extensions(facts.changed_files)

    if payload.get("diff_line_count") is not None:
        facts.diff_line_count = int(payload["diff_line_count"])
    else:
        diff_lines, diff_files = _git_diff_stats(cwd)
        if not facts.changed_file_count and diff_files:
            facts.changed_file_count = diff_files
        if not facts.diff_line_count:
            facts.diff_line_count = diff_lines

    facts.branch = str(payload.get("branch") or _git_branch(cwd))
    return facts
