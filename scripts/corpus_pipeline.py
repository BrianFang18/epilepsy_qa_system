#!/usr/bin/env python3
"""Minimal CLI for the explicit, offline-safe corpus pipeline API."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Never

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.corpus.config import load_source_config  # noqa: E402
from app.corpus.models import CorpusError, ValidationReport  # noqa: E402
from app.corpus.pipeline import (  # noqa: E402
    resolve_repository_path,
    sync_corpus,
    validate_corpus,
)


class _CliArgumentError(Exception):
    pass


class _StableArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        del message
        raise _CliArgumentError


def build_parser() -> argparse.ArgumentParser:
    parser = _StableArgumentParser(prog="corpus_pipeline.py")
    common = _StableArgumentParser(add_help=False)
    common.add_argument("--repo-root", type=Path, default=_PROJECT_ROOT)
    common.add_argument("--config", type=Path, default=Path("config/corpus_sources.json"))
    common.add_argument("--manifest", type=Path)
    common.add_argument("--summary", type=Path)
    common.add_argument("--artifact-root", type=Path)
    common.add_argument("--target", type=int)

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=_StableArgumentParser,
    )
    sync_parser = subparsers.add_parser("sync", parents=[common])
    sync_parser.add_argument("--candidate-limit", type=int)
    subparsers.add_parser("validate", parents=[common])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except _CliArgumentError:
        _write_error("invalid_cli_arguments")
        return 2
    try:
        repository_root = resolve_repository_path(args.repo_root, Path("."))
        config_path = resolve_repository_path(repository_root, args.config)
        config = load_source_config(config_path)
        if args.command == "sync":
            report = sync_corpus(
                repository_root,
                config,
                manifest_path=args.manifest,
                summary_path=args.summary,
                artifact_root=args.artifact_root,
                target=args.target,
                candidate_limit=args.candidate_limit,
            )
        else:
            report = validate_corpus(
                repository_root,
                config,
                manifest_path=args.manifest,
                summary_path=args.summary,
                artifact_root=args.artifact_root,
                target=args.target,
            )
    except CorpusError as exc:
        _write_error(exc.code)
        return 2
    except Exception:
        _write_error("pipeline_unexpected_error")
        return 2

    _write_report(report)
    return 0 if report.ok else 2


def _write_report(report: ValidationReport) -> None:
    print(json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _write_error(code: str) -> None:
    print(
        json.dumps({"error": code}, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        file=sys.stderr,
    )


if __name__ == "__main__":
    raise SystemExit(main())
