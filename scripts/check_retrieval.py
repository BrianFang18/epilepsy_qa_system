#!/usr/bin/env python3
"""直接调 server 检索接口，看看 KB 里到底有什么。"""
import requests

BASE = "http://127.0.0.1:8010"

def ask(question):
    resp = requests.post(f"{BASE}/v1/ask", json={"question": question, "with_trace": False}, timeout=30)
    resp.raise_for_status()
    return resp.json()

def health():
    resp = requests.get(f"{BASE}/health", timeout=5)
    return resp.json()

def main():
    h = health()
    print(f"KB count: {h['kb_count']}\n")

    questions = [
        "左乙拉西坦的适应症有哪些？",
        "癫痫手术治疗的适应症有哪些？",
        "局灶性发作的典型脑电图特征是什么？",
        "癫痫持续状态的院前处理流程是什么？",
    ]

    for q in questions:
        result = ask(q)
        sources = result.get("sources", [])
        print(f"Q: {q}")
        print(f"  intent={result['intent']}  sources_count={len(sources)}")
        for s in sources[:3]:
            print(f"  [{s['doc_type']}] score={s['score']:.4f}  title={s['title'][:60]}")
            print(f"    text={s['text'][:120]}...")
        print()
        # 同时打印 router debug 行（workflow.py 加过）
        import re
        trace = result.get("trace", [])
        router_trace = [t for t in trace if t.startswith("intent=")]
        for t in router_trace:
            print(f"  ROUTER: {t}")
        print("-" * 60)

if __name__ == "__main__":
    main()
