"""
V2 API 路由

提供与 V1 兼容的 API，同时开放 V2 专用接口：
- /v2/consultation/start — 开始问诊
- /v2/consultation/turn — 处理一轮对话
- /v2/consultation/summary — 获取问诊总结
- /v2/consultation/emr — 生成电子病历
- /v2/normalize — 方言规范化测试
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .safety import get_safety_guard
from .schemas_v2 import (
    ConsultationSummaryRequest,
    ConsultationSummaryResponse,
    ConversationStartRequest,
    ConversationStartResponse,
    ConversationTurnRequest,
    ConversationTurnResponse,
)
from .understanding import DialectNormalizer
from .workflow import MedicalConsultationWorkflow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2", tags=["v2"])

# 无服务依赖的轻量组件可在模块内懒加载。
_dialect_normalizer: DialectNormalizer | None = None


def _get_workflow(request: Request) -> MedicalConsultationWorkflow:
    """获取当前 FastAPI 应用隔离的 V2 工作流实例。"""
    app_state = request.app.state
    workflow = getattr(app_state, "v2_workflow", None)
    if workflow is not None:
        return workflow

    llm = getattr(app_state, "llm", None)
    retriever = getattr(app_state, "retriever", None)
    embedder = getattr(app_state, "embedder", None)

    if llm is None or retriever is None:
        raise HTTPException(
            status_code=503,
            detail="V2 service not initialized. Please ensure V1 services are running.",
        )

    workflow = MedicalConsultationWorkflow(
        llm_client=llm,
        retriever=retriever,
        embedder=embedder,
    )
    app_state.v2_workflow = workflow
    return workflow


def _get_dialect_normalizer() -> DialectNormalizer:
    """获取方言规范化器"""
    global _dialect_normalizer
    if _dialect_normalizer is None:
        _dialect_normalizer = DialectNormalizer()
    return _dialect_normalizer


# ─────────────────────────────────────────────────────────────────────────────
# 问诊接口
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/consultation/start", response_model=ConversationStartResponse)
def start_consultation(
    request: ConversationStartRequest,
    http_request: Request,
) -> ConversationStartResponse:
    """
    开始一个新的问诊会话

    返回：
    - session_id: 会话 ID（用于后续对话）
    - greeting: 开场白
    - first_question: 第一个追问
    """
    try:
        workflow = _get_workflow(http_request)
        session_id, greeting, first_question = workflow.start_consultation(
            patient_id=request.patient_id,
            initial_complaint=request.initial_complaint,
        )

        return ConversationStartResponse(
            session_id=session_id,
            greeting=greeting,
            first_question=first_question,
            estimated_turns=5,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to start consultation: {exc}")
        raise HTTPException(status_code=500, detail=f"start consultation failed: {exc}") from exc


@router.post("/consultation/turn", response_model=ConversationTurnResponse)
def process_consultation_turn(
    request: ConversationTurnRequest,
    http_request: Request,
) -> ConversationTurnResponse:
    """
    处理一轮问诊对话

    请求：
    - session_id: 会话 ID
    - message: 用户消息
    - with_trace: 是否返回详细链路

    返回：
    - response: 医生回复
    - phase: 当前问诊阶段
    - completion: 完成度
    - urgency: 紧迫性
    - emergency_detected: 是否检测到急危重症
    - collected_slots: 已收集的槽位
    """
    try:
        # 安全检查
        safety = get_safety_guard()
        is_safe, warning = safety.check_input(request.message)
        if not is_safe:
            raise HTTPException(
                status_code=400,
                detail=f"Input safety check failed: {warning}",
            )

        # 处理对话
        workflow = _get_workflow(http_request)
        response = workflow.process_turn(request)

        # 输出安全护栏
        response.response = safety.guard_output(response.response)

        return response
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(f"Failed to process turn: {exc}")
        raise HTTPException(status_code=500, detail=f"process turn failed: {exc}") from exc


@router.post("/consultation/summary", response_model=ConsultationSummaryResponse)
def get_consultation_summary(
    request: ConsultationSummaryRequest,
    http_request: Request,
) -> ConsultationSummaryResponse:
    """
    获取问诊总结

    返回：
    - summary: 问诊总结文本
    - collected_info: 收集到的信息
    - draft_diagnoses: 初步诊断
    - suggested_actions: 建议处置
    - referral_urgency: 转诊紧迫性
    """
    try:
        workflow = _get_workflow(http_request)
        summary = workflow.get_consultation_summary(request.session_id)

        # 构建总结响应
        collected_parts = []
        for k, v in summary.get("collected_slots", {}).items():
            if v:
                collected_parts.append(f"{k}: {v}")

        return ConsultationSummaryResponse(
            session_id=request.session_id,
            summary="\n".join(
                [
                    "【问诊摘要】",
                    f"阶段：{summary.get('phase', 'unknown')}",
                    f"完成度：{summary.get('completion', '0%')}",
                    f"紧迫性：{summary.get('urgency', 'unknown')}",
                    "",
                    "【已收集信息】",
                    "\n".join(f"- {p}" for p in collected_parts) if collected_parts else "暂无",
                ]
            ),
            collected_info=summary.get("collected_slots", {}),
            draft_diagnoses=summary.get("draft_diagnoses", []),
            suggested_actions=summary.get("suggested_actions", []),
            referral_urgency=summary.get("urgency", "low"),
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(f"Failed to get summary: {exc}")
        raise HTTPException(status_code=500, detail=f"get summary failed: {exc}") from exc


# ─────────────────────────────────────────────────────────────────────────────
# 工具接口
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/normalize")
def normalize_text(text: dict[str, str]) -> dict[str, Any]:
    """
    方言规范化测试接口

    请求：
    - text: {"input": "我脑阔痛啷个办"}

    返回：
    - original: 原始文本
    - normalized: 规范化后的文本
    - medical_entities: 识别的医学实体
    - transformations: 变换历史
    - urgency_signs: 紧迫性信号
    """
    input_text = text.get("input", "")
    if not input_text:
        raise HTTPException(status_code=400, detail="input text is required")

    normalizer = _get_dialect_normalizer()
    result = normalizer.normalize(input_text)

    return {
        "original": result.original_text,
        "normalized": result.normalized_text,
        "medical_entities": [
            {
                "text": e.text,
                "normalized": e.normalized,
                "medical_term": e.medical_term,
                "category": e.category,
                "confidence": e.confidence,
            }
            for e in result.medical_entities
        ],
        "transformations": [
            {
                "stage": t.stage,
                "original": t.original,
                "replacement": t.replacement,
                "confidence": t.confidence,
            }
            for t in result.transformations
        ],
        "urgency_signs": result.urgency_signs,
    }


@router.post("/emergency/detect")
def detect_emergency(text: dict[str, str]) -> dict[str, Any]:
    """
    急危重症检测接口

    请求：
    - text: {"input": "抽搐持续超过5分钟了"}

    返回：
    - is_emergency: 是否为紧急情况
    - urgency_level: 紧迫性等级
    - detected_signs: 检测到的信号
    - warning: 建议的警告消息
    """
    input_text = text.get("input", "")
    if not input_text:
        raise HTTPException(status_code=400, detail="input text is required")

    safety = get_safety_guard()
    is_emergency, urgency, signs = safety.detect_emergency(input_text)

    warning = ""
    if is_emergency:
        warning = safety.emergency_detector.generate_emergency_warning(urgency, signs)

    return {
        "is_emergency": is_emergency,
        "urgency_level": urgency.value,
        "detected_signs": signs,
        "warning": warning,
    }
