"""Failure log normalization into typed FailureFeatures."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from semantic.schema import FailureClass, FailureFeatures, TaskDomain


@dataclass
class FailureAnalysisInput:
    log_excerpt: str = ""
    exit_code: int | None = None
    agent: str = ""
    model: str = ""
    test_summary: str = ""
    acp_error: str = ""
    git_conflict: bool = False
    review_rejection: bool = False


def normalize_failure(input_data: FailureAnalysisInput) -> FailureFeatures:
    """Deterministic failure classification when SLM is unavailable."""
    text = " ".join(
        part
        for part in (
            input_data.log_excerpt,
            input_data.test_summary,
            input_data.acp_error,
        )
        if part
    ).lower()

    failure_class = FailureClass.UNKNOWN
    domain = TaskDomain.UNKNOWN
    component = ""
    likely_task_related = True
    retry_same_model = False

    if input_data.git_conflict or "merge conflict" in text or "git conflict" in text:
        failure_class = FailureClass.GIT_CONFLICT
        domain = TaskDomain.GIT
        component = "git"
        retry_same_model = False
    elif input_data.review_rejection:
        failure_class = FailureClass.REVIEW_REJECTION
        retry_same_model = False
    elif input_data.acp_error or "acp" in text or "retriableerror" in text:
        failure_class = FailureClass.ACP_ERROR
        domain = TaskDomain.TOOLING
        component = "acpx"
        retry_same_model = True
    elif input_data.exit_code == 124 or "timeout" in text or "timed out" in text:
        failure_class = FailureClass.TIMEOUT
        retry_same_model = False
    elif "compile error" in text or "error[E" in text or "cannot find" in text:
        failure_class = FailureClass.COMPILE_ERROR
        domain = TaskDomain.RUST_BACKEND if "error[e" in text else TaskDomain.UNKNOWN
        retry_same_model = True
    elif "test" in text and ("fail" in text or "error" in text):
        failure_class = FailureClass.TEST_REGRESSION
        domain = TaskDomain.TESTING
        retry_same_model = True
    elif "ci" in text or "github actions" in text or "workflow" in text:
        failure_class = FailureClass.CI_FAILURE
        domain = TaskDomain.CI
        retry_same_model = False

    match = re.search(r"([\w./-]+\.(rs|py|dart|tsx?|jsx?))", text)
    if match:
        component = match.group(1)

    return FailureFeatures(
        failure_class=failure_class,
        domain=domain,
        component=component,
        likely_task_related=likely_task_related,
        retry_same_model=retry_same_model,
        confidence=0.5,
    )


def failure_input_from_dict(data: dict[str, Any]) -> FailureAnalysisInput:
    return FailureAnalysisInput(
        log_excerpt=str(data.get("log_excerpt") or data.get("log") or ""),
        exit_code=data.get("exit_code"),
        agent=str(data.get("agent") or ""),
        model=str(data.get("model") or ""),
        test_summary=str(data.get("test_summary") or ""),
        acp_error=str(data.get("acp_error") or ""),
        git_conflict=bool(data.get("git_conflict", False)),
        review_rejection=bool(data.get("review_rejection", False)),
    )
