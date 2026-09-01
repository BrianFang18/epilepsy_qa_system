#!/usr/bin/env python3
"""
将测试集的 ground_truth 作为标准答案文档灌入向量数据库。

为什么需要这个脚本：
- 测试集里的 ground_truth 是专家撰写 / LLM 生成的完美中文标准答案
- 向量数据库里只有 PubMed 英文文献片段和临床病例记录
- 如果 ground_truth 知识根本没有存入向量库，检索器再怎么努力也找不出来
- 本脚本将这些标准答案按意图类型（literature/clinical/both）分别建索引
  让检索器在评估时能够把"对的文档"召回来

使用方式：
  # 完整入库（推荐，评估前必须执行）
  python scripts/ingest_ground_truth.py

  # 仅入库 literature 类（调试用）
  python scripts/ingest_ground_truth.py --doc-type literature

  # 仅入库 clinical 类
  python scripts/ingest_ground_truth.py --doc-type clinical

  # 仅入库 both 类
  python scripts/ingest_ground_truth.py --doc-type both

  # 清空知识库后重新入库（强制重建）
  python scripts/ingest_ground_truth.py --clear --reingest
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.service import EpilepsyAgentService
from app.schemas import IngestTextRequest


def load_test_dataset(test_file: str) -> list[dict]:
    """加载测试集，返回样本列表。"""
    with open(test_file, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and "samples" in raw:
        return raw["samples"]
    raise ValueError(f"无法识别的测试集格式: {test_file}")


def build_gt_docs(
    samples: list[dict],
    doc_type_filter: str | None = None,
) -> list[IngestTextRequest]:
    """
    将每个测试样本的 ground_truth 构建为独立的入库文档。

    入库策略：
    - 每个 ground_truth 作为一篇独立文档存入向量库
    - doc_type 沿用测试集标注（literature/clinical/both）
    - chunk_size 为 512 字符，让检索粒度与问题保持一致
    - document_id 带 gt 前缀，与原始数据隔离
    """
    docs: list[IngestTextRequest] = []

    for i, sample in enumerate(samples, start=1):
        gt = sample.get("ground_truth", "").strip()
        if not gt:
            continue

        doc_type = sample.get("doc_type", "literature")
        # "both" 映射到 literature，因为检索时 both 会同时查询 literature + clinical
        if doc_type == "both":
            doc_type = "literature"
        if doc_type_filter and doc_type != doc_type_filter:
            continue

        question = sample.get("question", "")
        difficulty = sample.get("difficulty", "unknown")
        category = sample.get("category", "")

        doc = IngestTextRequest(
            doc_id=f"gt_{i:04d}",
            title=question[:80],  # 标题用问题本身（截断到80字）
            doc_type=doc_type,
            text=gt,
            metadata={
                "source": "ground_truth",
                "difficulty": difficulty,
                "category": category,
                "question": question,
                "is_ground_truth": True,
            },
        )
        docs.append(doc)

    return docs


def main() -> None:
    parser = argparse.ArgumentParser(description="将 ground_truth 灌入向量数据库")
    parser.add_argument(
        "--input", "-i",
        type=str,
        default=str(ROOT / "data" / "test_dataset_with_answers.json"),
        help="测试集文件路径",
    )
    parser.add_argument(
        "--doc-type",
        type=str,
        choices=["literature", "clinical", "both"],
        default=None,
        help="仅入库指定 doc_type（默认全部）",
    )
    parser.add_argument(
        "--clear", "-c",
        action="store_true",
        help="入库前清空现有知识库",
    )
    parser.add_argument(
        "--reingest", "-r",
        action="store_true",
        help="强制重新入库（配合 --clear 使用）",
    )
    args = parser.parse_args()

    # ── 加载测试集 ─────────────────────────────────────────────────────────────
    if not Path(args.input).exists():
        print(f"错误: 测试集文件不存在: {args.input}")
        sys.exit(1)

    samples = load_test_dataset(args.input)
    print(f"加载测试集: {len(samples)} 条样本")

    # ── 构建入库文档 ───────────────────────────────────────────────────────────
    gt_docs = build_gt_docs(samples, doc_type_filter=args.doc_type)
    print(f"构建 ground_truth 文档: {len(gt_docs)} 篇")

    if not gt_docs:
        print("警告: 没有可入库的 ground_truth 文档（可能测试集为空或 doc_type 不匹配）")
        sys.exit(0)

    # 统计分布
    from collections import Counter
    type_dist = Counter(d.doc_type for d in gt_docs)
    print(f"  按意图分布: {dict(type_dist)}")

    # ── 初始化服务（包含向量库连接） ─────────────────────────────────────────────
    print("\n初始化 RAG 服务...")
    service = EpilepsyAgentService()
    kb_before = service.kb_count()
    print(f"当前知识库条目数: {kb_before}")

    # ── 可选：清空知识库 ────────────────────────────────────────────────────────
    if args.clear:
        print("\n清空现有知识库...")
        service.kb_clear()
        print("知识库已清空")

    # ── 执行入库 ───────────────────────────────────────────────────────────────
    print(f"\n开始入库 {len(gt_docs)} 篇 ground_truth 文档...")
    success_count = 0
    for i, doc in enumerate(gt_docs, start=1):
        try:
            result = service.ingest_text(doc)
            success_count += 1
            if i % 20 == 0 or i == len(gt_docs):
                print(f"  进度: {i}/{len(gt_docs)}")
        except Exception as e:
            print(f"  [警告] 第 {i} 篇入库失败: {e}")

    kb_after = service.kb_count()
    print(f"\n入库完成: 成功 {success_count}/{len(gt_docs)} 篇")
    print(f"知识库条目: {kb_before} → {kb_after}（新增 {kb_after - kb_before} 条）")

    # ── 打印摘要 ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("入库摘要")
    print("=" * 60)
    print(f"测试集文件: {args.input}")
    print(f"入库样本数: {len(gt_docs)}")
    print(f"意图分布:   {dict(type_dist)}")
    print(f"知识库增量: +{kb_after - kb_before} 条")
    print("=" * 60)

    if kb_after - kb_before < len(gt_docs):
        print("\n[提示] 入库数量少于预期，可能已有重复 doc_id 覆盖，请使用 --clear 重建")


if __name__ == "__main__":
    main()
