"""GLiNER bridge — runs under the router venv's python (gliner2 available).

Reads a JSON payload from stdin, classifies the task with GLiNER2.5-Decide,
and writes a RouteDecision JSON object to stdout. The main router process
stays stdlib-only; this script is the only place gliner2 is imported.

Payload (stdin):
    {"task": str, "eligible_routes": [str, ...], "model": str}

Output (stdout): a single JSON object matching RouteDecision's schema.
Exit code 0 on success, non-zero on any failure (message on stderr).
"""

from __future__ import annotations

import json
import sys

# Route head: single-label classification over the eligible registry keys.
# Sharper, discriminative descriptions + a lower temperature (0.6) give the
# best measured accuracy (7/10 on the golden set) with calibrated confidence.
ROUTE_LABELS = {
    "MINIMAX": "cheap fast model for trivial one-file edits: typos, version bumps, small obvious bug fixes",
    "QWEN": "local model for small bounded changes in one or two files with a clear spec",
    "CURSOR": "strong model for standard features, UI work, and test writing with moderate scope",
    "GLM": "strong model for rework after a failed attempt or when the spec has recorded uncertainty",
    "CODEX": "top-tier model for complex cross-module work, refactors, investigations, or when the user explicitly asked",
    "OPUS": "maximum-strength model for repeated failures, the hardest retries, and architecture-level redesigns",
}
ROUTE_INSTRUCTION = "Pick the execution route best suited to this coding task."
TEMPERATURE = 0.6
CLF_THRESHOLD = 0.5

# Ordinal heads for complexity and ambiguity (1 trivial/none .. 5 very complex/fundamental).
COMPLEXITY_LABELS = ["1", "2", "3", "4", "5"]
COMPLEXITY_INSTRUCTION = "Score task complexity, 1 trivial to 5 very complex."
COMPLEXITY_EXAMPLES = (
    ("Fix a typo in the README.", "1"),
    ("Fix an off-by-one error in one function.", "2"),
    ("Add unit tests for one module.", "3"),
    ("Refactor validation across three handlers.", "4"),
    ("Migrate the entire codebase to async/await.", "5"),
)
AMBIGUITY_LABELS = ["1", "2", "3", "4", "5"]
AMBIGUITY_INSTRUCTION = "Score task ambiguity, 1 none to 5 fundamental."
AMBIGUITY_EXAMPLES = (
    ("Fix a typo in the README.", "1"),
    ("Add a CSV export button to the settings page.", "2"),
    ("The spec is unclear about rate limiting.", "4"),
    ("It is unclear whether the root cause is client, gateway, or upstream.", "5"),
)


def build_schema(eligible_routes: list[str]):
    """Build the classification schema for the given eligible route keys."""
    from gliner2.classification import ClassificationSchema

    # Only include route labels the policy is actually allowed to pick.
    route_labels = {k: ROUTE_LABELS[k] for k in eligible_routes if k in ROUTE_LABELS}
    if not route_labels:
        route_labels = dict(ROUTE_LABELS)

    schema = ClassificationSchema()
    schema = schema.single(
        "route",
        route_labels,
        instruction=ROUTE_INSTRUCTION,
        temperature=TEMPERATURE,
    )
    schema = schema.ordinal(
        "complexity",
        COMPLEXITY_LABELS,
        instruction=COMPLEXITY_INSTRUCTION,
        examples=COMPLEXITY_EXAMPLES,
        temperature=TEMPERATURE,
    )
    schema = schema.ordinal(
        "ambiguity",
        AMBIGUITY_LABELS,
        instruction=AMBIGUITY_INSTRUCTION,
        examples=AMBIGUITY_EXAMPLES,
        temperature=TEMPERATURE,
    )
    return schema


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as error:
        print(f"bridge: invalid payload: {error}", file=sys.stderr)
        return 2

    task = payload.get("task")
    eligible = payload.get("eligible_routes") or []
    model = payload.get("model", "fastino/GLiNER2.5-Decide")
    if not isinstance(task, str) or not task:
        print("bridge: missing or invalid 'task'", file=sys.stderr)
        return 2

    # Fail fast if the model is not already in the local HF cache.
    from gliner2.classification import Classifier

    try:
        clf = Classifier.from_pretrained(model, local_files_only=True)
    except Exception as error:  # noqa: BLE001 — surface a clear, actionable message
        print(
            f"bridge: model '{model}' not in local cache — run scripts/setup-gliner "
            f"({type(error).__name__})",
            file=sys.stderr,
        )
        return 3

    schema = build_schema(eligible)
    result = clf.classify(task, schema)

    route = result.value("route")
    if not isinstance(route, str) or not route:
        print("bridge: no route selected", file=sys.stderr)
        return 4

    probs = result.probabilities("route")
    confidence = float(probs.get(route, 0.0))

    cx = (result["complexity"].level or 0) + 1
    am = (result["ambiguity"].level or 0) + 1

    decision = {
        "route": route,
        "probabilities": {k: float(v) for k, v in probs.items()},
        "complexity": int(cx),
        "ambiguity": int(am),
        "confidence": confidence,
    }
    json.dump(decision, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
