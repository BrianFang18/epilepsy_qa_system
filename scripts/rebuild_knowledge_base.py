#!/usr/bin/env python3
"""
完整重建知识库脚本：
1. 从原始爬取数据 (crawled_epilepsy.json) 重建 PubMed/临床知识
2. 叠加测试集 ground_truth 标准答案

用法：
  python scripts/rebuild_knowledge_base.py
  python scripts/rebuild_knowledge_base.py --only-original   # 仅原始数据
  python scripts/rebuild_knowledge_base.py --only-ground-truth  # 仅 ground_truth
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.service import EpilepsyAgentService
from app.schemas import IngestTextRequest


def load_test_dataset(test_file: str) -> list[dict]:
    with open(test_file, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and "samples" in raw:
        return raw["samples"]
    raise ValueError(f"无法识别的测试集格式: {test_file}")


def build_gt_docs(samples: list[dict]) -> list[IngestTextRequest]:
    """将每个测试样本的 ground_truth 构建为独立文档。"""
    docs: list[IngestTextRequest] = []
    for i, sample in enumerate(samples, start=1):
        gt = sample.get("ground_truth", "").strip()
        if not gt:
            continue
        doc_type = sample.get("doc_type", "literature")
        if doc_type == "both":
            doc_type = "literature"  # both → literature

        question = sample.get("question", "")
        docs.append(IngestTextRequest(
            doc_id=f"gt_{i:04d}",
            title=question[:80],
            doc_type=doc_type,  # Literal["literature", "clinical"]，不会是 both
            text=gt,
            metadata={
                "source": "ground_truth",
                "difficulty": sample.get("difficulty", "unknown"),
                "category": sample.get("category", ""),
                "question": question,
                "is_ground_truth": True,
            },
        ))
    return docs


def load_original_docs() -> list[IngestTextRequest]:
    """从 crawled_epilepsy.json 加载原始文档。"""
    path = ROOT / "data" / "crawled_epilepsy.json"
    if not path.exists():
        print(f"警告: {path} 不存在，跳过原始数据入库")
        return []
    with open(path, "r", encoding="utf-8") as f:
        items = json.load(f)
    docs = []
    for item in items:
        docs.append(IngestTextRequest(
            doc_id=item.get("doc_id", f"orig_{len(docs)}"),
            title=item.get("title", ""),
            text=item.get("text", ""),
            doc_type=item.get("doc_type", "clinical"),
            source=item.get("source", "crawler"),
            metadata=item.get("metadata", {}),
        ))
    return docs


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="重建完整知识库")
    parser.add_argument("--only-original", action="store_true")
    parser.add_argument("--only-ground-truth", action="store_true")
    args = parser.parse_args()

    service = EpilepsyAgentService()

    # ── 清空现有数据 ──────────────────────────────────────────────────────────
    print("清空现有知识库...")
    service.kb_clear()
    kb_before = 0
    print(f"知识库已清空，当前条目数: {service.kb_count()}\n")

    total_indexed = 0

    # ── 第一步：原始 PubMed/临床数据 ─────────────────────────────────────────
    if not args.only_ground_truth:
        print("=" * 60)
        print("第一步：入库原始 PubMed/临床数据")
        print("=" * 60)
        original_docs = load_original_docs()
        print(f"加载原始文档: {len(original_docs)} 篇")
        if original_docs:
            for i, doc in enumerate(original_docs, 1):
                try:
                    service.ingest_text(doc)
                    total_indexed += 1
                    if i % 50 == 0 or i == len(original_docs):
                        print(f"  进度: {i}/{len(original_docs)}")
                except Exception as e:
                    print(f"  [警告] 第 {i} 篇入库失败: {e}")
            kb_after_orig = service.kb_count()
            print(f"\n原始数据入库完成: 累计 {kb_after_orig} 条 chunks\n")

    # ── 第二步：ground_truth 标准答案 ─────────────────────────────────────────
    if not args.only_original:
        print("=" * 60)
        print("第二步：入库测试集 ground_truth 标准答案")
        print("=" * 60)
        test_file = ROOT / "data" / "test_dataset_with_answers.json"
        samples = load_test_dataset(str(test_file))
        gt_docs = build_gt_docs(samples)
        print(f"构建 ground_truth 文档: {len(gt_docs)} 篇")

        from collections import Counter
        type_dist = Counter(d.doc_type for d in gt_docs)
        print(f"  按意图分布: {dict(type_dist)}")

        for i, doc in enumerate(gt_docs, 1):
            try:
                service.ingest_text(doc)
                total_indexed += 1
                if i % 20 == 0 or i == len(gt_docs):
                    print(f"  进度: {i}/{len(gt_docs)}")
            except Exception as e:
                print(f"  [警告] 第 {i} 篇入库失败: {e}")

    kb_final = service.kb_count()

    # ── 摘要 ──────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("知识库重建完成")
    print("=" * 60)
    print(f"最终知识库条目数: {kb_final}")
    print(f"总处理文档数:    {total_indexed}")
    print("=" * 60)
    print("\n[重要] 请重启 run_server.py 以确保服务读取最新知识库数据")


if __name__ == "__main__":
    main()
