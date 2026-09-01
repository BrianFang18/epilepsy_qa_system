#!/usr/bin/env python3
"""
vLLM 启动器 - 解决 WSL2 CUDA 检测问题

原理：在 torch 导入后，立即打补丁强制 torch.cuda.is_available() = True，
然后启动 vLLM。补丁只在 WSL2 + 无 GPU 时生效。

用法：
  python scripts/start_vllm.py --port 8000
  # 或直接运行：
  /home/brian/anaconda3/envs/vllm/bin/python scripts/start_vllm.py --port 8000
"""

from __future__ import annotations

import os
import sys

# ── WSL2 CUDA 补丁（必须在 torch 导入后、vllm 导入前执行）────────────────────
def _apply_wsl2_cuda_patch():
    """仅在 WSL2 + 无 GPU 时打补丁。"""
    if not os.path.exists("/proc/version"):
        return False
    try:
        with open("/proc/version", "r") as f:
            v = f.read().lower()
        if "microsoft" not in v and "wsl" not in v:
            return False
    except Exception:
        return False

    import torch
    if torch.cuda.is_available():
        print("[patch] GPU already available, skipping patch")
        return False

    print("[patch] WSL2 detected, applying CUDA patch...")

    class _FakeDevProps:
        total_mem = 16 * (1024 ** 3)
        major = 8
        minor = 9
        multi_processor_count = 82

    GPU_NAME = "NVIDIA GeForce RTX (WSL2)"

    torch.cuda.is_available = lambda: True
    torch.cuda.device_count = lambda: 1
    torch.cuda.get_device_name = lambda i: GPU_NAME
    torch.cuda.get_device_properties = lambda i: _FakeDevProps()
    torch.cuda.current_device = lambda: 0

    if hasattr(torch._C, "_cuda_getDeviceCount"):
        torch._C._cuda_getDeviceCount = lambda: 1

    try:
        import pynvml
        pynvml.nvmlInit = lambda: None
        pynvml.nvmlDeviceGetCount = lambda: 1
        pynvml.nvmlDeviceGetName = lambda h: GPU_NAME.encode()
        pynvml.nvmlDeviceGetHandleByIndex = lambda i: i
        pynvml.nvmlShutdown = lambda: None
        print("[patch] pynvml patched")
    except ImportError:
        print("[patch] pynvml not found, skipping")

    print(f"[patch] Done: is_available={torch.cuda.is_available()}, "
          f"count={torch.cuda.device_count()}, GPU={torch.cuda.get_device_name(0)}")
    return True


# ── 主入口 ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # 应用补丁
    _apply_wsl2_cuda_patch()

    # 将剩余命令行参数传递给 vllm
    sys.argv = ["start_vllm.py"] + sys.argv[1:]

    from vllm.entrypoints.openai.api_server import make_arg_parser
    import uvicorn

    parser = make_arg_parser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args, _ = parser.parse_known_args()

    config = uvicorn.Config(
        "vllm.entrypoints.openai.api_server:app",
        host=args.host,
        port=args.port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    server.run()
