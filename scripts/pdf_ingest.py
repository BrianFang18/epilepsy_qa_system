#!/usr/bin/env python3
"""
pdf_ingest.py — PDF 文档批量入库脚本
=====================================
将本地 PDF 文档（指南/共识/药物说明书/专著章节）提取文本后，
通过 HTTP API 写入项目知识库，并同时更新 data/knowledge_base.json。

依赖安装：
    pip install pymupdf pdfplumber pytesseract pillow tqdm requests

    # 中文 OCR（可选）
    sudo apt install tesseract-ocr tesseract-ocr-chi-sim

用法：
    # 1. 扫描 data/pdfs/ 目录下所有 PDF 并入库（需先启动 server）
    python scripts/pdf_ingest.py

    # 2. 指定目录扫描
    python scripts/pdf_ingest.py --pdf-dir data/pdfs/

    # 3. 仅提取，不入库（生成 JSON，方便检查内容）
    python scripts/pdf_ingest.py --mode extract-only --output data/pdf_extracted.json

    # 4. 仅入库（已有提取好的 JSON）
    python scripts/pdf_ingest.py --mode ingest-only --input data/pdf_extracted.json

    # 5. 指定 doc_type 批量入库
    python scripts/pdf_ingest.py --pdf-dir data/pdfs/clinical/ --doc-type clinical

    # 6. 重建整个 knowledge_base.json（所有文本块合并）
    python scripts/pdf_ingest.py --mode rebuild-kb

架构说明：

    PDF → 文本提取（按章节/段落切块）→ IngestTextRequest 格式
    → HTTP POST /v1/ingest/text → 向量数据库
    同时追加写入 data/knowledge_base.json（JSON 快照）

核心逻辑：按标题/段落切块，每个语义块生成一个 ChildChunk，父文本为整页内容
    入库后 LLM 在推理时会同时看到精细块（精准匹配关键词）和父块（上下文完整），
    从而准确回答"ILAE 2017 三层次分类是什么"这类结构化问题。
"""



from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 路径设置
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# PDF Processor（延迟导入，避免未安装时报错）
# ---------------------------------------------------------------------------
_pdf_processor = None

def get_processor():
    global _pdf_processor
    if _pdf_processor is None:
        from app.retrieval.pdf_processor import PDFProcessor
        _pdf_processor = PDFProcessor()
    return _pdf_processor


# ---------------------------------------------------------------------------
# 默认 PDF 目录与 doc_type 映射
# ---------------------------------------------------------------------------

# 用户只需把 PDF 放到对应目录，脚本自动识别 doc_type
PDF_DIRS = {
    "guidelines":  "guidelines",   # 临床指南 / 共识声明
    "drug_labels":  "drug_labels",  # 药物说明书
    "textbooks":    "textbooks",     # 医学专著章节
    "protocols":    "protocols",     # 诊疗规范 / 操作规程
}

DEFAULT_PDF_DIR = ROOT / "data" / "pdfs"
KB_JSON = ROOT / "data" / "knowledge_base.json"
KB_BACKUP = ROOT / "data" / f"knowledge_base.{datetime.now():%Y%m%d_%H%M%S}.json.bak"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def save_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    size_mb = path.stat().st_size / 1024 / 1024
    print(f"  ✓ 已保存 → {path} ({size_mb:.1f} MB)")


def load_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def scan_pdfs(pdf_dir: Path) -> dict[str, list[Path]]:
    """递归扫描目录，返回 {(source_label): [pdf_paths]}。"""
    if not pdf_dir.exists():
        print(f"  目录不存在: {pdf_dir}")
        return {}

    by_source: dict[str, list[Path]] = {}
    for subdir_name, source_label in PDF_DIRS.items():
        subdir = pdf_dir / subdir_name
        if not subdir.exists():
            continue
        pdfs = sorted(subdir.glob("*.pdf"))
        if pdfs:
            by_source[source_label] = pdfs
            print(f"  发现 [{source_label}]: {len(pdfs)} 个 PDF")

    # 根目录下的 PDF（无名目分类）
    root_pdfs = sorted(pdf_dir.glob("*.pdf"))
    if root_pdfs:
        existing = by_source.get("other", [])
        existing.extend(root_pdfs)
        by_source["other"] = existing

    return by_source


def pdfs_to_ingest_items(
    pdf_docs: list,
    source_label: str,
    doc_type: str,
) -> list[dict[str, Any]]:
    """将 PDFProcessor 的提取结果批量转为 IngestTextRequest 格式。"""
    processor = get_processor()
    all_items: list[dict[str, Any]] = []

    for doc in pdf_docs:
        items = processor.pdf_to_ingest_items(
            doc,
            source_label=source_label,
            doc_type=doc_type,
        )
        all_items.extend(items)
        print(
            f"    → {Path(doc.file_path).name}: "
            f"{len(doc.blocks)} 块 / {doc.word_count} 字"
        )

    return all_items


