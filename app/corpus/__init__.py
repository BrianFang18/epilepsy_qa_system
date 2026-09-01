"""Offline, license-gated corpus preparation for Europe PMC.

Importing this package performs no file, environment, or network I/O.
"""

from app.corpus.config import SourceConfig, load_source_config
from app.corpus.models import (
    ArticleCandidate,
    FileArtifact,
    LicenseDecision,
    NormalizedArticle,
    ValidationReport,
)
from app.corpus.pipeline import (
    CorpusPipelineError,
    CorpusPipelinePaths,
    build_http_client,
    resolve_pipeline_paths,
    resolve_repository_path,
    sync_corpus,
    validate_corpus,
)

__all__ = [
    "ArticleCandidate",
    "CorpusPipelineError",
    "CorpusPipelinePaths",
    "FileArtifact",
    "LicenseDecision",
    "NormalizedArticle",
    "SourceConfig",
    "ValidationReport",
    "build_http_client",
    "load_source_config",
    "resolve_pipeline_paths",
    "resolve_repository_path",
    "sync_corpus",
    "validate_corpus",
]
