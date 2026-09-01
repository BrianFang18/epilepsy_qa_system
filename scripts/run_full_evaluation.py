#!/usr/bin/env python3
"""
确定性词法双轨评估脚本：上下文 token 重叠 + 答案 token Jaccard

评估指标：
- Context Precision/Recall：确定性 token 重叠指标
- Answer token Jaccard：生成答案与参考答案之间的词法相似度

探索性词法组合 = α × Context Overlap Mean + (1-α) × Answer Token Jaccard
该组合只是探索性算术结果，不是事实正确性、临床质量或整体质量分数。

使用方式：
  # 评估全部测试集
  python scripts/run_full_evaluation.py

  # 评估指定文件
  python scripts/run_full_evaluation.py --input test_dataset_100.json --output eval_result.json
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.utils import simple_tokenize  # noqa: E402


class HybridEvaluator:
    """确定性上下文 token 重叠 + 答案 token Jaccard 评估器。

    所有 RAG 检索和 LLM 生成都走 server 的 /v1/ask 接口，
    避免本地进程创建独立空 store。答案 token Jaccard 与加权组合
    仅用于探索性词法比较，不代表事实正确性、临床质量或整体质量。
    """

    def __init__(
        self, alpha: float = 0.7, verbose: bool = True, api_base: str = "http://127.0.0.1:8010"
    ):
        """
        Args:
            alpha: Context Overlap Mean 权重；(1-alpha) 为答案 token Jaccard 权重
            verbose: 是否打印详细过程
            api_base: server HTTP 地址
        """
        self.alpha = alpha
        self.verbose = verbose
        self.api_base = api_base.rstrip("/")
        self._session = requests.Session()

    def answer_token_jaccard(self, generated: str, ground_truth: str) -> float:
        """计算生成答案与参考答案的 token Jaccard 词法相似度。

        Jaccard = |A ∩ B| / |A ∪ B|。该值仅描述 token 集合重叠，
        不是事实正确性、临床质量或整体质量分数。
        """
        gen_tokens = set(simple_tokenize(generated))
        gt_tokens = set(simple_tokenize(ground_truth))

        if not gen_tokens or not gt_tokens:
            return 0.0

        intersection = len(gen_tokens & gt_tokens)
        union = len(gen_tokens | gt_tokens)
        return intersection / union

    def _ask_server(self, question: str) -> dict[str, Any]:
        """调 /v1/ask 接口，返回 AskResponse dict（已序列化）。"""
        resp = self._session.post(
            f"{self.api_base}/v1/ask",
            json={"question": question, "with_trace": False},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()

    def _evaluate_context_overlap(
        self,
        question: str,
        ground_truth: str,
        retrieved_contexts: list[str],
        generated_response: str,
    ) -> dict[str, Any]:
        """调用确定性词法评估；下方 legacy URL 仅为兼容保留。"""
        sample = {
            "question": question,
            "ground_truth": ground_truth,
            "retrieved_contexts": retrieved_contexts,
            "response": generated_response,
        }
        # /v1/eval/ragas is a legacy compatibility URL only. The current
        # backend is deterministic lexical token overlap.
        resp = self._session.post(
            f"{self.api_base}/v1/eval/ragas",
            json={"samples": [sample]},
            timeout=30,
        )
        resp.raise_for_status()
        evaluation_payload = resp.json()
        if not isinstance(evaluation_payload, dict):
            raise ValueError("评估响应必须是 JSON object")

        details = evaluation_payload.get("details")
        if not isinstance(details, dict):
            raise ValueError("评估响应缺少 details 元数据")

        expected_details = {
            "backend": "deterministic_lexical",
            "metric_version": "token_overlap_v1",
            "aggregation": "macro_average",
        }
        mismatches = {
            key: {"expected": expected, "actual": details.get(key)}
            for key, expected in expected_details.items()
            if details.get(key) != expected
        }
        if mismatches:
            raise ValueError(f"评估后端元数据不匹配: {mismatches}")

        metrics = evaluation_payload.get("metrics")
        if not isinstance(metrics, dict):
            raise ValueError("评估响应缺少 metrics")

        metric_values: dict[str, float] = {}
        for metric_name in ("context_precision", "context_recall"):
            value = metrics.get(metric_name)
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError(f"评估响应的 {metric_name} 无效: {value!r}")
            metric_values[metric_name] = float(value)

        return {
            **metric_values,
            "evaluation_details": {key: details[key] for key in expected_details},
        }

    def evaluate_single(
        self,
        question: str,
        ground_truth: str,
        difficulty: str,
    ) -> dict[str, Any]:
        """评估单条样本（全部走 HTTP API）。"""

        # ── DEBUG 打印 ──────────────────────────────────────────────────────────
        print("\n" + "=" * 70)
        print("[DEBUG] question :", question)
        print("[DEBUG] ground_truth :", ground_truth)
        # ── END DEBUG ───────────────────────────────────────────────────────────

        # Step 1: 调 server 获取 RAG 检索上下文 + LLM 回答
        start = time.perf_counter()
        ask_result = self._ask_server(question)
        latency_ms = (time.perf_counter() - start) * 1000

        generated = ask_result["answer"]
        intent = ask_result["intent"]
        sources = ask_result.get("sources", [])

        # 真实检索到的 context（来自 server 的 retriever）
        real_contexts = [s["text"] for s in sources]

        # ── DEBUG 打印检索结果 ──────────────────────────────────────────────────
        print("[DEBUG] real_contexts count :", len(real_contexts))
        for i, ctx in enumerate(real_contexts, 1):
            print(f"[DEBUG]   context[{i}] :", ctx[:150] + ("..." if len(ctx) > 150 else ""))
        # ── END DEBUG ──────────────────────────────────────────────────────────

        # Step 2: 确定性词法上下文重叠评估（通过 legacy 兼容 URL）
        context_metrics = self._evaluate_context_overlap(
            question,
            ground_truth,
            real_contexts,
            generated,
        )
        context_precision = context_metrics["context_precision"]
        context_recall = context_metrics["context_recall"]
        context_overlap_mean = 0.5 * context_precision + 0.5 * context_recall

        # ── DEBUG 打印生成答案 ──────────────────────────────────────────────────
        print("[DEBUG] generated     :", generated[:300] + ("..." if len(generated) > 300 else ""))
        print("[DEBUG] answer_token_jaccard_calc :")
        gen_tokens = set(simple_tokenize(generated))
        gt_tokens = set(simple_tokenize(ground_truth))
        print(f"              gen_tokens ({len(gen_tokens)}): {sorted(gen_tokens)}")
        print(f"              gt_tokens  ({len(gt_tokens)}): {sorted(gt_tokens)}")
        intersection = gen_tokens & gt_tokens
        print(f"              intersection ({len(intersection)}): {sorted(intersection)}")
        # ── END DEBUG ──────────────────────────────────────────────────────────

        # Step 3: 答案与参考答案的 token Jaccard（仅词法相似度）
        answer_token_jaccard = self.answer_token_jaccard(generated, ground_truth)

        # Step 4: 探索性算术组合；不是事实、临床或整体质量分数
        exploratory_lexical_composite = (
            self.alpha * context_overlap_mean + (1 - self.alpha) * answer_token_jaccard
        )

        # ── DEBUG 打印指标拆解 ──────────────────────────────────────────────────
        print(
            f"[DEBUG] context_precision={context_precision:.4f}  "
            f"context_recall={context_recall:.4f}  "
            f"context_overlap_mean={context_overlap_mean:.4f}"
        )
        print(
            f"[DEBUG] answer_token_jaccard={answer_token_jaccard:.4f}  "
            f"exploratory_lexical_composite={exploratory_lexical_composite:.4f}"
        )
        print(f"[DEBUG] sources_count ={len(sources)}  intent={intent}")
        print("=" * 70 + "\n")
        # ── END DEBUG ──────────────────────────────────────────────────────────

        return {
            "question": question,
            "generated_answer": generated,
            "ground_truth": ground_truth,
            "intent": intent,
            "difficulty": difficulty,
            "sources_count": len(sources),
            "latency_ms": latency_ms,
            "context_precision": context_precision,
            "context_recall": context_recall,
            "context_overlap_mean": context_overlap_mean,
            "answer_token_jaccard": answer_token_jaccard,
            "exploratory_lexical_composite": exploratory_lexical_composite,
            "evaluation_details": context_metrics["evaluation_details"],
        }

    def evaluate_dataset(
        self,
        test_file: str,
        output_file: str = "eval_results.json",
        max_samples: int | None = None,
    ) -> dict[str, Any]:
        """批量评估测试集"""
        with open(test_file, encoding="utf-8") as f:
            raw = json.load(f)

        # 支持两种格式：纯列表 或 {"samples": [...], "metadata": {...}}
        if isinstance(raw, list):
            test_data = raw
        elif isinstance(raw, dict) and "samples" in raw:
            test_data = raw["samples"]
        else:
            raise ValueError(
                f"测试集格式无法识别，期望 list 或 dict{{samples, metadata}}，实际: {type(raw).__name__}"
            )

        if max_samples:
            test_data = test_data[:max_samples]

        results: list[dict[str, Any]] = []
        for i, item in enumerate(test_data):
            question = item["question"]
            ground_truth = item.get("ground_truth", "")
            difficulty = item.get("difficulty", "unknown")

            if self.verbose:
                print(
                    f"[{i+1}/{len(test_data)}] "
                    f"[{item.get('doc_type', 'unknown'):<10}] "
                    f"{question[:40]}..."
                )

            try:
                result = self.evaluate_single(
                    question=question,
                    ground_truth=ground_truth,
                    difficulty=difficulty,
                )
                results.append(result)

                if self.verbose:
                    print(
                        f"    → intent={result['intent']:<10} "
                        f"context_overlap_mean={result['context_overlap_mean']:.2%} "
                        f"answer_token_jaccard={result['answer_token_jaccard']:.2%} "
                        f"exploratory_lexical_composite="
                        f"{result['exploratory_lexical_composite']:.2%} "
                        f"({result['latency_ms']:.0f}ms)"
                    )

            except Exception as e:
                print(f"    ✗ 评估失败: {e}")
                results.append(
                    {
                        "question": question,
                        "difficulty": difficulty,
                        "evaluation_error": str(e),
                    }
                )

        # 失败结果单独计数，不参与任何指标平均值。
        valid_results = [r for r in results if "evaluation_error" not in r]
        failed_results = [r for r in results if "evaluation_error" in r]

        if not valid_results:
            summary = {
                "total_samples": len(test_data),
                "valid_samples": 0,
                "failed_samples": len(failed_results),
                "context_overlap_weight": self.alpha,
                "metrics": {},
                "by_doc_type": {},
                "by_difficulty": {},
            }
            print("\n警告: 没有有效评估结果；失败样本未折算为 0")
            full_output = {
                "summary": summary,
                "results": results,
            }
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(full_output, f, indent=2, ensure_ascii=False)
            print(f"\n详细结果已保存至: {output_file}")
            return summary

        # 总体统计
        context_overlap_means = [r["context_overlap_mean"] for r in valid_results]
        answer_token_jaccards = [r["answer_token_jaccard"] for r in valid_results]
        exploratory_composites = [r["exploratory_lexical_composite"] for r in valid_results]
        latencies = [r["latency_ms"] for r in valid_results]

        summary = {
            "total_samples": len(test_data),
            "valid_samples": len(valid_results),
            "failed_samples": len(failed_results),
            "context_overlap_weight": self.alpha,
            "metrics": {
                "context_overlap_mean_avg": (
                    sum(context_overlap_means) / len(context_overlap_means)
                ),
                "context_precision_avg": (
                    sum(r["context_precision"] for r in valid_results) / len(valid_results)
                ),
                "context_recall_avg": (
                    sum(r["context_recall"] for r in valid_results) / len(valid_results)
                ),
                "answer_token_jaccard_avg": (
                    sum(answer_token_jaccards) / len(answer_token_jaccards)
                ),
                "exploratory_lexical_composite_avg": (
                    sum(exploratory_composites) / len(exploratory_composites)
                ),
                "latency_avg_ms": sum(latencies) / len(latencies),
                "latency_p95_ms": sorted(latencies)[int(len(latencies) * 0.95)],
            },
        }

        # 分维度统计
        summary["by_doc_type"] = {}
        for doc_type in ["literature", "clinical", "both"]:
            type_results = [r for r in valid_results if r.get("intent") == doc_type]
            if type_results:
                summary["by_doc_type"][doc_type] = {
                    "count": len(type_results),
                    "context_overlap_mean_avg": (
                        sum(r["context_overlap_mean"] for r in type_results) / len(type_results)
                    ),
                    "answer_token_jaccard_avg": (
                        sum(r["answer_token_jaccard"] for r in type_results) / len(type_results)
                    ),
                    "exploratory_lexical_composite_avg": (
                        sum(r["exploratory_lexical_composite"] for r in type_results)
                        / len(type_results)
                    ),
                }

        # 每条成功结果自带 difficulty，避免过滤失败结果后发生位置错配。
        summary["by_difficulty"] = {}
        for result in valid_results:
            difficulty = result["difficulty"]
            if difficulty not in summary["by_difficulty"]:
                summary["by_difficulty"][difficulty] = {
                    "exploratory_lexical_composites": [],
                    "count": 0,
                }
            summary["by_difficulty"][difficulty]["exploratory_lexical_composites"].append(
                result["exploratory_lexical_composite"]
            )
            summary["by_difficulty"][difficulty]["count"] += 1

        for difficulty_stats in summary["by_difficulty"].values():
            composites = difficulty_stats.pop("exploratory_lexical_composites")
            difficulty_stats["exploratory_lexical_composite_avg"] = sum(composites) / len(
                composites
            )

        # 打印汇总
        print("\n" + "=" * 70)
        print("确定性词法评估结果汇总")
        print("=" * 70)
        print(f"样本总数:     {summary['total_samples']}")
        print(f"有效评估:     {summary['valid_samples']}")
        print(f"失败数量:     {summary['failed_samples']}")
        print()
        print(
            "Context Overlap Mean 平均值: " f"{summary['metrics']['context_overlap_mean_avg']:.2%}"
        )
        print("  - Context Precision: " f"{summary['metrics']['context_precision_avg']:.2%}")
        print("  - Context Recall:    " f"{summary['metrics']['context_recall_avg']:.2%}")
        print(
            "答案 token Jaccard 平均值（仅词法相似度）: "
            f"{summary['metrics']['answer_token_jaccard_avg']:.2%}"
        )
        print(
            f"探索性词法组合 (α={self.alpha}): "
            f"{summary['metrics']['exploratory_lexical_composite_avg']:.2%}"
        )
        print()
        print(
            f"平均响应延迟: {summary['metrics']['latency_avg_ms']:.0f}ms "
            f"(p95: {summary['metrics']['latency_p95_ms']:.0f}ms)"
        )
        print()
        print("按意图分布:")
        for doc_type, stats in summary.get("by_doc_type", {}).items():
            print(
                f"  {doc_type:<12} n={stats['count']:<4} "
                f"context_overlap_mean={stats['context_overlap_mean_avg']:.2%} "
                f"answer_token_jaccard={stats['answer_token_jaccard_avg']:.2%} "
                f"exploratory_lexical_composite="
                f"{stats['exploratory_lexical_composite_avg']:.2%}"
            )
        print()
        print("按难度分布:")
        for diff, stats in summary.get("by_difficulty", {}).items():
            print(
                f"  {diff:<8} n={stats['count']:<4} "
                f"exploratory_lexical_composite_avg="
                f"{stats['exploratory_lexical_composite_avg']:.2%}"
            )

        print("=" * 70)
        print(
            "\n★ 探索性词法组合均值: "
            f"{summary['metrics']['exploratory_lexical_composite_avg']:.2%}"
        )
        print("  仅为词法指标的算术组合，不是事实正确性、临床质量或整体质量分数。")
        print("=" * 70)

        # 保存结果
        full_output = {
            "summary": summary,
            "results": results,
        }
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(full_output, f, indent=2, ensure_ascii=False)

        print(f"\n详细结果已保存至: {output_file}")

        return summary


def generate_test_dataset(output_file: str = "test_dataset.json", n_samples: int = 100):
    """
    生成测试数据集模板

    实际使用时，建议：
    1. 先用此脚本生成基础模板
    2. 人工补充 ground_truth 字段（专家撰写标准答案）
    3. 可用 LLM 辅助生成，但需人工审核
    """
    templates = [
        # ==================== literature 类 ====================
        {
            "doc_type": "literature",
            "category": "药物适应症",
            "difficulty": "easy",
            "templates": [
                "左乙拉西坦的适应症有哪些？",
                "丙戊酸钠在癫痫治疗中的一线地位是什么？",
                "卡马西平适用于哪种类型的癫痫？",
                "拉莫三嗪对哪些癫痫综合征有效？",
            ],
        },
        {
            "doc_type": "literature",
            "category": "发作类型",
            "difficulty": "medium",
            "templates": [
                "癫痫持续状态的定义和分类标准是什么？",
                "全面性发作和部分性发作的主要区别是什么？",
                "失神发作的典型脑电图特征有哪些？",
            ],
        },
        {
            "doc_type": "literature",
            "category": "诊疗指南",
            "difficulty": "hard",
            "templates": [
                "根据最新ILAE指南，难治性癫痫的定义标准是什么？",
                "癫痫患者术前评估的标准流程包括哪些内容？",
                "生酮饮食治疗癫痫的循证医学依据是什么？",
            ],
        },
        # ==================== clinical 类 ====================
        {
            "doc_type": "clinical",
            "category": "症状评估",
            "difficulty": "easy",
            "templates": [
                "如何判断患者是否为首次癫痫发作？",
                "夜间发作和日间发作在临床上有什么区别？",
                "发热相关性癫痫的临床特点是什么？",
            ],
        },
        {
            "doc_type": "clinical",
            "category": "用药管理",
            "difficulty": "medium",
            "templates": [
                "患者服用左乙拉西坦期间出现情绪低落，应该如何处理？",
                "癫痫患者自行停药有哪些风险？",
                "抗癫痫药物的血药浓度监测有什么临床意义？",
            ],
        },
        {
            "doc_type": "clinical",
            "category": "急症处理",
            "difficulty": "hard",
            "templates": [
                "癫痫发作时家属应该采取哪些紧急措施？",
                "癫痫持续状态的家庭急救流程是什么？",
                "患者在院外出现抽搐，家属应如何判断是否需要叫急救车？",
            ],
        },
        # ==================== both 类 ====================
        {
            "doc_type": "both",
            "category": "方案选择",
            "difficulty": "medium",
            "templates": [
                "生育期女性癫痫患者应如何选择抗癫痫药物？",
                "老年癫痫患者的用药选择有哪些特殊考虑？",
                "儿童癫痫和成人癫痫在用药上有什么区别？",
            ],
        },
        {
            "doc_type": "both",
            "category": "综合评估",
            "difficulty": "hard",
            "templates": [
                "难治性癫痫患者有哪些替代治疗方案？各有什么优劣？",
                "癫痫患者手术治疗的适应症和禁忌症是什么？",
                "如何评估癫痫患者的生活质量？有哪些核心指标？",
            ],
        },
    ]

    samples = []
    sample_id = 0

    # 均匀分布采样
    while len(samples) < n_samples:
        for template_group in templates:
            if len(samples) >= n_samples:
                break

            group_templates = template_group["templates"]
            # 每组至少抽 1 条，最多抽 3 条
            n_to_sample = min(3, n_samples - len(samples), len(group_templates))
            sampled = random.sample(group_templates, n_to_sample)

            for question in sampled:
                if len(samples) >= n_samples:
                    break

                sample_id += 1
                samples.append(
                    {
                        "id": f"test_{sample_id:04d}",
                        "question": question,
                        "ground_truth": "",  # 需要专家撰写
                        "doc_type": template_group["doc_type"],
                        "category": template_group["category"],
                        "difficulty": template_group["difficulty"],
                        "retrieved_contexts": [],  # 由系统检索填充
                        "keywords": [],  # 用于 Jaccard 评估的关键词
                    }
                )

    dataset = {
        "metadata": {
            "total": len(samples),
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "note": "ground_truth 字段需要专家撰写，retrieved_contexts 由系统填充",
        },
        "samples": samples,
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)

    print(f"测试数据集已生成: {output_file}")
    print(f"总样本数: {len(samples)}")

    # 统计分布
    from collections import Counter

    doc_type_dist = Counter(s["doc_type"] for s in samples)
    difficulty_dist = Counter(s["difficulty"] for s in samples)

    print("\n分布统计:")
    print("  按意图:", dict(doc_type_dist))
    print("  按难度:", dict(difficulty_dist))

    return dataset


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="确定性词法上下文重叠 + 探索性答案 token Jaccard 评估"
    )
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        default="./data/test_dataset_with_answers.json",
        help="测试集文件路径 (默认: test_dataset.json)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="./data/eval_with_answers.json",
        help="评估结果输出路径 (默认: eval_results.json)",
    )
    parser.add_argument(
        "--alpha",
        "-a",
        type=float,
        default=0.7,
        help=(
            "Context Overlap Mean 权重 (默认: 0.7；其余权重用于答案 " "token Jaccard 词法相似度)"
        ),
    )
    parser.add_argument(
        "--max-samples", "-m", type=int, default=None, help="最多评估样本数 (默认: 全部)"
    )
    parser.add_argument(
        "--generate", "-g", type=int, metavar="N", help="生成 N 条测试集模板（不执行评估）"
    )

    args = parser.parse_args()

    if args.generate:
        # 生成模式
        output_file = f"test_dataset_{args.generate}.json"
        generate_test_dataset(output_file=output_file, n_samples=args.generate)
        print("\n提示: 请补充 ground_truth 字段后，使用以下命令运行评估:")
        print(f"  python scripts/run_full_evaluation.py --input {output_file}")
        return

    # 评估模式
    input_file = Path(args.input)
    if not input_file.exists():
        print(f"\n错误: 找不到测试集文件: {input_file}")
        print("使用 --generate 参数生成测试集模板：")
        print("  python scripts/run_full_evaluation.py --generate 100")
        sys.exit(1)

    print("=" * 70)
    print("确定性词法上下文重叠 + 探索性答案 token Jaccard 评估")
    print(f"测试集: {input_file}")
    print(f"输出:   {args.output}")
    print(
        f"Context Overlap Mean 权重 α = {args.alpha} " f"(答案 token Jaccard 权重 = {1-args.alpha})"
    )
    print("=" * 70)

    evaluator = HybridEvaluator(alpha=args.alpha, verbose=True)
    evaluator.evaluate_dataset(
        test_file=str(input_file),
        output_file=args.output,
        max_samples=args.max_samples,
    )


if __name__ == "__main__":
    main()
