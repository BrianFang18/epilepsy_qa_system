"""
PDF 文本提取模块
================
支持从 PDF 文件中提取结构化文本，专为中文医学文档优化。

依赖安装：
    pip install pymupdf pytesseract pdfplumber pillow

    # Ubuntu/Debian 系统级 OCR（英文）
    sudo apt install tesseract-ocr

    # 中文 OCR（推荐）
    sudo apt install tesseract-ocr tesseract-ocr-chi-sim

用法：
    from app.retrieval.pdf_processor import PDFProcessor, PDFDocument

    processor = PDFProcessor()
    doc = processor.process("path/to/document.pdf")
    print(doc.title)
    print(f"提取了 {len(doc.pages)} 页，{doc.word_count} 字")

    # 获取所有文本块（按章节/段落切分）
    for block in doc.blocks:
        print(block[:100])
"""

from __future__ import annotations

import importlib
import io
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 安装检测
# ---------------------------------------------------------------------------
_MUPDF_AVAILABLE = True
_PDFPLUMBER_AVAILABLE = True
_PYTESSERACT_AVAILABLE = True

try:
    import fitz  # PyMuPDF
except ImportError:
    _MUPDF_AVAILABLE = False

try:
    importlib.import_module("pdfplumber")
except ImportError:
    _PDFPLUMBER_AVAILABLE = False

try:
    importlib.import_module("pytesseract")
except ImportError:
    _PYTESSERACT_AVAILABLE = False


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class PDFPage:
    page_num: int
    text: str
    images: list[bytes] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)
    is_scanned: bool = False


@dataclass
class PDFDocument:
    """单个 PDF 文件的提取结果。"""

    file_path: str
    title: str
    pages: list[PDFPage] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    extraction_method: str = "auto"

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)

    @property
    def word_count(self) -> int:
        return len(self.full_text)

    @property
    def blocks(self) -> list[str]:
        """
        将全文切分为语义块（段落/章节）。
        优先按标题级别（#、##、一、二、三）分段，
        其次按换行+空行分割，
        最后合并过短的块。
        """
        text = self.full_text
        lines = text.splitlines()

        heading_re = re.compile(
            r"^\s*(#{1,6}\s|"
            r"第[一二三四五六七八九十\d]+[章节部分节条]|"
            r"(?:【|〔)\d+[】〕]|"
            r"[0-9]+\.[0-9]+\s|"
            r"[0-9]+\s+(?:诊断|治疗|适应|禁忌|推荐|方案|原则|分类|定义|概述|流行病学|发病机制|病理|病因|预后|并发症|检查|实验室|影像|脑电图|鉴别|药物|手术|护理|健康教育)|"
            r"[A-Z][A-Z0-9\s/]+(?:指南|共识|推荐|标准|规范)|"
            r"(?:成人|儿童|老年|育龄|妊娠)[^，,。]{0,20}(?:用药|治疗|管理)"
            r")",
            re.IGNORECASE,
        )

        sections: list[str] = []
        buf: list[str] = []
        MIN_BLOCK = 80  # 字符，过短则合并

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if buf:
                    sections.append("\n".join(buf).strip())
                    buf = []
                continue
            if heading_re.match(line):
                if buf:
                    sections.append("\n".join(buf).strip())
                    buf = []
            buf.append(line)

        if buf:
            sections.append("\n".join(buf).strip())

        # 合并过短的块
        merged: list[str] = []
        for sec in sections:
            if len(sec) < MIN_BLOCK and merged:
                merged[-1] = merged[-1] + "\n" + sec
            elif sec:
                merged.append(sec)

        return [m for m in merged if len(m) >= 30]


# ---------------------------------------------------------------------------
# 核心提取器
# ---------------------------------------------------------------------------


