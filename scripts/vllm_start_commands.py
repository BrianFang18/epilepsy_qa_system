#!/usr/bin/env python3
"""
vLLM 服务启动命令模板
用于快速部署不同量化版本的 Qwen 模型

使用方式：
  python scripts/vllm_start_commands.py

或直接复制命令到终端运行
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


VLLM_COMMANDS = {
    # ============================================================
    # Qwen2.5-1.5B 系列 (适合快速验证)
    # ============================================================
    "qwen2.5-1.5b-fp16": {
        "description": "Qwen2.5-1.5B FP16 基线版本，适合快速验证全链路",
        "model": "Qwen/Qwen2.5-1.5B-Instruct",
        "served_name": "qwen2.5-1.5b-fp16",
        "port": 8000,
        "quantization": None,
        "tp_size": 1,
        "gpu_mem": "约 3GB VRAM (FP16)",
    },

    "qwen2.5-1.5b-int4": {
        "description": "Qwen2.5-1.5B GPTQ INT4 量化版，显存占用减半",
        "model": "TheBloke/Qwen2.5-1.5B-Instruct-GPTQ",
        "served_name": "qwen2.5-1.5b-int4",
        "port": 8000,
        "quantization": "gptq",
        "tp_size": 1,
        "gpu_mem": "约 1.5GB VRAM (INT4)",
    },

    # ============================================================
    # Qwen2.5-7B 系列 (性价比之选)
    # ============================================================
    "qwen2.5-7b-fp16": {
        "description": "Qwen2.5-7B FP16 版本，需要约 14GB VRAM",
        "model": "Qwen/Qwen2.5-7B-Instruct",
        "served_name": "qwen2.5-7b-fp16",
        "port": 8000,
        "quantization": None,
        "tp_size": 1,
        "gpu_mem": "约 14GB VRAM (FP16)",
    },

    "qwen2.5-7b-int4": {
        "description": "Qwen2.5-7B INT4 量化版，显存占用减少约 60%",
        "model": "TheBloke/Qwen2.5-7B-Instruct-GPTQ",
        "served_name": "qwen2.5-7b-int4",
        "port": 8000,
        "quantization": "gptq",
        "tp_size": 1,
        "gpu_mem": "约 4-5GB VRAM (INT4)",
    },

    # ============================================================
    # Qwen2.5-72B 系列 (生产环境主模型)
    # ============================================================
    "qwen2.5-72b-int4-tp2": {
        "description": "Qwen2.5-72B INT4 量化 + 张量并行2卡，需约 2x24GB VRAM",
        "model": "TheBloke/Qwen2.5-72B-Instruct-GPTQ",
        "served_name": "qwen2.5-72b-int4",
        "port": 8000,
        "quantization": "gptq",
        "tp_size": 2,
        "gpu_mem": "约 48GB VRAM 总计 (2x24GB, INT4)",
    },

    "qwen2.5-72b-int4-tp4": {
        "description": "Qwen2.5-72B INT4 量化 + 张量并行4卡，每卡约 20GB",
        "model": "TheBloke/Qwen2.5-72B-Instruct-GPTQ",
        "served_name": "qwen2.5-72b-int4",
        "port": 8000,
        "quantization": "gptq",
        "tp_size": 4,
        "gpu_mem": "约 80GB VRAM 总计 (4x20GB, INT4)",
    },
}


def build_command(config: dict) -> str:
    """构建 vLLM 启动命令"""
    cmd_parts = [
        "python -m vllm.entrypoints.openai.api_server",
        f"--model {config['model']}",
        f"--served-model-name {config['served_name']}",
        f"--host 0.0.0.0",
        f"--port {config['port']}",
        f"--tensor-parallel-size {config['tp_size']}",
        "--max-model-len 8192",
        "--gpu-memory-utilization 0.90",
    ]

    if config.get("quantization"):
        cmd_parts.append(f"--quantization {config['quantization']}")

    return " \\\n    ".join(cmd_parts)


def main() -> None:
    print("=" * 70)
    print("vLLM 服务启动命令模板")
    print("=" * 70)
    print()

    for name, config in VLLM_COMMANDS.items():
        print(f"--- {name.upper()} ---")
        print(f"描述: {config['description']}")
        print(f"显存: {config['gpu_mem']}")
        print()
        print("命令:")
        print(build_command(config))
        print()
        print("=" * 70)
        print()

    print("\n使用方式:")
    print("1. 复制对应命令到终端运行")
    print("2. 或修改 .env 中的 LLM_MODEL 为 served_name 的值")
    print("3. 确保 .env 中 LLM_API_BASE=http://127.0.0.1:8000/v1")
    print()


if __name__ == "__main__":
    main()
