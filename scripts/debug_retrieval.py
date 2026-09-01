#!/usr/bin/env python3
"""检索系统 Debug 脚本：逐层验证各组件是否正常工作。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests
from app.config import get_settings
from app.service import get_service


def main():
    settings = get_settings()
    base_url = "http://127.0.0.1:8010"

    print("=" * 60)
    print("1. 配置检查")
    print(f"   mock_mode         = {settings.mock_mode}")
    print(f"   embed_model_path  = {settings.embed_model_path}")
    print(f"   llm_api_base      = {settings.llm_api_base}")
    print(f"   llm_model         = {settings.llm_model}")
    print()

    # ── 知识库检查（通过 HTTP API，能看到 server 进程的真实数据）──
    print("=" * 60)
    print("2. server 健康检查（HTTP）")
    try:
        resp = requests.get(f"{base_url}/health", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        kb_count = data.get("kb_count", -1)
        print(f"   ✅ server 运行正常")
        print(f"   KB count          = {kb_count}")
        if kb_count == 0:
            print("   ⚠️  知识库为空！需要入库数据后重试。")
        else:
            print(f"   ✅ server 知识库有 {kb_count} 条文档")
    except requests.exceptions.ConnectionError:
        print(f"   ⚠️  无法连接到 {base_url}")
        print("   → 请确保 run_server.py 已启动")
        kb_count = -1
    print()

    print("=" * 60)
    print("3. 初始化本地 Service（用于模型加载 + 检索测试）")
    service = get_service()
    print()

    print("=" * 60)
    print("4. BGE-M3 模型检查（本地）")
    print(f"   embedder._model   = {service.embedder._model}")
    if service.embedder._model is None:
        print("   ⚠️  BGE-M3 模型未加载！检索将回退到哈希模式，效果很差。")
    else:
        print("   ✅ BGE-M3 模型已加载")
    print()

    print("=" * 60)
    print("5. LLM 连接检查（本地）")
    if service.llm.client is not None:
        print("   ✅ LLM client 已连接，尝试一次真实调用...")
        try:
            test_resp = service.llm.chat(
                [{"role": "user", "content": "1+1等于几？"}],
                temperature=0.0,
                max_tokens=50,
            )
            print(f"   LLM 回复: {test_resp[:100]}")
        except Exception as e:
            print(f"   ⚠️  LLM 调用失败: {e}")
    else:
        print("   ⚠️  LLM client 为 None（mock 模式）")
    print()

    if kb_count > 0:
        print("=" * 60)
        print("6. 检索测试（本地 service，注意：这里查的是本地空 store）")
        print("   ⚠️  注意：本地 service KB=0 是正常的，数据在 server 进程里")
        print("   ✅ 真正的检索由 run_server.py 处理，这里仅验证模型可用性")
        test_question = "癫痫患者怀孕期间抗癫痫药物如何调整"
        print(f"   问题: {test_question}")
        try:
            chunks = service.retriever.retrieve(
                query=test_question,
                intent=None,
                top_k=5,
            )
            print(f"   本地 store 命中 {len(chunks)} 条（应该为 0）")
        except Exception as e:
            print(f"   ⚠️  检索异常: {e}")
    else:
        print("=" * 60)
        print("6. 跳过检索测试（server KB 为空）")

    print()
    print("=" * 60)
    print("结论：")
    if kb_count > 0:
        print("  ✅ server KB 有数据，可以直接跑评估脚本")
        print("  ✅ 评估脚本会通过 HTTP API 访问 server 的真实检索能力")
    else:
        print("  ⚠️  server KB 为空，先入库再跑评估")
    print("=" * 60)


if __name__ == "__main__":
    main()
