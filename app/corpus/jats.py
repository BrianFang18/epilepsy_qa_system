"""Safe JATS parsing and deterministic Markdown normalization."""

from __future__ import annotations

import hashlib
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import Mapping

from app.corpus.license import classify_license
from app.corpus.models import JatsValidationError, NormalizedArticle, XmlSecurityError

_PMCID_RE = re.compile(r"^(?:PMC)?(\d+)$", re.IGNORECASE)
_ALWAYS_EXCLUDED = {
    "addr-line",
    "address",
    "aff",
    "email",
    "fig",
    "graphic",
    "institution",
    "media",
    "object-id",
    "script",
    "supplementary-material",
}
_REFERENCE_SECTION_TYPES = {"bibliography", "ref", "reference", "references"}
_REFERENCE_TITLES = {"bibliography", "reference", "references"}


def normalize_jats(
    xml_bytes: bytes,
    *,
    expected_pmcid: str,
    source_url: str,
    license_allowlist: Mapping[str, str],
    min_body_chars: int,
    include_references: bool = False,
) -> NormalizedArticle:
    """Parse non-networked XML and emit byte-stable UTF-8 Markdown."""

    safe_xml = strip_doctype(xml_bytes)
    try:
        root = ET.fromstring(safe_xml)
    except ET.ParseError as exc:
        raise JatsValidationError("JATS XML is not well formed", code="invalid_xml") from exc
    if _local_name(root.tag) != "article":
        raise JatsValidationError("JATS root must be article", code="invalid_jats_root")

    article_meta = _first_descendant(root, "article-meta")
    if article_meta is None:
        raise JatsValidationError("JATS article-meta is missing", code="missing_article_meta")
    pmcid = _article_id(article_meta, {"pmc", "pmcid"})
    normalized_expected = _normalize_pmcid(expected_pmcid)
    if pmcid is None:
        raise JatsValidationError("JATS PMCID is missing", code="missing_pmcid")
    normalized_actual = _normalize_pmcid(pmcid)
    if normalized_actual != normalized_expected:
        raise JatsValidationError("JATS PMCID does not match request", code="pmcid_mismatch")

    body = _first_descendant(root, "body")
    if body is None:
        raise JatsValidationError("JATS body is missing", code="missing_body")

    license_decision = classify_license(root, license_allowlist)
    title_node = _first_descendant(article_meta, "article-title")
    title = _visible_text(title_node) if title_node is not None else ""
    if not title:
        raise JatsValidationError("JATS article title is missing", code="missing_title")
    pmid = _article_id(article_meta, {"pmid"})
    doi = _article_id(article_meta, {"doi"})
    if doi is not None:
        doi = doi.lower()
    authors = _public_authors(article_meta)
    abstract = _abstract_text(article_meta)
    body_blocks, body_plain = _render_body(body, include_references=include_references)
    if len(body_plain) < min_body_chars:
        raise JatsValidationError(
            "JATS body is below the configured minimum",
            code="body_too_short",
        )
    if not body_blocks:
        raise JatsValidationError("JATS body has no allowed content", code="empty_body")

    lines = [
        f"# {title}",
        "",
        f"- PMCID: {normalized_actual}",
    ]
    if doi:
        lines.append(f"- DOI: {doi}")
    lines.extend(
        [
            f"- Source: {source_url}",
            f"- License: {license_decision.spdx} ({license_decision.url})",
        ]
    )
    if abstract:
        lines.extend(["", "## Abstract", "", abstract])
    lines.extend(["", "## Body", ""])
    lines.extend(body_blocks)
    canonical_text = unicodedata.normalize("NFC", "\n".join(lines).strip()) + "\n"
    canonical_bytes = canonical_text.encode("utf-8")
    return NormalizedArticle(
        pmcid=normalized_actual,
        pmid=pmid,
        doi=doi,
        title=title,
        authors=authors,
        license=license_decision,
        canonical_bytes=canonical_bytes,
        canonical_sha256=hashlib.sha256(canonical_bytes).hexdigest(),
    )


def strip_doctype(xml_bytes: bytes) -> bytes:
    """Remove external DOCTYPE declarations and reject every internal subset/entity."""

    lowered = xml_bytes.lower()
    if b"<!entity" in lowered:
        raise XmlSecurityError(
            "XML entity declarations are forbidden",
            code="xml_entity_forbidden",
        )

    output = bytearray()
    cursor = 0
    while True:
        start = lowered.find(b"<!doctype", cursor)
        if start < 0:
            output.extend(xml_bytes[cursor:])
            break
        output.extend(xml_bytes[cursor:start])
        quote: int | None = None
        internal_subset = False
        index = start + len(b"<!doctype")
        while index < len(xml_bytes):
            byte = xml_bytes[index]
            if quote is not None:
                if byte == quote:
                    quote = None
            elif byte in (ord('"'), ord("'")):
                quote = byte
            elif byte == ord("["):
                internal_subset = True
            elif byte == ord(">"):
                break
            index += 1
        if index >= len(xml_bytes):
            raise XmlSecurityError(
                "XML DOCTYPE is not terminated",
                code="invalid_doctype",
            )
        if internal_subset:
            raise XmlSecurityError(
                "XML internal DTD subsets are forbidden",
                code="xml_internal_subset_forbidden",
            )
        cursor = index + 1
    return bytes(output)