class PDFProcessor:
    """
    多策略 PDF 文本提取器。
    策略优先级：
      1. PyMuPDF（最快的原生文本提取）
      2. pdfplumber（表格提取更强）
      3. OCR（扫描/PDF 图片页兜底）
    """

    def __init__(
        self,
        lang: str = "chi_sim+eng",
        ocr_threshold_dpi: int = 200,
        min_text_ratio: float = 0.02,
    ):
        """
        Args:
            lang: Tesseract OCR 语言代码，中英文混排用 'chi_sim+eng'
            ocr_threshold_dpi: 图片分辨率低于此值时触发 OCR
            min_text_ratio: 页面的文字覆盖率低于此值时触发 OCR
        """
        self.lang = lang
        self.ocr_threshold_dpi = ocr_threshold_dpi
        self.min_text_ratio = min_text_ratio

        if not _MUPDF_AVAILABLE:
            raise ImportError("需要安装 PyMuPDF: pip install pymupdf")

    def process(self, file_path: str | Path) -> PDFDocument:
        """提取单个 PDF 文件。"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError("文件不存在: " + str(path))

        doc = PDFDocument(file_path=str(path), title=self._extract_title(path))

        try:
            # 策略1: PyMuPDF 快速提取
            pages = self._extract_fitz(path)
            doc.extraction_method = "pymupdf"

            # 检测扫描页并 OCR 兜底
            for page in pages:
                if self._looks_scanned(page):
                    ocr_text = self._ocr_page(path, page.page_num)
                    if ocr_text:
                        page.text = ocr_text
                        page.is_scanned = True
                        doc.extraction_method = "pymupdf+ocr"

            doc.pages = pages

        except Exception as e:
            # 策略2: pdfplumber 兜底
            if _PDFPLUMBER_AVAILABLE:
                try:
                    pages = self._extract_pdfplumber(path)
                    doc.pages = pages
                    doc.extraction_method = "pdfplumber"
                except Exception:
                    raise RuntimeError(f"PyMuPDF 和 pdfplumber 均失败: {e}") from e
            else:
                raise RuntimeError(f"PyMuPDF 提取失败，且 pdfplumber 未安装: {e}") from e

        # 补充元数据
        doc.metadata = {
            "pages": len(doc.pages),
            "word_count": doc.word_count,
            "extraction_method": doc.extraction_method,
        }

        return doc

    # ── PyMuPDF 提取 ────────────────────────────────────────────────────────

    def _extract_fitz(self, path: Path) -> list[PDFPage]:
        import fitz

        pages: list[PDFPage] = []
        with fitz.open(path) as pdf:
            for i, page in enumerate(pdf):
                text = page.get_text("text")
                if not text or len(text.strip()) < 10:
                    text = page.get_text("blocks") and page.get_text("text") or ""

                tables = self._extract_tables_fitz(page)
                images = self._extract_images_fitz(page)

                pages.append(
                    PDFPage(
                        page_num=i + 1,
                        text=self._clean_text(text),
                        tables=tables,
                        images=images,
                    )
                )
        return pages

    def _extract_tables_fitz(self, page: fitz.Page) -> list[list[list[str]]]:
        """用 PyMuPDF 提取表格。"""
        try:
            tabs = page.find_tables()
            if tabs and tabs[0]:
                result = []
                for table in tabs[0]:
                    rows = []
                    for row in table.extract():
                        cleaned = [str(c).strip() if c else "" for c in row]
                        rows.append(cleaned)
                    if rows:
                        result.append(rows)
                return result
        except Exception:
            pass
        return []

    def _extract_images_fitz(self, page: fitz.Page) -> list[bytes]:
        """提取页内图片（用于 OCR）。"""
        images: list[bytes] = []
        try:
            for img_info in page.get_images(full=True):
                xref = img_info[0]
                img_data = page.parent.extract_image(xref)
                if img_data:
                    images.append(img_data["image"])
        except Exception:
            pass
        return images

    # ── pdfplumber 提取（表格更强）───────────────────────────────────────

    def _extract_pdfplumber(self, path: Path) -> list[PDFPage]:
        import pdfplumber

        pages: list[PDFPage] = []
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                tables = []
                for table in page.extract_tables():
                    cleaned_table = [[str(c).strip() if c else "" for c in row] for row in table]
                    tables.append(cleaned_table)

                pages.append(
                    PDFPage(
                        page_num=i + 1,
                        text=self._clean_text(text),
                        tables=tables,
                    )
                )
        return pages

    # ── OCR 兜底 ─────────────────────────────────────────────────────────

    def _looks_scanned(self, page: PDFPage) -> bool:
        """判断页面是否为扫描页（文字极少）。"""
        if not page.text or len(page.text.strip()) < 50:
            return True
        # 计算文字覆盖率
        page_area = 1000  # 任意单位
        char_count = len(page.text.strip())
        ratio = char_count / page_area
        return ratio < self.min_text_ratio

    def _ocr_page(self, path: Path, page_num: int) -> str:
        """对指定页执行 OCR。"""
        if not _PYTESSERACT_AVAILABLE:
            return ""

        try:
            import fitz
            import pytesseract
            from PIL import Image

            with fitz.open(path) as pdf:
                page = pdf[page_num - 1]
                # 渲染为高分辨率图片
                mat = fitz.Matrix(2.0, 2.0)  # 2x 缩放
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("png")

            img = Image.open(io.BytesIO(img_bytes))
            text = pytesseract.image_to_string(
                img,
                lang=self.lang,
                config="--psm 4 --oem 3",
            )
            return self._clean_text(text)

        except Exception:
            return ""

    # ── 工具方法 ─────────────────────────────────────────────────────────

    @staticmethod
    def _clean_text(text: str) -> str:
        """清理 PDF 提取的原始文本。"""
        if not text:
            return ""
        # 去除零宽字符
        text = re.sub(r"[\u200b-\u200f\u2028-\u202f\ufeff]", "", text)
        # 规范化换行
        text = re.sub(r"([^\n])\n([^\n])", r"\1 \2", text)
        # 去除多余空格
        text = re.sub(r"[ \t]+", " ", text)
        # 去除行首行尾空格
        lines = [ln.strip() for ln in text.splitlines()]
        return "\n".join(ln for ln in lines if ln)

    @staticmethod
    def _extract_title(path: Path) -> str:
        """从文件名推断标题。"""
        name = path.stem
        # 去掉常见后缀
        for suffix in ["_final", "_v1", "_v2", "_chinese", "_CN", "_EN", "_中文", "_英文"]:
            name = name.replace(suffix, "")
        # 下划线/连字符转空格
        name = name.replace("_", " ").replace("-", " ")
        return name.strip()

    def process_batch(
        self,
        paths: list[str | Path],
        verbose: bool = True,
    ) -> list[PDFDocument]:
        """批量处理多个 PDF。"""
        results: list[PDFDocument] = []
        for p in paths:
            try:
                doc = self.process(p)
                if verbose:
                    print(
                        f"  ✓ [{doc.extraction_method}] {Path(p).name}: "
                        f"{len(doc.pages)}p / {doc.word_count}字"
                    )
                results.append(doc)
            except Exception as e:
                if verbose:
                    print(f"  ✗ {Path(p).name}: {e}")
        return results

    def pdf_to_ingest_items(
        self,
        doc: PDFDocument,
        source_label: str = "pdf",
        doc_type: str = "literature",
    ) -> list[dict[str, Any]]:
        """
        将 PDFDocument 转换为 IngestTextRequest 格式。
        每个语义块生成一个条目，父文本为整页内容。
        """
        items: list[dict[str, Any]] = []
        doc_id_base = f"pdf_{uuid.uuid5(uuid.NAMESPACE_DNS, doc.file_path)}"[:50]

        # 构建父文本：所有页拼接
        parent_text = doc.full_text

        for i, block in enumerate(doc.blocks):
            if len(block) < 30:
                continue

            items.append(
                {
                    "doc_id": doc_id_base,
                    "title": doc.title,
                    "doc_type": doc_type,
                    "text": block,
                    "parent_text": parent_text[:3000],  # 截断避免过大
                    "source": source_label,
                    "metadata": {
                        "source_label": source_label,
                        "file_path": doc.file_path,
                        "pages": doc.metadata.get("pages", 0),
                        "word_count": doc.word_count,
                        "extraction_method": doc.extraction_method,
                        "block_index": i,
                        "total_blocks": len(doc.blocks),
                        **doc.metadata,
                    },
                }
            )

        return items


# ---------------------------------------------------------------------------
# CLI 入口（单独运行此文件时可用）
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PDF 文本提取工具")
    parser.add_argument("files", nargs="+", help="PDF 文件路径")
    parser.add_argument("--output", "-o", default=None, help="输出 JSON 路径")
    parser.add_argument(
        "--type", default="literature", choices=["literature", "clinical"], help="文档类型"
    )
    args = parser.parse_args()

    processor = PDFProcessor()

    docs = processor.process_batch([str(f) for f in args.files])

    if args.output:
        import json

        all_items = []
        for doc in docs:
            items = processor.pdf_to_ingest_items(doc, doc_type=args.type)
            all_items.extend(items)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(all_items, f, ensure_ascii=False, indent=2)
        print(f"已保存 {len(all_items)} 个文本块到 {args.output}")
    else:
        for doc in docs:
            print(f"\n{'='*60}")
            print(f"文档: {doc.title}")
            print(f"页数: {len(doc.pages)}, 字数: {doc.word_count}")
            print(f"提取方式: {doc.extraction_method}")
            print(f"语义块: {len(doc.blocks)}")
            print(f"前300字:\n{doc.full_text[:300]}")
