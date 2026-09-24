"""SemanticAnalyzer implementations — Laya is a sensor; enabled by default,
degrades to deterministic routing when unreachable or invalid.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from semantic.client import laya_request
from semantic.config import LayaConfig, load_laya_config
from semantic.errors import (
    SemanticDisabledError,
    SemanticError,
    SemanticLowConfidenceError,
    SemanticValidationError,
)
from semantic.facts import RoutingFacts
from semantic.failure import FailureAnalysisInput
from semantic.policy import ROUTE_DEFINITIONS
from semantic.schema import (
    FailureFeatures,
    RouteDecision,
    failure_features_json_schema,
    parse_failure_features_json,
    parse_route_decision_json,
    route_decision_json_schema,
)

FAILURE_SCHEMA_HINT = (
    "Reply with JSON only matching the failure schema. domain must be one "
    "discrete enum string, never pipe-joined. No explanation."
)


@dataclass
class TaskAnalysisInput:
    user_request: str
    facts: RoutingFacts
    eligible_routes: tuple[str, ...]


class SemanticAnalyzer(Protocol):
    def analyze_task(self, input_data: TaskAnalysisInput) -> RouteDecision: ...

    def analyze_failure(self, input_data: FailureAnalysisInput) -> FailureFeatures: ...


class DisabledSemanticAnalyzer:
    """Raises SemanticDisabledError — policy uses deterministic fallback."""

    def analyze_task(self, input_data: TaskAnalysisInput) -> RouteDecision:
        raise SemanticDisabledError("semantic analysis disabled")

    def analyze_failure(self, input_data: FailureAnalysisInput) -> FailureFeatures:
        raise SemanticDisabledError("semantic analysis disabled")


class LayaAnalyzer:
    """Self-hosted Laya System-1 routing sensor (Jev-compatible /v1/systemone).

    Sends one compact decision payload (task summary + deterministic facts +
    eligible routes) and returns one validated RouteDecision. Never retries,
    never owns policy: any failure raises a typed SemanticError so the caller
    degrades to deterministic routing.
    """

    def __init__(self, config: LayaConfig | None = None):
        self.config = config or load_laya_config()

    def analyze_task(self, input_data: TaskAnalysisInput) -> RouteDecision:
        if not self.config.enabled:
            raise SemanticDisabledError("semantic analysis disabled")
        if not input_data.eligible_routes:
            raise SemanticValidationError("no eligible routes for laya analysis")
        body = laya_request(
            self.config.endpoint,
            self._task_payload(input_data),
            self.config.timeout_ms,
        )
        try:
            decision = parse_route_decision_json(
                _json_dumps(body), input_data.eligible_routes
            )
        except ValueError as error:
            raise SemanticValidationError(str(error)) from error
        if decision.confidence < self.config.confidence_threshold:
            raise SemanticLowConfidenceError(
                f"route confidence {decision.confidence:.2f} below threshold "
                f"{self.config.confidence_threshold:.2f}"
            )
        return decision

    def analyze_failure(self, input_data: FailureAnalysisInput) -> FailureFeatures:
        if not self.config.enabled:
            raise SemanticDisabledError("semantic analysis disabled")
        body = laya_request(
            self.config.endpoint,
            {
                "kind": "failure",
                "schema_hint": FAILURE_SCHEMA_HINT,
                "response_format": failure_features_json_schema(),
                "log_excerpt": input_data.log_excerpt[:2000],
                "facts": input_data.facts.to_dict()
                if input_data.facts is not None
                else {},
            },
            self.config.timeout_ms,
        )
        features = self._parse_failure(_json_dumps(body))
        if features.confidence < self.config.confidence_threshold:
            raise SemanticLowConfidenceError(
                f"confidence {features.confidence} below threshold"
            )
        return features

    def _task_payload(self, input_data: TaskAnalysisInput) -> dict[str, object]:
        """Compact decision-relevant payload — no source files or repo dumps."""
        facts = input_data.facts
        return {
            "kind": "route",
            "task": input_data.user_request[:1000],
            "facts": {
                "changed_file_count": facts.changed_file_count,
                "diff_line_count": facts.diff_line_count,
                "file_extensions": facts.file_extensions[:12],
                "known_subsystem": facts.known_subsystem,
                "is_retry": facts.is_retry,
                "previous_model_key": facts.previous_model_key,
                "previous_failure": facts.previous_failure[:200],
                "ci_state": facts.ci_state,
            },
            "eligible_routes": list(input_data.eligible_routes),
            "route_definitions": {
                key: ROUTE_DEFINITIONS[key]
                for key in input_data.eligible_routes
                if key in ROUTE_DEFINITIONS
            },
            "response_schema": route_decision_json_schema(
                input_data.eligible_routes
            ),
        }

    def _parse_failure(self, content: str) -> FailureFeatures:
        try:
            return parse_failure_features_json(content)
        except ValueError as error:
            raise SemanticValidationError(str(error)) from error


def create_analyzer(config: LayaConfig | None = None) -> SemanticAnalyzer:
    cfg = config or load_laya_config()
    if not cfg.enabled:
        return DisabledSemanticAnalyzer()
    return LayaAnalyzer(cfg)


def analyze_with_fallback(
    analyzer: SemanticAnalyzer,
    input_data: TaskAnalysisInput,
) -> tuple[RouteDecision | None, str | None, str]:
    """Return (decision, fallback_reason, analysis_source). Never raises."""
    try:
        decision = analyzer.analyze_task(input_data)
        return decision, None, "laya"
    except SemanticDisabledError:
        return None, "semantic analysis disabled", "disabled"
    except SemanticLowConfidenceError as error:
        return None, str(error), "laya_rejected"
    except SemanticError as error:
        return None, str(error), "laya_failed"


def _json_dumps(data: object) -> str:
    import json

    return json.dumps(data)
