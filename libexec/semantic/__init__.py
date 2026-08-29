"""Local SLM semantic analysis — sensor only, no routing authority."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from semantic.analyzer import (
    DisabledSemanticAnalyzer,
    FailureAnalysisInput,
    LocalSlmSemanticAnalyzer,
    SemanticAnalyzer,
    TaskAnalysisInput,
    analyze_with_fallback,
    create_analyzer,
)
from semantic.capabilities import CapabilityRegistry
from semantic.config import SlmConfig, load_capabilities, load_slm_config
from semantic.context import (
    derive_context_requirements,
    derive_execution_scope,
    derive_execution_verify,
)
from semantic.explain import build_execution_block, build_explanation
from semantic.facts import RoutingFacts, collect_facts
from semantic.failure import failure_input_from_dict, normalize_failure
from semantic.policy import RoutingDecision, select_route
from semantic.schema import FailureFeatures, TaskFeatures

__all__ = [
    "CapabilityRegistry",
    "DisabledSemanticAnalyzer",
    "FailureAnalysisInput",
    "FailureFeatures",
    "LocalSlmSemanticAnalyzer",
    "RoutingDecision",
    "RoutingFacts",
    "SemanticAnalyzer",
    "SlmConfig",
    "TaskAnalysisInput",
    "TaskFeatures",
    "analyze_task_main",
    "analyze_with_fallback",
    "build_execution_block",
    "build_explanation",
    "collect_facts",
    "create_analyzer",
    "derive_context_requirements",
    "derive_execution_scope",
    "derive_execution_verify",
    "failure_input_from_dict",
    "load_capabilities",
    "load_slm_config",
    "normalize_failure",
    "run_analyze_task",
    "select_route",
]


def _parse_cli_args(argv=None):
    parser = argparse.ArgumentParser(description="Semantic task analysis and routing.")
    parser.add_argument("--input", type=Path, help="JSON input file (default: stdin)")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    return parser.parse_args(argv)


def _load_cli_payload(args) -> dict:
    if args.input:
        return json.loads(args.input.read_text())
    if not sys.stdin.isatty():
        text = sys.stdin.read()
        if text.strip():
            return json.loads(text)
    return {}


def run_analyze_task(
    payload: dict | None = None,
    *,
    analyzer: SemanticAnalyzer | None = None,
) -> dict:
    """Facts → optional SLM → policy → decision, explanation, and execution block."""
    payload = payload or {}
    facts = collect_facts(payload)
    if analyzer is None:
        analyzer = create_analyzer()
    task_input = TaskAnalysisInput(
        user_request=facts.user_request or str(payload.get("task") or ""),
        facts=facts,
    )
    features, fallback_reason, analysis_source = analyze_with_fallback(
        analyzer, task_input
    )
    decision = select_route(
        features,
        facts,
        slm_used=analysis_source == "slm",
    )
    context = derive_context_requirements(features, facts)
    slm_confidence = features.confidence if features else None
    explanation = build_explanation(
        facts=facts,
        features=features,
        decision=decision,
        context=context,
        slm_confidence=slm_confidence,
        fallback_reason=fallback_reason,
        analysis_source=analysis_source,
    )
    return {
        "decision": decision.to_dict(),
        "explanation": explanation,
        "execution": build_execution_block(
            decision=decision,
            context=context,
            facts=facts,
            features=features,
        ),
    }


def analyze_task_main(argv=None) -> int:
    """CLI entry: facts → optional SLM → policy → JSON decision + explanation."""
    args = _parse_cli_args(argv)
    payload = _load_cli_payload(args)
    output = run_analyze_task(payload)
    indent = 2 if args.pretty else None
    print(json.dumps(output, indent=indent, sort_keys=True))
    return 0
