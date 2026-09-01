#!/usr/bin/env python3
"""
test_dataset_answer_tool.py

用法：
  # 第1步：从 JSON 导出 Markdown 模板（供人工填写答案）
  python scripts/test_dataset_answer_tool.py \
      --input data/test_dataset_100.json \
      --output data/test_ground_truth.md

  # 第2步：将填好的 Markdown 转回 JSON（生成带 ground_truth 的数据集）
  python scripts/test_dataset_answer_tool.py \
      --input data/test_dataset_100.json \
      --answer-md data/test_ground_truth.md \
      --output data/test_dataset_with_answers.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ──────────────────────────────────────────────────────────────────────────────
# 导出 Markdown 模板
# ──────────────────────────────────────────────────────────────────────────────

ANSWER_PATTERN = re.compile(
    r"^## test_(\d+).*?\n"      # 标题行
    r"\*\*问题:\*\* (.*?)\n\n"   # 问题行
    r"\*\*答案:\*\*\s*\n(.*?)"   # 答案标记（content 在下面）
    r"(?=^## test_|\Z)",         # 下一个问题或文件末尾
    re.MULTILINE | re.DOTALL,
)


def export_markdown(samples: list[dict], output_path: str) -> None:
    lines = [
        "# 癫痫 QA 系统 - 测试集标准答案模板",
        "",
        "> 共 **75** 道题，请在每道题的 `**答案:**` 后填写对应的标准答案。",
        "> 格式：段落文本即可，不需要特殊格式。",
        "",
        "---\n",
    ]

    for sample in samples:
        qid = sample["id"]
        doc_type = sample["doc_type"]
        difficulty = sample["difficulty"]
        question = sample["question"]
        current_gt = sample.get("ground_truth", "").strip()
        existing = f"\n> 现有答案：{current_gt}" if current_gt else ""

        lines.append(f"## test_{qid.split('_')[1]} | {doc_type} | {difficulty}")
        lines.append(f"**问题:** {question}{existing}")
        lines.append("")
        lines.append("**答案:**")
        lines.append("（请在此填写标准答案）")
        lines.append("")
        lines.append("---\n")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"✓ Markdown 模板已导出：{output_path}")
    print(f"  共 {len(samples)} 道题，请补充答案后运行转换命令。")


# ──────────────────────────────────────────────────────────────────────────────
# 从 Markdown 解析答案
# ──────────────────────────────────────────────────────────────────────────────

def parse_answer_markdown(md_path: str) -> dict[str, str]:
    """返回 {test_XXXX: answer_text, ...}"""
    with open(md_path, encoding="utf-8") as f:
        content = f.read()

    answers = {}
    # 分割每个问题块
    blocks = re.split(r"^## test_(\d{4})", content, flags=re.MULTILINE)

    # blocks[0] = 前言文本, blocks[1]=id1, blocks[2]=内容1, blocks[3]=id2, blocks[4]=内容2 ...
    i = 1
    while i < len(blocks) - 1:
        qid = f"test_{blocks[i]}"
        body = blocks[i + 1]

        # 提取答案内容：在 "**答案:**" 行之后，到下一个 "---" 或文件末尾之前
        answer_match = re.search(
            r"^\*\*答案:\*\*\s*\n(.*?)(?=^---|\Z)",
            body,
            re.MULTILINE | re.DOTALL,
        )
        answer_text = answer_match.group(1).strip() if answer_match else ""
        answers[qid] = answer_text
        i += 2

    return answers


# ──────────────────────────────────────────────────────────────────────────────
# 合并：原始 JSON + Markdown 答案 → 新 JSON
# ──────────────────────────────────────────────────────────────────────────────

def merge_answers(
    input_json_path: str,
    answer_md_path: str,
    output_path: str,
) -> None:
    with open(input_json_path, encoding="utf-8") as f:
        dataset = json.load(f)

    samples = dataset.get("samples", dataset) if isinstance(dataset, dict) else dataset

    answers = parse_answer_markdown(answer_md_path)

    filled = 0
    empty = []
    for sample in samples:
        qid = sample["id"]
        if qid in answers:
            sample["ground_truth"] = answers[qid]
            if answers[qid] and answers[qid] != "（请在此填写标准答案）":
                filled += 1
            else:
                empty.append(qid)
        else:
            empty.append(qid)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)

    print(f"✓ 已生成带答案的数据集：{output_path}")
    print(f"  成功填充：{filled}/{len(samples)} 题")
    if empty:
        print(f"  未填写 / 未识别（将保留原值）：{', '.join(empty)}")


# ──────────────────────────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="测试集答案工具")
    parser.add_argument("--input", "-i", required=True,
                        help="原始 JSON 测试集路径")
    parser.add_argument("--output", "-o",
                        help="输出路径（导出 Markdown 时用）")
    parser.add_argument("--answer-md",
                        help="填好的 Markdown 答案文件路径（转换回 JSON 时用）")
    args = parser.parse_args()

    # 加载原始数据
    with open(args.input, encoding="utf-8") as f:
        raw = json.load(f)
    samples = raw.get("samples", raw) if isinstance(raw, dict) else raw

    if args.answer_md:
        # Markdown → JSON
        if not args.output:
            print("错误：--answer-md 模式需要指定 --output")
            sys.exit(1)
        merge_answers(args.input, args.answer_md, args.output)
    else:
        # JSON → Markdown
        out_path = args.output or args.input.replace(".json", "_answers.md")
        export_markdown(samples, out_path)


if __name__ == "__main__":
    main()
