"""Laya semantic routing — sensor only, no routing authority.

Pipeline: facts → hard constraints (eligibility) → optional Laya decision over
eligible routes → deterministic policy → decision, explanation, execution.
Laya failure never blocks routing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from semantic.analyzer import (
    DisabledSemanticAnalyzer,
    LayaAnalyzer,
    SemanticAnalyzer,
    TaskAnalysisInput,
    analyze_with_fallback,
    create_analyzer,
)
from semantic.capabilities import CapabilityRegistry
from semantic.config import LayaConfig, load_capabilities, load_laya_config
from semantic.context import (
    derive_context_requirements,
    derive_execution_scope,
    derive_execution_verify,
)
from semantic.explain import build_execution_block, build_explanation
from semantic.facts import RoutingFacts, collect_facts
from semantic.failure import (
    FailureAnalysisInput,
    failure_input_from_dict,
    normalize_failure,
)
from semantic.policy import (
    RoutingDecision,
    eligible_routes,
    has_hard_override,
    select_route,
)
from semantic.schema import FailureFeatures, RouteDecision

__all__ = [
    "CapabilityRegistry",
    "DisabledSemanticAnalyzer",
    "FailureAnalysisInput",
    "FailureFeatures",
    "LayaAnalyzer",
    "LayaConfig",
    "RoutingDecision",
    "RoutingFacts",
    "RouteDecision",
    "SemanticAnalyzer",
    "TaskAnalysisInput",
    "analyze_task_main",
    "analyze_with_fallback",
    "build_execution_block",
    "build_explanation",
    "collect_facts",
    "create_analyzer",
    "derive_context_requirements",
    "derive_execution_scope",
    "derive_execution_verify",
    "eligible_routes",
    "failure_input_from_dict",
    "has_hard_override",
    "load_capabilities",
    "load_laya_config",
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
    config: LayaConfig | None = None,
) -> dict:
    """Facts → eligibility → optional Laya → policy → decision + explanation.

    Laya is only consulted when no hard override applies and at least two
    routes remain eligible; otherwise deterministic routing runs directly.
    """
    payload = payload or {}
    facts = collect_facts(payload)
    cfg = config or load_laya_config()
    if analyzer is None:
        analyzer = create_analyzer(cfg)
    eligible = eligible_routes(facts)

    laya: RouteDecision | None = None
    fallback_reason: str | None = None
    analysis_source = "deterministic"
    if has_hard_override(facts):
        analysis_source = "skipped_hard_override"
    elif len(eligible) <= 1:
        analysis_source = "skipped_single_eligible"
    else:
        task_input = TaskAnalysisInput(
            user_request=facts.user_request or str(payload.get("task") or ""),
            facts=facts,
            eligible_routes=eligible,
        )
        laya, fallback_reason, analysis_source = analyze_with_fallback(
            analyzer, task_input
        )

    decision = select_route(
        facts,
        laya=laya,
        laya_fallback_reason=fallback_reason,
        confidence_threshold=cfg.confidence_threshold,
    )
    context = derive_context_requirements(laya, facts)
    explanation = build_explanation(
        facts=facts,
        decision=decision,
        context=context,
        laya=laya,
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
        ),
    }


def analyze_task_main(argv=None) -> int:
    """CLI entry: facts → eligibility → optional Laya → policy → JSON output."""
    args = _parse_cli_args(argv)
    payload = _load_cli_payload(args)
    output = run_analyze_task(payload)
    indent = 2 if args.pretty else None
    print(json.dumps(output, indent=indent, sort_keys=True))
    return 0
