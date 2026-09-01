#!/usr/bin/env python3
"""
本地 HuggingFace 推理 API 服务（替代 vLLM）

当 vLLM 因 WSL2 GPU 检测问题无法启动时，本服务通过 HuggingFace Transformers
直接加载 Qwen2.5-1.5B 模型，提供 OpenAI 兼容的 /v1/chat/completions 接口。

用法：
  python scripts/start_hf_api.py --port 8000
  # 然后在 .env 中设置：
  # LLM_API_BASE=http://127.0.0.1:8000/v1
  # LLM_MODEL=Qwen2.5-1.5B
"""

from __future__ import annotations

import os
import sys
import argparse
import uvicorn
from pathlib import Path
import threading
from typing import Any, Optional

# ── WSL2 CUDA 补丁（必须在 torch 导入前执行）─────────────────────────────────
def _apply_wsl2_cuda_patch():
    """在 torch 导入后打补丁，使推理能在 WSL2 GPU 上运行。"""
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
        print("[patch] GPU already available")
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
    torch.cuda.FloatTensor = lambda x: torch.tensor(x, dtype=torch.float32, device='cuda') if isinstance(x, list) else x
    torch.cuda.LongTensor = lambda x: torch.tensor(x, dtype=torch.long, device='cuda') if isinstance(x, list) else x
    torch.cuda.IntTensor = lambda x: torch.tensor(x, dtype=torch.int32, device='cuda') if isinstance(x, list) else x

    if hasattr(torch._C, "_cuda_getDeviceCount"):
        torch._C._cuda_getDeviceCount = lambda: 1
    if hasattr(torch._C, "_cuda_setDevice"):
        torch._C._cuda_setDevice = lambda i: None

    try:
        import pynvml
        pynvml.nvmlInit = lambda: None
        pynvml.nvmlDeviceGetCount = lambda: 1
        pynvml.nvmlDeviceGetName = lambda h: GPU_NAME.encode()
        pynvml.nvmlDeviceGetHandleByIndex = lambda i: i
        pynvml.nvmlShutdown = lambda: None
        print("[patch] pynvml patched")
    except ImportError:
        print("[patch] pynvml not found")

    print(f"[patch] Done: is_available={torch.cuda.is_available()}, "
          f"count={torch.cuda.device_count()}, GPU={torch.cuda.get_device_name(0)}")
    return True


