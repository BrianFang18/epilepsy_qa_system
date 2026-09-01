from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

# 先按标题粗分段，尽量保持医学段落语义完整。
HEADING_PATTERN = re.compile(r"^\s*(#{1,6}\s+.+|第[一二三四五六七八九十0-9]+[章节部分].*)\s*$")


@dataclass
class ParentChunk:
    parent_id: str
    doc_id: str
    title: str
    doc_type: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChildChunk:
    chunk_id: str
    parent_id: str
    doc_id: str
    title: str
    doc_type: str
    text: str
    parent_text: str
    metadata: dict[str, Any] = field(default_factory=dict)


# 第2步：滑动窗口分块
def _sliding_windows(text: str, size: int, overlap: int) -> list[str]:
    clean = (text or "").strip()
    if not clean:
        return []
    if size <= 0:
        raise ValueError("size must be > 0")
    if overlap >= size:
        raise ValueError("overlap must be < size")
    if len(clean) <= size:
        return [clean]

    # 步长=窗口-重叠，确保相邻块共享上下文。
    step = size - overlap
    windows: list[str] = []
    for start in range(0, len(clean), step):
        end = start + size
        piece = clean[start:end].strip()
        if piece:
            windows.append(piece)
        if end >= len(clean):
            break
    return windows


# 第1步：按标题分段
def _split_by_heading_paragraphs(text: str, fallback_size: int = 2000) -> list[str]:
    lines = text.splitlines()
    if not lines:
        return []

    sections: list[str] = []
    buf: list[str] = []
    for ln in lines:
        # 检测标题行（如 "## 诊断标准" 或 "第一章 概述"）
        if HEADING_PATTERN.match(ln) and buf:
            sections.append("\n".join(buf).strip())
            buf = [ln]
        else:
            buf.append(ln)
    if buf:
        sections.append("\n".join(buf).strip())  # 保存最后一段

    merged: list[str] = []
    for section in sections:
        if len(section) <= fallback_size:
            merged.append(section)
        else:
            # 超长段落继续切分，避免后续向量化输入过大。
            merged.extend(_sliding_windows(section, fallback_size, overlap=120))
    return [s for s in merged if s]


# 第3步：构建父子块
def build_parent_child_chunks(
    doc_id: str,
    title: str,
    text: str,
    doc_type: str,
    metadata: dict[str, Any] | None = None,
    parent_size: int = 1600,
    parent_overlap: int = 150,
    child_size: int = 360,
    child_overlap: int = 60,
) -> tuple[list[ParentChunk], list[ChildChunk]]:
    """构建父子分块：父块保语义上下文，子块用于精细检索。"""
    metadata = metadata or {}
    normalized_text = (text or "").replace("\x00", " ").strip()
    if not normalized_text:
        return [], []

    high_level_sections = _split_by_heading_paragraphs(normalized_text, fallback_size=2200)
    if not high_level_sections:
        high_level_sections = [normalized_text]

    parent_chunks: list[ParentChunk] = []
    child_chunks: list[ChildChunk] = []

    parent_seq = 0
    for section in high_level_sections:
        for parent_piece in _sliding_windows(section, parent_size, parent_overlap):
            # 使用 UUID5 让相同输入生成稳定 ID，便于重复入库去重。
            parent_id = (
                f"p_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{doc_id}_{parent_seq}_{parent_piece[:40]}')}"
            )
            parent_seq += 1

            parent = ParentChunk(
                parent_id=parent_id,
                doc_id=doc_id,
                title=title,
                doc_type=doc_type,
                text=parent_piece,
                metadata={**metadata, "level": "parent"},
            )
            parent_chunks.append(parent)

            child_seq = 0
            for child_piece in _sliding_windows(parent_piece, child_size, child_overlap):
                chunk_id = f"c_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{parent_id}_{child_seq}_{child_piece[:40]}')}"
                child_seq += 1
                child = ChildChunk(
                    chunk_id=chunk_id,
                    parent_id=parent_id,
                    doc_id=doc_id,
                    title=title,
                    doc_type=doc_type,
                    text=child_piece,
                    parent_text=parent_piece,
                    metadata={
                        **metadata,
                        "level": "child",
                        "source_parent": parent_id,
                    },
                )
                child_chunks.append(child)

    return parent_chunks, child_chunks