def determine_doc_type(
    filename: str,
    explicit_type: str | None,
) -> str:
    """根据文件名或显式参数推断 doc_type。"""
    if explicit_type:
        return explicit_type

    name_lower = filename.lower()
    if any(k in name_lower for k in ["guideline", "consensus", "共识", "指南", "recommendation", "guidance"]):
        return "clinical"
    if any(k in name_lower for k in ["drug", "label", "说明书", "prescribing", "smpc"]):
        return "clinical"
    if any(k in name_lower for k in ["textbook", "chapter", "专著", "教材", "教科书"]):
        return "clinical"
    return "literature"


# ---------------------------------------------------------------------------
# API 入库
# ---------------------------------------------------------------------------

def ingest_via_api(
    items: list[dict[str, Any]],
    base_url: str = "http://127.0.0.1:8010",
    batch_size: int = 20,
) -> tuple[int, int]:
    """
    通过 HTTP POST 将文本块批量入库。
    Returns: (ingested_count, failed_count)
    """
    try:
        import requests
    except ImportError:
        print("  ✗ 需要安装 requests: pip install requests")
        return 0, len(items)

    ingested = 0
    failed = 0

    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        for item in batch:
            try:
                resp = requests.post(
                    f"{base_url}/v1/ingest/text",
                    json=item,
                    timeout=30,
                )
                resp.raise_for_status()
                ingested += 1
            except requests.exceptions.ConnectionError:
                print(f"\n!!! 无法连接到 server ({base_url})")
                print("  → 请先启动: python run_server.py")
                return ingested, len(items) - ingested
            except Exception as e:
                print(f"  ✗ 入库失败 [{item.get('title', '')[:30]}]: {e}")
                failed += 1

        if (i + batch_size) % 100 == 0 or i + batch_size >= len(items):
            print(f"    ... 已提交 {min(i + batch_size, len(items))}/{len(items)}")

    return ingested, failed


def rebuild_knowledge_base_json(
    new_items: list[dict[str, Any]],
    kb_path: Path = KB_JSON,
    backup: bool = True,
) -> None:
    """
    将新的 PDF 文本块追加到 knowledge_base.json。
    旧文档（有 doc_id 重复的会被替换）。
    """
    if backup and kb_path.exists():
        import shutil
        shutil.copy(kb_path, KB_BACKUP)
        print(f"  ✓ 已备份旧文件 → {KB_BACKUP.name}")

    # 加载旧数据
    existing: list[dict[str, Any]] = []
    if kb_path.exists():
        try:
            existing = load_json(kb_path)
            print(f"  加载旧 KB: {len(existing)} 个文本块")
        except Exception:
            existing = []

    # 去重：旧 doc_id + 新 doc_id 相同则替换
    existing_ids: set[str] = {item.get("doc_id", "") for item in existing}
    merged: dict[str, dict] = {item["doc_id"]: item for item in existing}

    for item in new_items:
        merged[item["doc_id"]] = item

    result = list(merged.values())

    # 写入
    save_json(result, kb_path)
    print(f"  KB 快照已更新: {len(result)} 个文本块 (新增 {len(new_items)})")


# ---------------------------------------------------------------------------
# 核心流程
# ---------------------------------------------------------------------------

def extract_pdfs(
    pdf_dir: Path,
    doc_type_hint: str | None,
    output: Path | None,
) -> tuple[list, dict]:
    """
    扫描 PDF → 提取文本 → 返回 (pdf_docs, all_ingest_items)
    """
    processor = get_processor()
    all_docs: list = []
    all_items: list[dict[str, Any]] = []
    source_map: dict[str, list] = {}

    by_source = scan_pdfs(pdf_dir)
    if not by_source:
        print("  ✗ 未找到任何 PDF 文件")
        print(f"  → 请将 PDF 放入以下目录之一:")
        for subdir in PDF_DIRS:
            print(f"      {pdf_dir / subdir}/")
        return [], {}

    for source_label, pdf_paths in by_source.items():
        doc_type = determine_doc_type(
            pdf_paths[0].name, doc_type_hint
        )
        print(f"\n  [{source_label}] ({doc_type}) 提取中...")
        docs = processor.process_batch([str(p) for p in pdf_paths], verbose=True)
        items = pdfs_to_ingest_items(docs, source_label, doc_type)
        all_docs.extend(docs)
        all_items.extend(items)
        source_map[source_label] = docs

    if output:
        save_json(all_items, output)
        print(f"\n  提取完成: {len(all_items)} 个文本块 → {output}")

    return all_docs, all_items