class HuggingFaceAPIServer:
    """HuggingFace Transformers 推理 API（OpenAI 兼容接口）。"""

    def __init__(
        self,
        model_path: str,
        model_name: str = "Qwen2.5-1.5B",
        device: str = "cuda",
        dtype: str = "float16",
        max_model_len: int = 4096,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> None:
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_model_len = max_model_len
        self.model = None
        self.tokenizer = None
        self.device = device
        self.dtype = dtype
        self.model_path = model_path

    def load_model(self) -> None:
        """加载模型和分词器。"""
        print(f"\n[HF Server] 正在加载模型: {self.model_path}")
        print(f"[HF Server] 设备: {self.device}, dtype: {self.dtype}")

        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        torch.set_num_threads(8)

        dtype_map = {
            "float16": torch.float16,
            "bfloat16": torch.bfloat16,
            "float32": torch.float32,
        }
        torch_dtype = dtype_map.get(self.dtype, torch.float16)

        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_path,
            trust_remote_code=True,
        )

        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            torch_dtype=torch_dtype,
            device_map="cpu",  # WSL2 GPU 不兼容，强制使用 CPU
            trust_remote_code=True,
        )

        # 获取实际加载设备
        first_param = next(self.model.parameters(), None)
        device_str = str(first_param.device) if first_param is not None else "unknown"
        print(f"[HF Server] 模型设备: {device_str}")
        self.model.eval()

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str:
        """生成聊天回复。"""
        if self.model is None:
            raise RuntimeError("模型未加载，请先调用 load_model()")

        import torch

        # 构建 prompt
        prompt = self._build_prompt(messages)

        # Tokenize（模型在 CPU 上）
        inputs = self.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=self.max_model_len - (max_tokens or self.max_tokens),
        )
        # 模型在 CPU，手动设置 device
        input_ids = inputs.input_ids
        attention_mask = inputs.attention_mask

        # 生成
        gen_kwargs = {
            "max_new_tokens": max_tokens or self.max_tokens,
            "temperature": temperature if temperature is not None else self.temperature,
            "do_sample": temperature is not None and temperature > 0,
            "pad_token_id": self.tokenizer.pad_token_id or self.tokenizer.eos_token_id,
            "eos_token_id": self.tokenizer.eos_token_id,
            "attention_mask": attention_mask,
        }

        with torch.no_grad():
            outputs = self.model.generate(input_ids=input_ids, **gen_kwargs)

        # 解码（去掉输入部分）
        response_ids = outputs[0][input_ids.shape[1]:]
        response = self.tokenizer.decode(response_ids, skip_special_tokens=True)
        return response.strip()

    @staticmethod
    def _build_prompt(messages: list[dict[str, str]]) -> str:
        """构建 Qwen 格式的 prompt。"""
        prompt = ""
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                prompt += f"<|im_start|>system\n{content}<|im_end|>\n"
            elif role == "user":
                prompt += f"<|im_start|>user\n{content}<|im_end|>\n"
            elif role == "assistant":
                prompt += f"<|im_start|>assistant\n{content}<|im_end|>\n"
        prompt += "<|im_start|>assistant\n"
        return prompt

    def list_models(self) -> list[dict[str, str]]:
        """返回模型列表（兼容 OpenAI API）。"""
        return [{"id": self.model_name, "object": "model", "owned_by": "huggingface"}]


    # ── 简单 HTTP API（FastAPI）────────────────────────────────────────────────
    from fastapi import FastAPI
    from starlette.requests import Request
    from starlette.routing import Route, RouteMixin
    from starlette.responses import JSONResponse

    app = FastAPI(title="HuggingFace Inference API")

    @app.get("/v1/models")
    def list_models():
        return {"object": "list", "data": server.list_models()}

    async def chat_endpoint(scope, receive, send):
        """手动处理 /v1/chat/completions 请求，完全绕过 FastAPI 路由解析。"""
        # 读取请求体
        body = b""
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.request":
                body += message.get("body", b"")
                more_body = message.get("more_body", False)
            elif message["type"] == "http.disconnect":
                break

        # 解析 JSON
        import json as _json
        try:
            data = _json.loads(body) if body else {}
        except Exception:
            data = {}

        messages = data.get("messages", [])
        model_name = data.get("model", server.model_name)
        temperature = data.get("temperature")
        max_tokens = data.get("max_tokens", server.max_tokens)

        try:
            content = server.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:
            content = f"Error: {str(e)}"

        response_data = {
            "id": f"chatcmpl-{os.urandom(8).hex()}",
            "object": "chat.completion",
            "created": int(__import__("time").time()),
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": len(content.split()),
                "total_tokens": len(content.split()),
            },
        }

        response_body = _json.dumps(response_data).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                [b"content-type", b"application/json"],
                [b"content-length", str(len(response_body)).encode()],
            ],
        })
        await send({"type": "http.response.body", "body": response_body})

    # 手动添加路由，完全绕过 FastAPI 路由装饰器
    from starlette.routing import Route, Router
    app.router = Router(
        routes=[
            Route("/v1/models", list_models, methods=["GET"]),
            Route("/v1/chat/completions", chat_endpoint, methods=["POST"]),
        ]
    )

    return app


def main():
    parser = argparse.ArgumentParser(description="HuggingFace 推理 API 服务")
    parser.add_argument("--model", type=str,
                        default="/home/brian/llm/Qwen/Qwen2.5-1.5B-Instruct",
                        help="模型路径")
    parser.add_argument("--served-model-name", dest="model_name", type=str,
                        default="Qwen2.5-1.5B",
                        help="API 模型名称")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--dtype", default="float16",
                        choices=["float16", "bfloat16", "float32"])
    parser.add_argument("--max-model-len", type=int, default=4096)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=1024)
    args = parser.parse_args()

    # 应用 WSL2 CUDA 补丁
    _apply_wsl2_cuda_patch()

    # 创建服务器
    server = HuggingFaceAPIServer(
        model_path=args.model,
        model_name=args.model_name,
        device="cuda",
        dtype=args.dtype,
        max_model_len=args.max_model_len,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )

    # 加载模型（同步）
    server.load_model()

    # 创建 FastAPI app
    app = create_app(server)

    print(f"\n[HF Server] 启动服务: http://{args.host}:{args.port}")
    print(f"[HF Server] API 端点: http://{args.host}:{args.port}/v1/chat/completions")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
