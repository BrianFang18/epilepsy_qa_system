#!/usr/bin/env python3
"""
测试数据集生成脚本

生成结构化的癫痫问答测试集，包含：
- literature 类：文献指南相关问题
- clinical 类：临床实践相关问题
- both 类：需要综合两类知识的问题

使用方式：
  # 生成100条小规模测试集（验证用）
  python scripts/generate_test_dataset.py --count 100 --output data/test_dataset_100.json

  # 生成2000条完整测试集
  python scripts/generate_test_dataset.py --count 2000 --output data/test_dataset_2000.json

  # 生成100条 + 同时生成 ground_truth 填写模板
  python scripts/generate_test_dataset.py --count 100 --output data/test_dataset_100.json --with-template
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ============================================================
# 测试集模板定义
# ============================================================

LITERATURE_TEMPLATES = {
    "药物适应症": [
        {"template": "{drug}的适应症有哪些？",
         "slots": {"drug": ["左乙拉西坦", "丙戊酸钠", "卡马西平", "拉莫三嗪", "奥卡西平", "托吡酯", "氯巴占", "苯巴比妥"]}},
        {"template": "{drug}对哪种类型的癫痫综合征最有效？",
         "slots": {"drug": ["左乙拉西坦", "丙戊酸钠", "拉莫三嗪", "卡马西平", "奥卡西平"]}},
        {"template": "根据指南，{drug}的推荐初始剂量是多少？",
         "slots": {"drug": ["左乙拉西坦", "丙戊酸钠", "拉莫三嗪", "托吡酯"]}},
        {"template": "{drug}有哪些常见的不良反应？",
         "slots": {"drug": ["丙戊酸钠", "卡马西平", "苯妥英钠", "托吡酯", "左乙拉西坦"]}},
        {"template": "{drug}与其他抗癫痫药物的相互作用有哪些？",
         "slots": {"drug": ["卡马西平", "丙戊酸钠", "苯巴比妥", "拉莫三嗪"]}},
        {"template": "根据{year}年{org}指南，{drug}的推荐剂量是多少？",
         "slots": {"year": ["2022", "2023", "2024"], "org": ["ILAE", "AAN", "中国抗癫痫协会"],
                   "drug": ["左乙拉西坦", "丙戊酸钠", "拉莫三嗪"]}},
    ],
    "发作类型": [
        {"template": "癫痫持续状态的定义是什么？"},
        {"template": "全面性发作和部分性发作的主要区别是什么？"},
        {"template": "失神发作的典型临床表现是什么？"},
        {"template": "肌阵挛发作的特点有哪些？"},
        {"template": "癫痫发作的ILAE 2017分类体系是什么？"},
        {"template": "{type}发作的典型脑电图特征是什么？",
         "slots": {"type": ["全面性", "部分性", "局灶性"]}},
        {"template": "自动症常见于哪种癫痫发作类型？"},
        {"template": "癫痫先兆具体包括哪些症状？"},
    ],
    "诊疗指南": [
        {"template": "难治性癫痫的定义标准是什么？"},
        {"template": "癫痫手术治疗的适应症有哪些？"},
        {"template": "生酮饮食治疗癫痫的适应症和机制是什么？"},
        {"template": "VNS（迷走神经刺激）治疗的适应人群是哪些？"},
        {"template": "癫痫患者术前评估的标准流程包括哪些内容？"},
        {"template": "癫痫共患焦虑抑郁的筛查和管理建议是什么？"},
        {"template": "新诊断癫痫患者的药物治疗流程是什么？"},
        {"template": "癫痫治疗的目标是什么？如何评估疗效？"},
    ],
}

CLINICAL_TEMPLATES = {
    "症状评估": [
        {"template": "如何判断患者是否为首次癫痫发作？"},
        {"template": "夜间发作和日间发作在临床上有什么区别？"},
        {"template": "发热相关性癫痫的临床特点是什么？"},
        {"template": "如何鉴别癫痫发作和心因性非癫痫发作？"},
        {"template": "癫痫发作前的先兆症状有哪些？"},
        {"template": "患者出现发作性愣神，鉴别诊断包括哪些？"},
        {"template": "Todd麻痹与癫痫发作的关联是什么？"},
        {"template": "癫痫发作后的发作后朦胧状态持续多久是正常的？"},
    ],
    "用药管理": [
        {"template": "患者{duration}内出现{frequency}次夜间发作，是否需要调整{drug}剂量？",
         "slots": {"duration": ["一周", "两周", "一个月"],
                   "frequency": ["1-2", "3-4", "5次以上"],
                   "drug": ["左乙拉西坦", "丙戊酸钠"]}},
        {"template": "癫痫患者自行停药有哪些风险？"},
        {"template": "抗癫痫药物的血药浓度监测有什么临床意义？"},
        {"template": "患者漏服一次抗癫痫药物应该怎么办？"},
        {"template": "抗癫痫药物需要多长时间才能达到稳态血药浓度？"},
        {"template": "{age}岁患者首次癫痫发作后，应该做哪些检查？",
         "slots": {"age": ["18", "35", "45", "60", "75"]}},
        {"template": "育龄期女性使用丙戊酸钠需要注意什么？"},
        {"template": "左乙拉西坦需要逐渐停药吗？"},
        {"template": "抗癫痫药物的最佳服用时间是什么时候？"},
    ],
    "急症处理": [
        {"template": "癫痫发作时家属应该采取哪些紧急措施？"},
        {"template": "癫痫持续状态的家庭急救流程是什么？"},
        {"template": "患者在院外出现抽搐，家属应如何判断是否需要叫急救车？"},
        {"template": "癫痫发作时能否将物体塞入患者口中？"},
        {"template": "癫痫患者出现持续抽搐超过5分钟应该如何处理？"},
        {"template": "癫痫持续状态的院前处理流程是什么？"},
        {"template": "癫痫大发作时按压人中是否正确？"},
    ],
    "随访管理": [
        {"template": "癫痫患者的随访周期应该是多久？"},
        {"template": "癫痫患者需要定期监测哪些实验室指标？"},
        {"template": "如何指导患者正确记录癫痫日记？"},
        {"template": "癫痫患者驾驶有哪些法律规定？"},
        {"template": "癫痫患者可以从事哪些工作？有哪些职业禁忌？"},
        {"template": "癫痫患者游泳时需要注意什么？"},
        {"template": "癫痫患者的睡眠管理建议是什么？"},
    ],
}

BOTH_TEMPLATES = {
    "方案选择": [
        {"template": "生育期女性癫痫患者应如何选择抗癫痫药物？"},
        {"template": "老年癫痫患者的用药选择有哪些特殊考虑？"},
        {"template": "儿童癫痫和成人癫痫在用药上有什么区别？"},
        {"template": "肝功能异常的癫痫患者如何选择抗癫痫药物？"},
        {"template": "肾功能不全的癫痫患者用药需要注意什么？"},
        {"template": "癫痫患者怀孕期间抗癫痫药物如何调整？"},
        {"template": "合并抑郁症的癫痫患者如何选择抗癫痫药物？"},
        {"template": "认知功能障碍的癫痫患者用药需要注意什么？"},
    ],
    "综合评估": [
        {"template": "难治性癫痫患者有哪些替代治疗方案？各有什么优劣？"},
        {"template": "癫痫患者手术治疗的适应症和禁忌症是什么？"},
        {"template": "如何评估癫痫患者的生活质量？有哪些核心指标？"},
        {"template": "抗癫痫药物联合治疗的原则是什么？"},
        {"template": "癫痫患者能否接种疫苗？需要注意什么？"},
        {"template": "癫痫与认知功能障碍的关系是什么？如何评估？"},
        {"template": "癫痫患者的心理社会支持包括哪些方面？"},
        {"template": "如何对癫痫患者进行健康教育？"},
    ],
}

# 所有药物列表
ALL_DRUGS = [
    "左乙拉西坦", "丙戊酸钠", "卡马西平", "拉莫三嗪",
    "奥卡西平", "托吡酯", "氯巴占", "苯巴比妥",
    "苯妥英钠", "加巴喷丁", "普瑞巴林", "卢非酰胺",
    "氨己烯酸", "扑米酮", "乙琥胺", "司替戊醇",
]


def generate_samples_from_group(
    group: dict[str, list],
    target_count: int,
    doc_type: str,
) -> list[dict]:
    """从模板组生成测试样本"""
    samples = []
    group_keys = list(group.keys())
    per_category = max(1, target_count // len(group_keys))

    for category, templates in group.items():
        category_count = 0

        for tmpl_def in templates:
            if category_count >= per_category:
                break

            template_text = tmpl_def["template"]
            slots = tmpl_def.get("slots", {})

            if not slots:
                sample_id = len(samples) + 1
                samples.append({
                    "id": f"{doc_type}_{sample_id:04d}",
                    "question": template_text,
                    "doc_type": doc_type,
                    "category": category,
                    "difficulty": _infer_difficulty(template_text),
                    "ground_truth": "",
                    "retrieved_contexts": [],
                    "keywords": _extract_keywords(template_text),
                })
                category_count += 1
            else:
                keys = list(slots.keys())
                values = [slots[k] for k in keys]
                all_combos = list(itertools.product(*values))
                random.shuffle(all_combos)

                for combo in all_combos:
                    if category_count >= per_category:
                        break

                    question = template_text.format(**dict(zip(keys, combo)))
                    sample_id = len(samples) + 1
                    samples.append({
                        "id": f"{doc_type}_{sample_id:04d}",
                        "question": question,
                        "doc_type": doc_type,
                        "category": category,
                        "difficulty": _infer_difficulty(question),
                        "ground_truth": "",
                        "retrieved_contexts": [],
                        "keywords": _extract_keywords(question),
                    })
                    category_count += 1

    return samples


def _infer_difficulty(text: str) -> str:
    """根据问题关键词推断难度"""
    hard_keywords = ["标准", "定义", "机制", "指南", "禁忌", "治疗方案", "评估", "适应症"]
    medium_keywords = ["如何", "哪些", "什么", "区别", "特点", "注意", "关联"]
    easy_keywords = ["是", "有", "能不能", "能否"]

    for kw in hard_keywords:
        if kw in text:
            return "hard"
    for kw in medium_keywords:
        if kw in text:
            return "medium"
    return "easy"


def _extract_keywords(text: str) -> list[str]:
    """提取问题中的关键词"""
    keywords = []
    for drug in ALL_DRUGS:
        if drug in text:
            keywords.append(drug)
    return keywords


def generate_dataset(n_samples: int) -> list[dict]:
    """生成完整测试集"""
    distribution = {"literature": 0.35, "clinical": 0.35, "both": 0.30}
    targets = {}
    remaining = n_samples

    for i, (dtype, ratio) in enumerate(distribution.items()):
        if i == len(distribution) - 1:
            targets[dtype] = remaining
        else:
            targets[dtype] = int(n_samples * ratio)
            remaining -= targets[dtype]

    lit_samples = generate_samples_from_group(LITERATURE_TEMPLATES, targets["literature"], "literature")
    cli_samples = generate_samples_from_group(CLINICAL_TEMPLATES, targets["clinical"], "clinical")
    both_samples = generate_samples_from_group(BOTH_TEMPLATES, targets["both"], "both")

    all_samples = lit_samples + cli_samples + both_samples
    random.shuffle(all_samples)

    for i, s in enumerate(all_samples):
        s["id"] = f"test_{i + 1:04d}"

    return all_samples


def save_ground_truth_template(samples: list[dict], output_path: str) -> None:
    """生成 ground_truth 填写模板（Markdown 格式）"""
    lines = [
        "# 癫痫问答测试集 Ground Truth 模板\n",
        f"**生成时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**样本总数**: {len(samples)}\n",
        "---\n",
    ]

    grouped: dict = {}
    for s in samples:
        dtype = s["doc_type"]
        grouped.setdefault(dtype, []).append(s)

    for dtype, items in grouped.items():
        lines.append(f"\n## {dtype.upper()} 类 ({len(items)}条)\n")
        for s in items:
            lines.append(f"### [{s['id']}] {s['category']} - {s['difficulty']}\n")
            lines.append(f"**问题**: {s['question']}\n")
            kw = s.get("keywords") or []
            lines.append(f"**关键词**: {', '.join(kw) if kw else '（无）'}\n")
            lines.append("**Ground Truth**: \n")
            lines.append("<!-- 请在此处填写专家标准答案 -->\n")
            lines.append("---\n")

    tpl_path = output_path.replace(".json", "_ground_truth_template.md")
    Path(tpl_path).parent.mkdir(parents=True, exist_ok=True)
    with open(tpl_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Ground Truth 填写模板已生成: {tpl_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="生成癫痫问答测试集")
    parser.add_argument("--count", "-n", type=int, default=100,
                        help="生成样本数量 (默认: 100)")
    parser.add_argument("--output", "-o", type=str, default="data/test_dataset.json",
                        help="输出文件路径 (默认: data/test_dataset.json)")
    parser.add_argument("--seed", "-s", type=int, default=42,
                        help="随机种子 (默认: 42，保证可复现)")
    parser.add_argument("--with-template", "-t", action="store_true",
                        help="同时生成 Ground Truth 填写模板")
    parser.add_argument("--dry-run", "-d", action="store_true",
                        help="仅预览，不保存文件")

    args = parser.parse_args()
    random.seed(args.seed)

    print("=" * 60)
    print(f"生成测试集: {args.count} 条样本 | 种子: {args.seed}")
    print("=" * 60)

    samples = generate_dataset(args.count)

    dtype_dist = Counter(s["doc_type"] for s in samples)
    diff_dist = Counter(s["difficulty"] for s in samples)
    cat_dist = Counter(s["category"] for s in samples)

    print(f"\n总样本: {len(samples)}")
    print(f"\n按意图: " + "  ".join(f"{k}={v}({v/len(samples)*100:.0f}%)" for k, v in dtype_dist.items()))
    print(f"按难度: " + "  ".join(f"{k}={v}({v/len(samples)*100:.0f}%)" for k, v in diff_dist.items()))

    if args.dry_run:
        print("\n[预览前5条]:")
        for s in samples[:5]:
            print(f"  [{s['id']}] [{s['doc_type']:<10}] {s['question'][:45]}...")
        return

    dataset = {
        "metadata": {
            "total": len(samples),
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "seed": args.seed,
            "doc_type_distribution": dict(dtype_dist),
            "difficulty_distribution": dict(diff_dist),
            "category_distribution": dict(cat_dist),
        },
        "samples": samples,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)

    print(f"\n数据集已保存: {output_path}")

    if args.with_template:
        save_ground_truth_template(samples, args.output)

    print("\n" + "-" * 60)
    print("下一步:")
    print(f"  python scripts/run_full_evaluation.py --input {args.output}")
    print("-" * 60)


if __name__ == "__main__":
    main()