def run_full_pipeline(
    pdf_dir: Path,
    doc_type_hint: str | None,
    update_kb: bool = True,
) -> None:
    """完整流程：提取 → 入库 → 更新 KB JSON。"""
    print("=" * 60)
    print(f"PDF 批量入库流程")
    print(f"PDF 目录: {pdf_dir}")
    print(f"doc_type: {doc_type_hint or 'auto'}")
    print("=" * 60)

    # Step 1: 提取
    print("\n[Step 1/3] 提取 PDF 文本...")
    _, all_items = extract_pdfs(pdf_dir, doc_type_hint, output=None)

    if not all_items:
        print("\n✗ 没有提取到任何文本块，流程终止")
        return

    print(f"\n  共提取 {len(all_items)} 个文本块")

    # Step 2: 入库
    print("\n[Step 2/3] 通过 HTTP API 入库...")
    print("  提示: 请确保 run_server.py 已在运行中！")
    ingested, failed = ingest_via_api(all_items)
    print(f"  入库结果: {ingested} 成功 / {failed} 失败")

    # Step 3: 更新 KB JSON
    if update_kb:
        print("\n[Step 3/3] 更新 data/knowledge_base.json ...")
        rebuild_knowledge_base_json(all_items)
    else:
        print("\n[Step 3/3] 跳过 KB JSON 更新（--no-update-kb）")

    print(f"\n{'='*60}")
    print(f"完成！")
    print(f"  提取文本块: {len(all_items)}")
    print(f"  成功入库: {ingested}")
    print(f"  失败: {failed}")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="PDF 文档批量入库工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/pdf_ingest.py                          # 扫描 data/pdfs/ 并入库
  python scripts/pdf_ingest.py --pdf-dir data/mypdfs/     # 指定目录
  python scripts/pdf_ingest.py --mode extract-only        # 仅提取，不入库
  python scripts/pdf_ingest.py --mode ingest-only --input data/my.json
  python scripts/pdf_ingest.py --mode rebuild-kb          # 重建 KB JSON
  python scripts/pdf_ingest.py --doc-type literature       # 统一类型

PDF 目录结构:
  data/pdfs/
  ├── guidelines/        ← 临床指南 / ILAE 共识声明 PDF
  ├── drug_labels/      ← 药物说明书 PDF (FDA/NMPA)
  ├── textbooks/         ← 神经病学专著章节 PDF
  └── protocols/        ← 诊疗规范 PDF
        """,
    )
    parser.add_argument(
        "--mode",
        choices=["full", "extract-only", "ingest-only", "rebuild-kb"],
        default="full",
        help="运行模式",
    )
    parser.add_argument(
        "--pdf-dir",
        type=Path,
        default=DEFAULT_PDF_DIR,
        help="PDF 所在目录",
    )
    parser.add_argument(
        "--doc-type",
        choices=["literature", "clinical"],
        default=None,
        help="统一指定 doc_type（不自动推断）",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="ingest-only 模式时指定的 JSON 文件路径",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="extract-only 模式时的输出 JSON 路径",
    )
    parser.add_argument(
        "--no-update-kb",
        action="store_true",
        help="入库后不更新 knowledge_base.json",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="API 入库批量大小",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.mode == "extract-only":
        print(f"[Extract Only] PDF 目录: {args.pdf_dir}")
        _, all_items = extract_pdfs(args.pdf_dir, args.doc_type, args.output)
        print(f"\n完成: {len(all_items)} 个文本块")

    elif args.mode == "ingest-only":
        if not args.input:
            print("✗ ingest-only 模式必须指定 --input")
            return
        print(f"[Ingest Only] 从 {args.input} 加载...")
        all_items = load_json(args.input)
        print(f"  加载了 {len(all_items)} 个文本块")
        ingested, failed = ingest_via_api(all_items, batch_size=args.batch_size)
        print(f"\n完成: {ingested} 成功 / {failed} 失败")

    elif args.mode == "rebuild-kb":
        print("[Rebuild KB JSON]")
        print("  扫描所有已知 KB 文件...")
        # 合并 crawled_epilepsy.json + pdf_extracted + 已有 KB
        sources = [
            ROOT / "data" / "crawled_epilepsy.json",
            ROOT / "data" / "pdf_extracted.json",
        ]
        all_items: list[dict[str, Any]] = []
        for fp in sources:
            if fp.exists():
                items = load_json(fp)
                if isinstance(items, list):
                    all_items.extend(items)
                    print(f"  + {fp.name}: {len(items)} 条")
        print(f"\n共收集 {len(all_items)} 个文本块")
        rebuild_knowledge_base_json(all_items)

    else:  # full
        run_full_pipeline(
            pdf_dir=args.pdf_dir,
            doc_type_hint=args.doc_type,
            update_kb=not args.no_update_kb,
        )


if __name__ == "__main__":
    main()
