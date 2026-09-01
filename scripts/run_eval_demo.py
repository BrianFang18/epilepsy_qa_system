from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.schemas import (  # noqa: E402
    AskRequest,
    EvalSample,
)
from app.schemas import (  # noqa: E402
    RagasEvalRequest as LegacyEvalRequest,
)
from app.service import get_service  # noqa: E402

EXPECTED_EVALUATION_DETAILS = {
    "backend": "deterministic_lexical",
    "metric_version": "token_overlap_v1",
    "aggregation": "macro_average",
}


def _validated_lexical_output(evaluation_payload: dict[str, object]) -> dict[str, object]:
    details = evaluation_payload.get("details")
    if not isinstance(details, dict):
        raise RuntimeError("Evaluation response is missing details metadata")

    mismatches = {
        key: {"expected": expected, "actual": details.get(key)}
        for key, expected in EXPECTED_EVALUATION_DETAILS.items()
        if details.get(key) != expected
    }
    if mismatches:
        raise RuntimeError(f"Unexpected evaluation backend metadata: {mismatches}")

    metrics = evaluation_payload.get("metrics")
    if not isinstance(metrics, dict):
        raise RuntimeError("Evaluation response is missing metrics")

    metric_values: dict[str, float] = {}
    for metric_name in ("context_precision", "context_recall"):
        value = metrics.get(metric_name)
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise RuntimeError(f"Invalid {metric_name} value: {value!r}")
        metric_values[metric_name] = float(value)

    context_overlap_mean = 0.5 * (
        metric_values["context_precision"] + metric_values["context_recall"]
    )
    return {
        **metric_values,
        "context_overlap_mean": context_overlap_mean,
        "details": {key: details[key] for key in EXPECTED_EVALUATION_DETAILS},
    }


def main() -> None:
    svc = get_service()
    svc.seed_demo_data()
    ask_resp = svc.ask(
        AskRequest(
            question="Should medication be adjusted when nocturnal seizures increase?",
            with_trace=False,
        )
    )

    samples = [
        EvalSample(
            question="Should medication be adjusted when nocturnal seizures increase?",
            ground_truth=(
                "Medication adjustment should be based on seizure trend, adherence, and specialist evaluation. "
                "Emergency care is required for prolonged convulsions."
            ),
            retrieved_contexts=[s.text for s in ask_resp.sources],
            response=ask_resp.answer,
        )
    ]

    # RagasEvalRequest and evaluate_ragas are legacy compatibility names only;
    # the current backend is deterministic lexical token overlap.
    legacy_request = LegacyEvalRequest(samples=samples)
    evaluation_response = svc.evaluate_ragas(legacy_request)
    output = _validated_lexical_output(evaluation_response.model_dump())
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
