"""Strict per-article JATS license classification."""

from __future__ import annotations

import hashlib
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import Mapping

from app.corpus.models import LicenseDecision, LicenseRejectedError

_VERSION = r"(?:2\.0|2\.5|3\.0|4\.0)"
_SPDX_BY_RE = re.compile(rf"\bcc[\s_-]*by[\s_-]*({_VERSION})\b", re.IGNORECASE)
_CC0_RE = re.compile(r"\bcc[\s_-]*0(?:[\s_-]*1\.0)?\b", re.IGNORECASE)
_BY_URL_RE = re.compile(
    rf"https?://(?:www\.)?creativecommons\.org/licenses/([^/\s]+)/({_VERSION})(?:/|\b)",
    re.IGNORECASE,
)
_CC0_URL_RE = re.compile(
    r"https?://(?:www\.)?creativecommons\.org/publicdomain/zero/1\.0(?:/|\b)",
    re.IGNORECASE,
)
_ATTRIBUTION_RE = re.compile(
    rf"creative\s+commons\s+attribution(?:\s+(?:international|unported))?"
    rf"(?:\s+license)?(?:\s+(?:version\s+)?)?({_VERSION})\b",
    re.IGNORECASE,
)
_PROHIBITED_RE = re.compile(
    r"(?:licenses/(?:by-)?(?:nc|nd|sa)|\bby[\s_-]+(?:nc|nd|sa)\b|"
    r"non[\s-]*commercial|no[\s-]*derivatives?|share[\s-]*alike|"
    r"custom\s+licen[cs]e)",
    re.IGNORECASE,
)


def classify_license(root: ET.Element, allowlist: Mapping[str, str]) -> LicenseDecision:
    """Require every JATS license declaration to resolve to one allowed SPDX value."""

    license_nodes = [node for node in root.iter() if _local_name(node.tag) == "license"]
    if not license_nodes:
        raise LicenseRejectedError(
            "article has no JATS license node",
            code="license_missing",
        )

    statements = [_normalized_statement(node) for node in license_nodes]
    decisions: set[str] = set()
    for statement in statements:
        if _PROHIBITED_RE.search(statement):
            raise LicenseRejectedError(
                "license contains a prohibited NC, ND, SA, or custom condition",
                code="license_prohibited",
            )
        claims = _claims(statement)
        if not claims:
            raise LicenseRejectedError(
                "license declaration is not explicit enough for the allowlist",
                code="license_unknown",
            )
        if len(claims) != 1:
            raise LicenseRejectedError(
                "license declaration contains conflicting classifications",
                code="license_conflict",
            )
        decisions.update(claims)

    if len(decisions) != 1:
        raise LicenseRejectedError(
            "multiple license nodes conflict",
            code="license_conflict",
        )
    spdx = next(iter(decisions))
    url = allowlist.get(spdx)
    if url is None:
        raise LicenseRejectedError(
            "recognized license is not in the configured allowlist",
            code="license_not_allowlisted",
        )
    declaration = "\n---\n".join(statements).encode("utf-8")
    return LicenseDecision(
        spdx=spdx,
        url=url,
        declaration_sha256=hashlib.sha256(declaration).hexdigest(),
    )


def _normalized_statement(node: ET.Element) -> str:
    license_type = _clean(node.attrib.get("license-type", ""))
    href = ""
    for key, value in node.attrib.items():
        if _local_name(key) == "href":
            href = _clean(value)
            break
    paragraphs: list[str] = []
    for descendant in node.iter():
        if _local_name(descendant.tag) == "license-p":
            text = _clean("".join(descendant.itertext()))
            if text:
                paragraphs.append(text)
    fields = [f"license-type={license_type}", f"href={href}"]
    fields.extend(f"license-p={paragraph}" for paragraph in paragraphs)
    return "\n".join(fields)


def _claims(statement: str) -> set[str]:
    claims: set[str] = set()
    if _CC0_URL_RE.search(statement) or _CC0_RE.search(statement):
        claims.add("CC0-1.0")
    for match in _BY_URL_RE.finditer(statement):
        license_code = match.group(1).casefold()
        version = match.group(2)
        if license_code == "by":
            claims.add(f"CC-BY-{version}")
        else:
            claims.add(f"PROHIBITED-{license_code.upper()}-{version}")
    for match in _SPDX_BY_RE.finditer(statement):
        claims.add(f"CC-BY-{match.group(1)}")
    for match in _ATTRIBUTION_RE.finditer(statement):
        claims.add(f"CC-BY-{match.group(1)}")
    return claims


def _clean(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1]
