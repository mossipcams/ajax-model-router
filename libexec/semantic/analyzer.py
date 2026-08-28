"""SemanticAnalyzer implementations — SLM is a sensor; enabled by default, degrades when unreachable."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

from semantic.client import chat_completion
from semantic.config import SlmConfig, load_slm_config
from semantic.errors import (
    SemanticDisabledError,
    SemanticError,
    SemanticLowConfidenceError,
    SemanticValidationError,
)
from semantic.facts import RoutingFacts
from semantic.schema import (
    ChangeScope,
    Complexity,
    ContextSize,
    FailureClass,
    FailureFeatures,
    ReasoningDepth,
    TaskDomain,
    TaskFeatures,
    TaskRisk,
    TaskType,
    Uncertainty,
    failure_features_response_format,
    parse_failure_features_json,
    parse_task_features_json,
    task_features_response_format,
)

TASK_SCHEMA_HINT = json.dumps(
    {
        "example": {
            "task_type": "bug_fix",
            "domains": ["rust_backend"],
            "complexity": "medium",
            "scope": "localized",
            "reasoning_depth": "medium",
            "uncertainty": "low",
            "requires_repo_discovery": False,
            "requires_visual_validation": False,
            "requires_large_context": False,
            "likely_context_size": "small",
            "risk": "medium",
            "confidence": 0.85,
        },
        "allowed_values": {
            "task_type": [member.value for member in TaskType],
            "domains": [member.value for member in TaskDomain],
            "complexity": [member.value for member in Complexity],
            "scope": [member.value for member in ChangeScope],
            "reasoning_depth": [member.value for member in ReasoningDepth],
            "uncertainty": [member.value for member in Uncertainty],
            "likely_context_size": [member.value for member in ContextSize],
            "risk": [member.value for member in TaskRisk],
        },
        "notes": {
            "domains": (
                "JSON array of one or more discrete values from allowed_values.domains; "
                "never pipe-join or copy the full enum list"
            )
        },
    },
    indent=2,
)

FAILURE_SCHEMA_HINT = json.dumps(
    {
        "example": {
            "failure_class": "test_regression",
            "domain": "testing",
            "component": "tests/test_foo.py",
            "likely_task_related": True,
            "retry_same_model": True,
            "confidence": 0.7,
        },
        "allowed_values": {
            "failure_class": [member.value for member in FailureClass],
            "domain": [member.value for member in TaskDomain],
        },
        "notes": {
            "domain": (
                "One discrete value from allowed_values.domain; "
                "never pipe-join or copy the full enum list"
            )
        },
    },
    indent=2,
)


@dataclass
class TaskAnalysisInput:
    user_request: str
    facts: RoutingFacts


@dataclass
class FailureAnalysisInput:
    log_excerpt: str
    facts: RoutingFacts


class SemanticAnalyzer(Protocol):
    def analyze_task(self, input_data: TaskAnalysisInput) -> TaskFeatures: ...

    def analyze_failure(self, input_data: FailureAnalysisInput) -> FailureFeatures: ...


class DisabledSemanticAnalyzer:
    """Raises SemanticDisabledError — policy uses deterministic fallback."""

    def analyze_task(self, input_data: TaskAnalysisInput) -> TaskFeatures:
        raise SemanticDisabledError("semantic analysis disabled")

    def analyze_failure(self, input_data: FailureAnalysisInput) -> FailureFeatures:
        raise SemanticDisabledError("semantic analysis disabled")


def _extract_json_block(text: str) -> str:
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        return match.group(0)
    raise SemanticValidationError("no JSON object in SLM response")


class LocalSlmSemanticAnalyzer:
    def __init__(self, config: SlmConfig | None = None):
        self.config = config or load_slm_config()

    def analyze_task(self, input_data: TaskAnalysisInput) -> TaskFeatures:
        if not self.config.enabled:
            raise SemanticDisabledError("semantic analysis disabled")
        user = self._task_prompt(input_data)
        content = self._request(
            self.config.task_system, user, task_features_response_format()
        )
        features = self._parse_task(content)
        if features.confidence < self.config.confidence_threshold:
            raise SemanticLowConfidenceError(
                f"confidence {features.confidence} below threshold"
            )
        return features

    def analyze_failure(self, input_data: FailureAnalysisInput) -> FailureFeatures:
        if not self.config.enabled:
            raise SemanticDisabledError("semantic analysis disabled")
        user = self._failure_prompt(input_data)
        content = self._request(
            self.config.failure_system, user, failure_features_response_format()
        )
        features = self._parse_failure(content)
        if features.confidence < self.config.confidence_threshold:
            raise SemanticLowConfidenceError(
                f"confidence {features.confidence} below threshold"
            )
        return features

    def _request(
        self,
        system: str,
        user: str,
        response_format: dict[str, object],
    ) -> str:
        last_error: Exception | None = None
        attempts = max(self.config.max_retries, 0) + 1
        for _ in range(attempts):
            try:
                return chat_completion(
                    endpoint=self.config.endpoint,
                    model=self.config.model,
                    system=system,
                    user=user,
                    max_tokens=self.config.max_tokens,
                    timeout_ms=self.config.timeout_ms,
                    response_format=response_format,
                )
            except SemanticError as error:
                last_error = error
        assert last_error is not None
        raise last_error

    def _parse_task(self, content: str) -> TaskFeatures:
        try:
            return parse_task_features_json(_extract_json_block(content))
        except ValueError as error:
            raise SemanticValidationError(str(error)) from error

    def _parse_failure(self, content: str) -> FailureFeatures:
        try:
            return parse_failure_features_json(_extract_json_block(content))
        except ValueError as error:
            raise SemanticValidationError(str(error)) from error

    def _task_prompt(self, input_data: TaskAnalysisInput) -> str:
        facts_json = json.dumps(input_data.facts.to_dict(), sort_keys=True)
        return (
            f"Classify this coding task. Use only the schema.\n"
            f"Schema: {TASK_SCHEMA_HINT}\n"
            f"Known facts (do not contradict): {facts_json}\n"
            f"Task: {input_data.user_request[:2000]}"
        )

    def _failure_prompt(self, input_data: FailureAnalysisInput) -> str:
        facts_json = json.dumps(input_data.facts.to_dict(), sort_keys=True)
        return (
            f"Classify this failure. Use only the schema.\n"
            f"Schema: {FAILURE_SCHEMA_HINT}\n"
            f"Known facts: {facts_json}\n"
            f"Log excerpt: {input_data.log_excerpt[:2000]}"
        )


def create_analyzer(config: SlmConfig | None = None) -> SemanticAnalyzer:
    cfg = config or load_slm_config()
    if not cfg.enabled:
        return DisabledSemanticAnalyzer()
    return LocalSlmSemanticAnalyzer(cfg)


def analyze_with_fallback(
    analyzer: SemanticAnalyzer,
    input_data: TaskAnalysisInput,
) -> tuple[TaskFeatures | None, str | None, str]:
    """Return (features, fallback_reason, analysis_source). Never raises."""
    try:
        features = analyzer.analyze_task(input_data)
        return features, None, "slm"
    except SemanticDisabledError:
        return None, "semantic analysis disabled", "disabled"
    except SemanticLowConfidenceError as error:
        return None, str(error), "slm_rejected"
    except SemanticError as error:
        return None, str(error), "slm_failed"
