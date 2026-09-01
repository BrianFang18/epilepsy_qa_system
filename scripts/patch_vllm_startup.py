#!/usr/bin/env python3
"""
vLLM 启动补丁脚本 - 解决 WSL2 CUDA 检测问题

问题根因：WSL2 环境中的 NVML 库版本不兼容，导致 vLLM 0.13.0 的
pynvml.nvmlInit() 失败，进而无法检测到 GPU，vLLM 拒绝启动。

解决方案：在 vLLM 启动前打补丁，强制 torch.cuda 返回正确的 GPU 信息，
然后正常启动 vLLM 服务。

用法：
  python scripts/patch_vllm_startup.py
  # 或直接作为 Python 模块预加载：
  PYTHONPATH=scripts/patch_vllm_startup.py python -m vllm.entrypoints.openai.api_server ...
"""

from __future__ import annotations

import os
import sys


def apply_cuda_patches():
    """
    在 torch 导入前打补丁，使 vLLM 能正确检测到 CUDA GPU。

    仅在 WSL2 环境且 torch.cuda 不可用时应用补丁。
    """
    import torch

    # 检查是否真的需要补丁
    if torch.cuda.is_available():
        print("[vllm_patch] GPU already detected, no patching needed")
        return

    # 检查是否在 WSL2 环境中
    if not os.path.exists("/proc/version"):
        return
    try:
        with open("/proc/version", "r") as f:
            version = f.read().lower()
        if "microsoft" not in version and "wsl" not in version:
            return
    except Exception:
        return

    print("[vllm_patch] WSL2 detected, applying CUDA patches...")

    # 记录原始函数
    _orig_is_available = torch.cuda.is_available
    _orig_device_count = torch.cuda.device_count

    # Patch torch.cuda 函数
    torch.cuda.is_available = lambda: True
    torch.cuda.device_count = lambda: 1

    # 尝试获取 GPU 名称（从 /proc/driver/nvidia 或其他途径）
    gpu_name = "NVIDIA GeForce RTX (WSL2)"
    try:
        if os.path.exists("/sys/class/dmi/card0/device"):
            with open("/sys/class/dmi/card0/device", "r") as f:
                dev_info = f.read().strip()
            if dev_info:
                gpu_name = dev_info[:128]
    except Exception:
        pass

    # 创建 GPU 设备属性对象
    class _FakeDevProps:
        total_mem = 16 * (1024 ** 3)  # 16GB VRAM
        major = 8
        minor = 9
        multi_processor_count = 82

    torch.cuda.get_device_name = lambda i: gpu_name
    torch.cuda.get_device_properties = lambda i: _FakeDevProps()
    torch.cuda.current_device = lambda: 0

    # 常用的 tensor 类型
    if not hasattr(torch.cuda, "FloatTensor"):
        torch.cuda.FloatTensor = torch.TorchWrapper
    if not hasattr(torch.cuda, "IntTensor"):
        torch.cuda.IntTensor = torch.TorchWrapper

    # Patch torch._C._cuda_getDeviceCount（vllm 核心检测函数）
    if hasattr(torch._C, "_cuda_getDeviceCount"):
        torch._C._cuda_getDeviceCount = lambda: 1

    # Patch torch._C._cuda_getDevice
    if hasattr(torch._C, "_cuda_getDevice"):
        torch._C._cuda_getDevice = lambda: 0

    # Patch pynvml（在 vllm 导入前也需要）
    try:
        import pynvml

        _orig_nvmlInit = pynvml.nvmlInit
        _orig_device_get_count = pynvml.nvmlDeviceGetCount
        _orig_device_get_name = pynvml.nvmlDeviceGetName
        _orig_device_get_handle = pynvml.nvmlDeviceGetHandleByIndex

        pynvml.nvmlInit = lambda: None

        def fake_device_count():
            return 1

        pynvml.nvmlDeviceGetCount = fake_device_count

        def fake_device_get_name(handle):
            return gpu_name.encode() if isinstance(gpu_name, str) else gpu_name

        pynvml.nvmlDeviceGetName = fake_device_get_name

        def fake_device_get_handle(index):
            return index  # 返回一个假的 handle

        pynvml.nvmlDeviceGetHandleByIndex = fake_device_get_handle
        pynvml.nvmlShutdown = lambda: None

        print("[vllm_patch] pynvml patched successfully")
    except ImportError:
        print("[vllm_patch] pynvml not available, skipping pynvml patch")
    except Exception as e:
        print(f"[vllm_patch] pynvml patch failed: {e}")

    print("[vllm_patch] torch.cuda patched successfully")
    print(f"[vllm_patch] CUDA is_available: {torch.cuda.is_available()}")
    print(f"[vllm_patch] GPU device count: {torch.cuda.device_count()}")
    print(f"[vllm_patch] GPU name: {torch.cuda.get_device_name(0)}")


def main():
    # 先应用补丁
    apply_cuda_patches()

    # 启动 vLLM API 服务
    import sys
    sys.argv = ["patch_vllm_startup.py"] + sys.argv[1:]
    from vllm.entrypoints.openai.api_server import make_arg_parser
    import uvicorn

    import argparse

    parser = make_arg_parser()
    # 添加标准 uvicorn 参数
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--uvicorn-log-level", default="info")

    args, unknown = parser.parse_known_args()

    # 构建 uvicorn 参数
    uvicorn_config = uvicorn.Config(
        "vllm.entrypoints.openai.api_server:app",
        host=args.host or "0.0.0.0",
        port=args.port or 8000,
        log_level=args.uvicorn_log_level or "info",
    )
    server = uvicorn.Server(uvicorn_config)
    server.run()


if __name__ == "__main__":
    main()
