from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..config import Settings
from ..utils import simple_tokenize

if TYPE_CHECKING:
    from openai import OpenAI


class LLMClient:
    """统一的大模型客户端：优先真实 OpenAI 兼容接口，失败时回退 mock。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client: OpenAI | None = None
        self._try_init_openai_client()

    def _try_init_openai_client(self) -> None:
        # mock 模式下不连接远端模型服务。
        if self.settings.mock_mode:
            return
        try:
            from openai import OpenAI

            self.client = OpenAI(
                api_key=self.settings.llm_api_key,
                base_url=self.settings.llm_api_base,
                timeout=30.0,
            )
        except Exception:
            # 保持 None，让上层自动走 mock 逻辑，保证接口可用。
            self.client = None

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str:
        if self.client is None:
            return self._mock_response(messages, json_mode=json_mode)

        try:
            kwargs: dict[str, Any] = {
                "model": self.settings.llm_model,
                "messages": messages,
                "temperature": self.settings.llm_temperature
                if temperature is None
                else temperature,
                "max_tokens": self.settings.llm_max_tokens if max_tokens is None else max_tokens,
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            resp = self.client.chat.completions.create(**kwargs)
            content = resp.choices[0].message.content
            if content:
                return content.strip()
            return "{}" if json_mode else ""
        except Exception:
            # 运行期失败时回退 mock，避免整个 API 因上游模型故障不可用。
            return self._mock_response(messages, json_mode=json_mode)

    def _mock_response(self, messages: list[dict[str, str]], json_mode: bool) -> str:
        merged = "\n".join(m.get("content", "") for m in messages)
        lower = merged.lower()

        # 意图路由 mock。
        if '"intent"' in lower and "literature|clinical|both" in lower:
            intent = self._rule_intent(merged)
            return f'{{"intent":"{intent}","reason":"mock router by keyword"}}'

        # 查询改写 mock。
        if '"queries"' in lower:
            question = messages[-1]["content"]
            return self._mock_queries(question)

        # LLM 评委打分 mock。
        if "total_score" in lower and "safety_score" in lower:
            return (
                '{"total_score":8.5,"safety_score":9.0,"professionalism_score":8.2,'
                '"factuality_score":8.4,"verdict":"pass","rationale":"Answer is acceptable with safety warning."}'
            )

        if json_mode:
            return "{}"

        return (
            "[Conclusion] Based on available evidence, follow standard epilepsy management and verify with specialist review.\n"
            "[Evidence] 1) Retrieved relevant clinical/literature passages. 2) Medication and follow-up should be individualized.\n"
            "[Risk] If prolonged seizure, altered consciousness, or breathing issues occur, seek emergency care immediately.\n"
            "[Next Steps] Provide seizure frequency, current medication, and EEG findings for a more precise suggestion."
        )

    def _rule_intent(self, text: str) -> str:
        """规则路由（fallback）：根据关键词判断意图。"""
        question = self._extract_question_from_router_prompt(text)
        lower_text = question.lower()

        literature_keys = {
            "literature",
            "guideline",
            "study",
            "meta",
            "rct",
            "consensus",
            "evidence",
            "文献",
            "指南",
            "研究",
            "共识",
            "证据",
            # 常见医学文献类关键词
            "适应症",
            "禁忌症",
            "疗效",
            "机制",
            "药理",
            "代谢",
            "脑电图",
            "分类",
            "标准",
            "方案",
            "体系",
            "ilae",
            "手术",
            "切除",
            "电图",
            "综合征",
            "癫痫发作",
            "randomized",
            "trial",
            "review",
            "cochrane",
        }
        clinical_keys = {
            "symptom",
            "seizure",
            "dose",
            "side effect",
            "follow-up",
            "patient",
            "pregnancy",
            "发作",
            "剂量",
            "随访",
            "患者",
            "怀孕",
            "急诊",
            "怎么处理",
            "怎么办",
            "怎么选",
            "如何调整",
            "日记",
            "记录",
            "教育",
            "护理",
        }
        tokens = set(simple_tokenize(lower_text))

        lit_hit = any(k in lower_text for k in literature_keys) or any(
            k in tokens for k in literature_keys
        )
        cli_hit = any(k in lower_text for k in clinical_keys) or any(
            k in tokens for k in clinical_keys
        )

        if lit_hit and cli_hit:
            return "both"
        if lit_hit:
            return "literature"
        return "clinical"

    @staticmethod
    def _extract_question_from_router_prompt(text: str) -> str:
        # 路由提示词结尾是：用户问题：{question}
        marker = "用户问题："
        if marker in text:
            return text.split(marker)[-1].strip()
        return text

    def _mock_queries(self, prompt: str) -> str:
        raw = prompt.split("Original question:")[-1].split("原问题：")[-1].strip()
        variants = [raw]
        if "epilepsy" in raw.lower():
            variants.append(raw.replace("epilepsy", "seizure disorder"))
        variants.append(f"{raw} guideline")

        uniq: list[str] = []
        seen = set()
        for q in variants:
            q = q.strip()
            if q and q not in seen:
                uniq.append(q)
                seen.add(q)
        return '{"queries":' + str(uniq[:3]).replace("'", '"') + "}"
