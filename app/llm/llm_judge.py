from __future__ import annotations

from ..prompts import LLM_JUDGE_PROMPT
from ..schemas import JudgeResponse
from ..utils import safe_json_loads
from .llm_client import LLMClient


class LLMJudge:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def judge(self, question: str, answer: str, references: list[str]) -> JudgeResponse:
        ref_text = (
            "\n".join(f"- {r}" for r in references) if references else "- no external evidence"
        )
        prompt = LLM_JUDGE_PROMPT.format(question=question, answer=answer, references=ref_text)
        raw = self.llm.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=300,
            json_mode=True,
        )
        data = safe_json_loads(raw)
        return JudgeResponse(
            total_score=float(data.get("total_score", 0.0)),
            safety_score=float(data.get("safety_score", 0.0)),
            professionalism_score=float(data.get("professionalism_score", 0.0)),
            factuality_score=float(data.get("factuality_score", 0.0)),
            verdict=str(data.get("verdict", "borderline")),
            rationale=str(data.get("rationale", "No rationale returned by judge model.")),
        )
