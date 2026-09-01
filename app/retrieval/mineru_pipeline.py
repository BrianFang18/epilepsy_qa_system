"""
文档解析
MinerU 解析适配器：
- 若检测到 MinerU，优先用于 PDF 解析。
- 否则自动回退到 pypdf/纯文本读取。
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .chunking import ChildChunk, ParentChunk, build_parent_child_chunks


@dataclass
class ParsedDocument:
    doc_id: str
    title: str
    text: str
    doc_type: str
    source: str = "file"
    metadata: dict[str, Any] = field(default_factory=dict)


class MinerUParser:
    """
    MinerU 解析适配器：
    - 若检测到 MinerU，优先用于 PDF 解析。
    - 否则自动回退到 pypdf/纯文本读取。
    """

    def __init__(self) -> None:
        self.mineru_available = importlib.util.find_spec("magic_pdf") is not None

    def parse_file(
        self,
        file_path: str,
        doc_id: str,
        title: str | None = None,
        doc_type: str = "literature",
        metadata: dict[str, Any] | None = None,
    ) -> ParsedDocument:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        metadata = metadata or {}
        resolved_title = title or path.stem
        suffix = path.suffix.lower()

        if suffix in {".txt", ".md"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
        elif suffix == ".pdf":
            text = self._parse_pdf(path)
        else:
            text = path.read_text(encoding="utf-8", errors="ignore")

        text = (text or "").strip()
        if not text:
            raise ValueError(f"Parsed empty text from: {file_path}")

        return ParsedDocument(
            doc_id=doc_id,
            title=resolved_title,
            text=text,
            doc_type=doc_type,
            source=str(path),
            metadata=metadata,
        )

    def parse_to_chunks(
        self,
        file_path: str,
        doc_id: str,
        title: str | None = None,
        doc_type: str = "literature",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[list[ParentChunk], list[ChildChunk]]:
        parsed = self.parse_file(
            file_path=file_path,
            doc_id=doc_id,
            title=title,
            doc_type=doc_type,
            metadata=metadata,
        )
        return build_parent_child_chunks(
            doc_id=parsed.doc_id,
            title=parsed.title,
            text=parsed.text,
            doc_type=parsed.doc_type,
            metadata={**parsed.metadata, "source": parsed.source},
        )

    def _parse_pdf(self, path: Path) -> str:
        if self.mineru_available:
            text = self._parse_pdf_with_mineru(path)
            if text.strip():
                return text
        return self._parse_pdf_with_pypdf(path)

    def _parse_pdf_with_mineru(self, path: Path) -> str:
        try:
            # MinerU 不同版本 API 可能变化，失败时交给 fallback 处理。
            from magic_pdf.data.data_reader_writer import FileBasedDataReader

            reader = FileBasedDataReader(str(path))
            content = reader.read()
            if isinstance(content, bytes):
                return content.decode("utf-8", errors="ignore")
            return str(content)
        except Exception:
            return ""

    def _parse_pdf_with_pypdf(self, path: Path) -> str:
        try:
            from pypdf import PdfReader
        except Exception as exc:
            raise RuntimeError("pypdf is required for PDF fallback parsing.") from exc

        reader = PdfReader(str(path))
        pages = [p.extract_text() or "" for p in reader.pages]
        return "\n".join(pages)
