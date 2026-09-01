#!/usr/bin/env python3
"""Run the isolated public evaluation over the product HTTP/SSE API.

The runner intentionally does not import application settings or services, does not load
dotenv files, and has no fallback backend. It emits aggregate JSON to stdout only.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.evaluation.public import (  # noqa: E402
    OpenURL,
    PublicEvaluationError,
    load_public_dataset,
    run_public_evaluation,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate or run the aggregate-only public evaluation through /api/v1/chat/stream."
        )
    )
    parser.add_argument("--base-url", required=True, help="HTTP(S) product origin; no credentials")
    parser.add_argument("--manifest", default="public_eval/manifest.json")
    parser.add_argument("--samples", default="public_eval/samples.jsonl")
    parser.add_argument("--model-id", required=True, help="Public operator-provided model label")
    parser.add_argument(
        "--retriever-id", required=True, help="Public operator-provided retriever label"
    )
    parser.add_argument("--build-id", required=True, help="Public operator-provided build label")
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help=("Offline retrieval metric cutoff only; this does not configure the chat backend"),
    )
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate public files and output shape without any HTTP request",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    repo_root: Path | None = None,
    opener: OpenURL | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run the CLI, exposing injection points only for isolated unit tests."""

    output = stdout or sys.stdout
    errors = stderr or sys.stderr
    arguments = _parser().parse_args(argv)
    try:
        root = (repo_root or _REPO_ROOT).resolve(strict=True)
        dataset = load_public_dataset(root, arguments.manifest, arguments.samples)
        result = run_public_evaluation(
            dataset,
            base_url=arguments.base_url,
            model_id=arguments.model_id,
            retriever_id=arguments.retriever_id,
            build_id=arguments.build_id,
            top_k=arguments.top_k,
            timeout_seconds=arguments.timeout_seconds,
            concurrency=arguments.concurrency,
            dry_run=arguments.dry_run,
            opener=opener,
        )
    except PublicEvaluationError as exc:
        print(json.dumps({"error_code": exc.code}, separators=(",", ":")), file=errors)
        return 2
    except Exception:
        print('{"error_code":"PUBLIC_EVALUATION_INTERNAL_ERROR"}', file=errors)
        return 2
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ),
        file=output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
