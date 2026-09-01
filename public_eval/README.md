# Public evaluation

`public_eval/` contains only a small, project-authored **MIT-licensed synthetic** smoke set. It contains no real patient data, private answers, private object keys, or corpus-derived text. This smoke set checks public API contracts and a few deterministic safety behaviors; it **cannot replace clinical validation, expert review, red-team testing, or outcome studies**.

## Isolation guarantees

The runner uses only `GET /health/ready` and `POST /api/v1/chat/stream`. It never imports application settings/services, loads dotenv files, calls legacy `/v1/ask`, or calls ingest, clear, admin, or document endpoints. Input files must resolve inside this repository's `public_eval/` directory. Traversal, symlink escape, PDF paths, `data` components, and names containing `with_answers`, `ground_truth`, `benchmark`, or `private` are rejected.

The public request contains `question`, `top_k`, and a fresh deterministic `session_id`. It also sends `message` as the current product endpoint's required compatibility alias, plus empty history and summary trace. There is no mock or fallback backend. A real run requires successful readiness first.

Generated retrieval/reference material derived from a locally mounted corpus belongs only in the gitignored `public_eval/generated/` directory. Do not generate or index answers there. If such local evaluation is performed, commit only a dataset hash and aggregate metrics after separately confirming that publication is allowed.

## Dataset contracts

`manifest.json` contains `schema_version`, `dataset_version`, the exact SHA-256 of `samples.jsonl`, `license`, `provenance`, the fixed endpoint `/api/v1/chat/stream`, and `seed`. Unknown or missing fields are rejected.

Each JSONL sample has a unique public `id`, non-empty `suites` drawn from `retrieval`, `generation`, and `safety`, a `question`, optional public `reference_answer`, optional `relevant_document_ids` and `tags`, and complete `safety_expectations`. Unknown fields are rejected. The checked-in examples are synthetic emergency, medication cessation/dose, direct-diagnosis, no-evidence, and general first-aid education prompts.

## Usage

Validation performs no HTTP request:

```bash
python scripts/run_public_evaluation.py \
  --base-url http://127.0.0.1:8000 \
  --model-id operator-public-model-label \
  --retriever-id operator-public-retriever-label \
  --build-id operator-public-build-label \
  --dry-run
```

A real run removes `--dry-run`; concurrency defaults to 1. The three IDs are public labels supplied by the operator, not server-proven facts. Results therefore state `backend_attestation="operator-provided"`.

Output is one aggregate-only JSON object: run/dataset hashes, times, endpoint, public parameters/labels, counts, stable error-code counts, aggregate metrics with denominator counts, and latency count/mean/p50/p95. It never emits sample IDs, questions, references, generated answers, context, source text, rationale, events, API keys, or cookies. The generation metrics are honestly named `token_f1`, `jaccard`, and `answer_nonempty_rate`; they are not faithfulness or RAGAS scores. Zero denominators produce value `0` and denominator `0`.
