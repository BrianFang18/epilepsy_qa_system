from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter

TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]+|[A-Za-z0-9_]+")

# 中文停用词（常见标点、功能词，不贡献语义）
_STOPWORDS = {
    "，",
    "。",
    "！",
    "？",
    "：",
    "；",
    '"',
    "'",
    "（",
    "）",
    "【",
    "】",
    "、",
    "／",
    "～",
    "——",
    "–",
    "—",
    "\n",
    "\t",
    " ",
    "　",
    "的",
    "了",
    "是",
    "在",
    "和",
    "与",
    "或",
    "及",
    "等",
    "也",
    "都",
    "而",
    "为",
    "有",
    "以",
    "于",
    "被",
    "由",
    "将",
    "可",
    "能",
    "会",
    "应",
    "需",
    "要",
    "到",
    "对",
    "不",
    "无",
    "非",
    "但",
    "却",
    "又",
    "则",
    "之",
    "这",
    "那",
    "此",
    "其",
    "一",
    "每",
    "各",
}

# jieba 初始化标记（避免重复加载）
_jieba_initialized = False


def _init_jieba() -> None:
    global _jieba_initialized
    if _jieba_initialized:
        return
    try:
        from pathlib import Path

        import jieba

        user_dict = Path(__file__).resolve().parents[1] / "data" / "jieba_user_dict.txt"
        if user_dict.exists():
            jieba.load_userdict(str(user_dict))
        _jieba_initialized = True
    except Exception:
        _jieba_initialized = True  # 失败也标记，避免重复尝试


def simple_tokenize(text: str) -> list[str]:
    """
    混合分词：
    - 英文/数字：保留原词（统一小写）
    - 中文：用 jieba 精确模式分词，去停用词，去单字
    """
    text = text or ""
    _init_jieba()
    # 英文词（已足够精确）
    en_tokens = [t.lower() for t in TOKEN_PATTERN.findall(text) if t.isascii()]
    # 中文词（jieba）
    zh_chunks = TOKEN_PATTERN.findall(text)
    zh_tokens: list[str] = []
    try:
        import jieba

        for chunk in zh_chunks:
            if not chunk.isascii():
                tokens = jieba.lcut(chunk, cut_all=False)
                zh_tokens.extend(
                    t.strip().lower()
                    for t in tokens
                    if t.strip() and t.strip() not in _STOPWORDS and len(t.strip()) > 1
                )
    except Exception:
        zh_tokens = _fallback_chinese_tokenize(text)

    return en_tokens + zh_tokens


def _fallback_chinese_tokenize(text: str) -> list[str]:
    """jieba 不可用时的中文回退分词。"""
    # 去掉已匹配的英文，保留纯中文部分
    zh_only = TOKEN_PATTERN.sub("", text)
    tokens = []
    for chunk in zh_only:
        for start in range(0, len(chunk) - 1, 2):
            token = chunk[start : start + 2]
            if token.strip() not in _STOPWORDS:
                tokens.append(token)
    return tokens


def hash_token_to_index(token: str, dim: int) -> int:
    digest = hashlib.md5(token.encode("utf-8")).hexdigest()
    return int(digest, 16) % dim


def vector_norm(vec: list[float]) -> float:
    return math.sqrt(sum(v * v for v in vec))


def normalize_vector(vec: list[float]) -> list[float]:
    norm = vector_norm(vec)
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = vector_norm(a)
    nb = vector_norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def sparse_dot(a: dict[int, float], b: dict[int, float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


def tf_sparse_vector(text: str, dim: int = 100_000) -> dict[int, float]:
    tokens = simple_tokenize(text)
    if not tokens:
        return {}
    cnt = Counter(tokens)
    total = float(sum(cnt.values()))
    return {hash_token_to_index(tok, dim): c / total for tok, c in cnt.items()}


def safe_json_loads(text: str) -> dict:
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return {}
        try:
            return json.loads(match.group(0))
        except Exception:
            return {}