def _render_body(body: ET.Element, *, include_references: bool) -> tuple[list[str], str]:
    blocks: list[str] = []
    plain_parts: list[str] = []

    def add_block(markdown: str, plain: str) -> None:
        if not plain:
            return
        if blocks and blocks[-1] != "":
            blocks.append("")
        blocks.append(markdown)
        plain_parts.append(plain)

    def visit(node: ET.Element, section_depth: int) -> None:
        tag = _local_name(node.tag)
        if tag in _ALWAYS_EXCLUDED:
            return
        if tag == "ref-list":
            if include_references:
                for ref in node.iter():
                    if _local_name(ref.tag) == "ref":
                        text = _visible_text(ref)
                        add_block(f"- {text}", text)
            return
        if tag == "sec":
            if not include_references and _is_reference_section(node):
                return
            title_node = _direct_child(node, "title")
            if title_node is not None:
                section_title = _visible_text(title_node)
                if section_title:
                    heading_level = min(3 + section_depth, 6)
                    add_block(f"{'#' * heading_level} {section_title}", section_title)
            for child in node:
                if child is not title_node:
                    visit(child, section_depth + 1)
            return
        if tag == "p":
            text = _visible_text(node)
            add_block(text, text)
            return
        if tag == "list":
            ordered = node.attrib.get("list-type", "").casefold() in {
                "order",
                "ordered",
                "number",
            }
            number = 1
            for item in node:
                if _local_name(item.tag) != "list-item":
                    continue
                text = _list_item_text(item)
                marker = f"{number}." if ordered else "-"
                add_block(f"{marker} {text}", text)
                number += 1
            return
        if tag == "table-wrap":
            caption = _first_descendant(node, "caption")
            text = _visible_text(caption) if caption is not None else ""
            add_block(f"Table: {text}", text)
            return
        if tag in {"caption", "list-item", "title"}:
            return
        for child in node:
            visit(child, section_depth)

    for child in body:
        visit(child, 0)
    while blocks and blocks[-1] == "":
        blocks.pop()
    return blocks, _clean(" ".join(plain_parts))


def _is_reference_section(section: ET.Element) -> bool:
    section_type = _clean(section.attrib.get("sec-type", "")).casefold()
    if section_type in _REFERENCE_SECTION_TYPES:
        return True
    title = _direct_child(section, "title")
    return title is not None and _visible_text(title).casefold() in _REFERENCE_TITLES


def _list_item_text(item: ET.Element) -> str:
    parts: list[str] = []
    for child in item:
        tag = _local_name(child.tag)
        if tag == "p":
            text = _visible_text(child)
            if text:
                parts.append(text)
        elif tag not in _ALWAYS_EXCLUDED and tag != "list":
            text = _visible_text(child)
            if text:
                parts.append(text)
    if not parts:
        return _visible_text(item)
    return _clean(" ".join(parts))


def _abstract_text(article_meta: ET.Element) -> str:
    abstract = _first_descendant(article_meta, "abstract")
    if abstract is None:
        return ""
    paragraphs = [_visible_text(node) for node in abstract.iter() if _local_name(node.tag) == "p"]
    paragraphs = [paragraph for paragraph in paragraphs if paragraph]
    return _clean(" ".join(paragraphs)) if paragraphs else _visible_text(abstract)


def _public_authors(article_meta: ET.Element) -> tuple[str, ...]:
    authors: list[str] = []
    for contrib in article_meta.iter():
        if _local_name(contrib.tag) != "contrib":
            continue
        contrib_type = contrib.attrib.get("contrib-type", "author").casefold()
        if contrib_type != "author":
            continue
        surname = ""
        given = ""
        collective = ""
        for descendant in contrib.iter():
            tag = _local_name(descendant.tag)
            if tag == "surname" and not surname:
                surname = _visible_text(descendant)
            elif tag in {"given-names", "given-name"} and not given:
                given = _visible_text(descendant)
            elif tag == "collab" and not collective:
                collective = _visible_text(descendant)
        name = collective or _clean(" ".join(part for part in (given, surname) if part))
        if name and "@" not in name and name not in authors:
            authors.append(name)
    return tuple(authors)


def _article_id(article_meta: ET.Element, accepted_types: set[str]) -> str | None:
    for node in article_meta.iter():
        if _local_name(node.tag) != "article-id":
            continue
        id_type = node.attrib.get("pub-id-type", "").casefold()
        if id_type in accepted_types:
            value = _visible_text(node)
            if value:
                return value
    return None


def _normalize_pmcid(value: str) -> str:
    match = _PMCID_RE.fullmatch(_clean(value))
    if match is None:
        raise JatsValidationError("PMCID is malformed", code="invalid_pmcid")
    return f"PMC{int(match.group(1))}"


def _visible_text(node: ET.Element | None) -> str:
    if node is None or _local_name(node.tag) in _ALWAYS_EXCLUDED:
        return ""
    fragments: list[str] = []

    def collect(current: ET.Element) -> None:
        if current.text:
            fragments.append(current.text)
        for child in current:
            if _local_name(child.tag) not in _ALWAYS_EXCLUDED:
                collect(child)
            if child.tail:
                fragments.append(child.tail)

    collect(node)
    return _clean(" ".join(fragments))


def _clean(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    without_controls = "".join(
        char for char in normalized if unicodedata.category(char) != "Cc" or char in "\t\n\r"
    )
    return " ".join(without_controls.split())


def _first_descendant(node: ET.Element, name: str) -> ET.Element | None:
    for descendant in node.iter():
        if _local_name(descendant.tag) == name:
            return descendant
    return None


def _direct_child(node: ET.Element, name: str) -> ET.Element | None:
    for child in node:
        if _local_name(child.tag) == name:
            return child
    return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1]
