from __future__ import annotations

from typing import Any

from ..schemas import EvalSample
from ..utils import simple_tokenize


def evaluate_context_metrics(samples: list[EvalSample]) -> dict[str, Any]:
    """Compute deterministic lexical context-overlap aggregates without network access."""
    return _deterministic_lexical_context_metrics(samples)


def _details() -> dict[str, str]:
    return {
        "backend": "deterministic_lexical",
        "aggregation": "macro_average",
        "metric_version": "token_overlap_v1",
    }


def _deterministic_lexical_context_metrics(samples: list[EvalSample]) -> dict[str, Any]:
    if not samples:
        return {
            "metrics": {"context_precision": 0.0, "context_recall": 0.0},
            "details": _details(),
        }

    precision_scores: list[float] = []
    recall_scores: list[float] = []
    for sample in samples:
        ground_truth_tokens = set(simple_tokenize(sample.ground_truth))
        if not ground_truth_tokens:
            precision_scores.append(0.0)
            recall_scores.append(0.0)
            continue

        context_token_sets = [set(simple_tokenize(text)) for text in sample.retrieved_contexts]
        relevant_count = sum(
            1 for context_tokens in context_token_sets if ground_truth_tokens & context_tokens
        )
        precision_scores.append(relevant_count / max(len(context_token_sets), 1))

        combined_context_tokens = set().union(*context_token_sets) if context_token_sets else set()
        covered_count = len(ground_truth_tokens & combined_context_tokens)
        recall_scores.append(covered_count / len(ground_truth_tokens))

    return {
        "metrics": {
            "context_precision": float(sum(precision_scores) / len(precision_scores)),
            "context_recall": float(sum(recall_scores) / len(recall_scores)),
        },
        "details": _details(),
    }
