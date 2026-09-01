#!/usr/bin/env python3
"""
量化对比基准测试脚本

测量并对比 FP16 和 INT4 (GPTQ) 量化在不同模型上的：
1. GPU 显存占用
2. 推理延迟 (p50 / p95 / p99)
3. 吞吐量 (tokens/s)

使用方式：
  python scripts/quantization_benchmark.py

注意：需要先分别以 FP16 和 INT4 模式启动 vLLM 服务
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx


def get_gpu_memory_info() -> Optional[tuple[float, float]]:
    """获取 GPU 显存使用情况，返回 (used_gb, total_gb)"""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True,
        )
        used_str, total_str = result.stdout.strip().split(",")
        return float(used_str) / 1024, float(total_str) / 1024
    except Exception:
        return None


def check_vllm_running(port: int = 8000) -> bool:
    """检查 vLLM 服务是否运行"""
    try:
        response = httpx.get(f"http://127.0.0.1:{port}/v1/models", timeout=5.0)
        return response.status_code == 200
    except Exception:
        return False


def get_model_name(port: int = 8000) -> Optional[str]:
    """获取当前服务的模型名称"""
    try:
        response = httpx.get(f"http://127.0.0.1:{port}/v1/models", timeout=5.0)
        data = response.json()
        if data.get("data"):
            return data["data"][0].get("id", "unknown")
    except Exception:
        pass
    return None


def benchmark_inference(
    model_name: str,
    prompt: str,
    port: int = 8000,
    n_runs: int = 20,
    max_tokens: int = 256,
    temperature: float = 0.0,
) -> dict:
    """
    基准测试：测量单次推理的延迟和吞吐量
    """
    latencies = []
    first_token_latencies = []
    tokens_counts = []

    for i in range(n_runs):
        try:
            req_start = time.perf_counter()

            response = httpx.post(
                f"http://127.0.0.1:{port}/v1/completions",
                json={
                    "model": model_name,
                    "prompt": prompt,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
                timeout=120.0,
            )

            elapsed_ms = (time.perf_counter() - req_start) * 1000
            latencies.append(elapsed_ms)

            if response.status_code == 200:
                data = response.json()
                # 估算 token 数（用字符数近似）
                output_text = data.get("choices", [{}])[0].get("text", "")
                tokens_counts.append(len(output_text) // 4)
                # 如果有 usage 信息则用实际值
                usage = data.get("usage", {})
                if usage.get("completion_tokens"):
                    tokens_counts[-1] = usage["completion_tokens"]

        except Exception as e:
            print(f"    请求 {i+1} 失败: {e}")
            latencies.append(0)

    # 过滤掉失败的请求
    valid_latencies = [l for l in latencies if l > 0]

    if not valid_latencies:
        return {
            "p50": 0, "p95": 0, "p99": 0, "avg": 0,
            "throughput": 0, "valid_runs": 0,
        }

    valid_latencies.sort()
    avg_tokens = sum(tokens_counts) / max(len(tokens_counts), 1)
    avg_latency = sum(valid_latencies) / len(valid_latencies)

    return {
        "p50": valid_latencies[len(valid_latencies) // 2],
        "p95": valid_latencies[int(len(valid_latencies) * 0.95)] if len(valid_latencies) >= 20 else valid_latencies[-1],
        "p99": valid_latencies[int(len(valid_latencies) * 0.99)] if len(valid_latencies) >= 100 else valid_latencies[-1],
        "avg": avg_latency,
        "throughput": (avg_tokens / avg_latency * 1000) if avg_latency > 0 else 0,
        "valid_runs": len(valid_latencies),
    }


# ============================================================
# 测试用例集：覆盖医学领域核心问题类型
# ============================================================

TEST_PROMPTS = [
    {
        "category": "药物适应症",
        "text": "左乙拉西坦的一线适应症有哪些？",
    },
    {
        "category": "发作类型",
        "text": "癫痫持续状态的定义是什么？",
    },
    {
        "category": "检查诊断",
        "text": "首次癫痫发作后需要做哪些检查？",
    },
    {
        "category": "用药方案",
        "text": "育龄期女性癫痫患者如何选择抗癫痫药物？",
    },
    {
        "category": "急症处理",
        "text": "癫痫发作时的急性处理流程是什么？",
    },
]


def run_benchmark(port: int = 8000) -> dict:
    """运行完整基准测试"""
    gpu_info = get_gpu_memory_info()
    model_name = get_model_name(port)

    print(f"当前模型: {model_name}")
    print(f"GPU 显存: {gpu_info[0]:.1f}GB / {gpu_info[1]:.1f}GB" if gpu_info else "GPU 信息不可用")
    print(f"测试用例数: {len(TEST_PROMPTS)}")
    print()

    results = {
        "model": model_name,
        "gpu_memory_used_gb": gpu_info[0] if gpu_info else None,
        "gpu_memory_total_gb": gpu_info[1] if gpu_info else None,
        "prompts": [],
        "summary": {},
    }

    all_latencies = []

    for i, item in enumerate(TEST_PROMPTS):
        print(f"[{i+1}/{len(TEST_PROMPTS)}] 测试: {item['category']} - {item['text'][:30]}...")

        bench = benchmark_inference(
            model_name=model_name or "unknown",
            prompt=item["text"],
            port=port,
            n_runs=20,
        )

        results["prompts"].append({
            "category": item["category"],
            "question": item["text"],
            "benchmark": bench,
            "p50": bench["p50"],
            "p95": bench["p95"],
            "avg": bench["avg"],
            "throughput": bench["throughput"],
        })

        all_latencies.append(bench["avg"])

        print(f"    p50={bench['p50']:.1f}ms  p95={bench['p95']:.1f}ms  "
              f"avg={bench['avg']:.1f}ms  throughput={bench['throughput']:.1f}tok/s")

    # 汇总统计
    lat_sorted = sorted(all_latencies)
    mid = len(lat_sorted) // 2
    results["summary"] = {
        "avg_p50": lat_sorted[mid],
        "avg_p95": sum(p["p95"] for p in results["prompts"]) / len(results["prompts"]),
        "avg_latency": sum(all_latencies) / len(all_latencies),
        "avg_throughput": sum(p["throughput"] for p in results["prompts"]) / len(results["prompts"]),
        "samples": len(results["prompts"]),
    }

    return results


def compare_results(result_fp16: dict, result_int4: dict) -> None:
    """对比 FP16 和 INT4 的结果"""
    print("\n" + "=" * 70)
    print("量化对比分析")
    print("=" * 70)

    fp16_mem = result_fp16.get("gpu_memory_used_gb") or 0
    int4_mem = result_int4.get("gpu_memory_used_gb") or 0

    fp16_latency = result_fp16["summary"]["avg_latency"]
    int4_latency = result_int4["summary"]["avg_latency"]

    fp16_tp = result_fp16["summary"]["avg_throughput"]
    int4_tp = result_int4["summary"]["avg_throughput"]

    print()
    print(f"{'指标':<25} {'FP16':<15} {'INT4':<15} {'变化':<15}")
    print("-" * 70)
    print(f"{'显存占用 (GB)':<25} {fp16_mem:<15.2f} {int4_mem:<15.2f} "
          f"{(fp16_mem - int4_mem) / fp16_mem * 100:.1f}% 节省" if fp16_mem > 0 else "")
    print(f"{'平均延迟 (ms)':<25} {fp16_latency:<15.1f} {int4_latency:<15.1f} "
          f"{fp16_latency / int4_latency:.2f}x {'快' if int4_latency < fp16_latency else '慢'}")
    print(f"{'吞吐量 (tok/s)':<25} {fp16_tp:<15.1f} {int4_tp:<15.1f} "
          f"{int4_tp / fp16_tp:.2f}x {'快' if int4_tp > fp16_tp else '慢'}")
    print()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="vLLM 量化对比基准测试")
    parser.add_argument("--port", type=int, default=8000, help="vLLM 服务端口 (默认 8000)")
    parser.add_argument("--mode", type=str, choices=["single", "compare"], default="single",
                        help="single: 只测当前服务; compare: 需要分别测试后对比")
    parser.add_argument("--fp16-result", type=str, help="FP16 结果文件路径 (compare 模式)")
    parser.add_argument("--int4-result", type=str, help="INT4 结果文件路径 (compare 模式)")
    parser.add_argument("--output", type=str, default="benchmark_result.json",
                        help="结果输出文件")

    args = parser.parse_args()

    if args.mode == "single":
        # 单次测试模式
        print("=" * 70)
        print("单次基准测试")
        print("=" * 70)

        if not check_vllm_running(args.port):
            print(f"\n错误: vLLM 服务未运行于端口 {args.port}")
            print("请先启动 vLLM 服务：")
            print("  python -m vllm.entrypoints.openai.api_server --model Qwen/Qwen2.5-1.5B-Instruct ...")
            sys.exit(1)

        result = run_benchmark(port=args.port)

        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        print(f"\n结果已保存至: {args.output}")
        print(f"平均延迟: {result['summary']['avg_latency']:.1f}ms")
        print(f"平均吞吐量: {result['summary']['avg_throughput']:.1f} tok/s")

    elif args.mode == "compare":
        # 对比模式
        if not args.fp16_result or not args.int4_result:
            print("错误: compare 模式需要指定 --fp16-result 和 --int4-result")
            sys.exit(1)

        with open(args.fp16_result, "r", encoding="utf-8") as f:
            fp16_data = json.load(f)

        with open(args.int4_result, "r", encoding="utf-8") as f:
            int4_data = json.load(f)

        compare_results(fp16_data, int4_data)


if __name__ == "__main__":
    main()
