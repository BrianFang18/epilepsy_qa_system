"""V2 understanding module: 方言规范化和指代消解"""

from __future__ import annotations

from .coreference import CoreferenceResolver, ResolvedUtterance
from .dialect_normalizer import DialectNormalizer, DialectNormalizerFactory

__all__ = [
    "DialectNormalizer",
    "DialectNormalizerFactory",
    "CoreferenceResolver",
    "ResolvedUtterance",
]
