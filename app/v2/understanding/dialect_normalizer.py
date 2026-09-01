"""
V2 方言与口语规范化处理器

采用多级管道（Pipeline）架构，每级专注一个转换任务：
  Layer 1: 医学术语标准化
  Layer 2: 方言词汇转换
  Layer 3: 口语症状解析
  Layer 4: 身体部位标准化
  Layer 5: 向量相似度兜底

V2-002 迭代: 解决"脑阔痛啷个办"无法识别为"头痛"的问题
"""

from __future__ import annotations

import re

from ..dialect_dict import (
    EMERGENCY_KEYWORDS,
    SYMPTOM_EXPANSION,
    DialectEntry,
    build_category_index,
    build_exact_match_index,
    get_colloquial_map,
    get_dialect_dict,
)
from ..schemas_v2 import (
    MedicalEntity,
    NormalizationResult,
    Transformation,
)


class DialectNormalizer:
    """
    方言与口语规范化处理器

    将四川话等方言以及口语化表达转换为标准医学文本，
    同时提取医学实体和紧迫性信号。
    """

    def __init__(
        self,
        dialect_dict: list[DialectEntry] | None = None,
        symptom_map: dict[str, str] | None = None,
        use_fuzzy: bool = True,
    ) -> None:
        self.dialect_dict = dialect_dict or get_dialect_dict()
        self.symptom_map = symptom_map or get_colloquial_map()
        self.symptom_expansion = SYMPTOM_EXPANSION
        self.emergency_keywords = EMERGENCY_KEYWORDS

        # 构建索引以加速查找
        self._exact_index = build_exact_match_index()
        self._category_index = build_category_index()

        # 是否启用模糊匹配
        self.use_fuzzy = use_fuzzy

        # 正则表达式：检测可能的方言词（基于常见四川话特征）
        self._dialect_pattern = re.compile(
            r"[脑壳脑阔]\S{0,4}|"
            r"\S{1,3}(痛|阔|壳|杆|膀)|"
            r"(扯|发)\S{0,3}|"
            r"造\S{0,2}|遭\S{0,2}|"
            r"\S{1,3}(昏|晕|抽|扯)|"
            r"(大小)?手臂|脚杆",
            re.IGNORECASE,
        )

    def normalize(self, text: str) -> NormalizationResult:
        """
        完整规范化流程

        Args:
            text: 用户输入的原始文本

        Returns:
            NormalizationResult: 包含规范化文本、医学实体、变换历史、紧迫性信号
        """
        if not text or not text.strip():
            return NormalizationResult(
                original_text=text or "",
                normalized_text="",
                medical_entities=[],
                transformations=[],
                urgency_signs=[],
            )

        current_text = text.strip()
        medical_entities: list[MedicalEntity] = []
        transformations: list[Transformation] = []
        urgency_signs: list[str] = []

        # Stage 1: 医学术语标准化（症状同义词扩展）
        current_text, entities1, trans1 = self._normalize_medical_terms(current_text)
        medical_entities.extend(entities1)
        transformations.extend(trans1)

        # Stage 2: 方言词汇转换
        current_text, entities2, trans2 = self._normalize_dialect_words(current_text)
        medical_entities.extend(entities2)
        transformations.extend(trans2)

        # Stage 3: 口语症状解析
        current_text, entities3, trans3 = self._normalize_colloquial(current_text)
        medical_entities.extend(entities3)
        transformations.extend(trans3)

        # Stage 4: 身体部位标准化
        current_text, entities4, trans4 = self._normalize_body_parts(current_text)
        medical_entities.extend(entities4)
        transformations.extend(trans4)

        # Stage 5: 紧迫性信号检测
        urgency_signs = self._detect_urgency_signs(text)

        return NormalizationResult(
            original_text=text,
            normalized_text=current_text,
            medical_entities=medical_entities,
            transformations=[
                t.model_dump() if hasattr(t, "model_dump") else dict(t) for t in transformations
            ],
            urgency_signs=urgency_signs,
        )

    def _normalize_medical_terms(
        self, text: str
    ) -> tuple[str, list[MedicalEntity], list[Transformation]]:
        """
        Layer 1: 医学术语标准化
        将非标准症状表达转换为标准医学术语
        例如："抽风" → "抽搐"
        """
        result = text
        entities: list[MedicalEntity] = []
        transformations: list[Transformation] = []

        # 按长度从长到短排序，避免"抽搐"被"抽搐发作"截断后再次处理
        sorted_terms = sorted(
            self.symptom_expansion.items(),
            key=lambda x: len(x[0]),
            reverse=True,
        )

        # 构建所有同义词的快速查找集合
        all_variants: dict[str, str] = {}
        for standard, variants in sorted_terms:
            for variant in variants:
                all_variants[variant.lower()] = standard

        # 标记已替换的位置，避免重复处理
        replaced_ranges: list[tuple[int, int, str]] = []

        # 简单贪心替换（按长度降序）
        for variant, standard in sorted(
            all_variants.items(), key=lambda x: len(x[0]), reverse=True
        ):
            pattern = re.escape(variant)
            for m in re.finditer(pattern, result, re.IGNORECASE):
                start, end = m.start(), m.end()
                # 检查是否与已替换的区域重叠
                if any(r[0] < end and r[1] > start for r in replaced_ranges):
                    continue

                matched_text = m.group()
                result = result[:start] + standard + result[end:]
                new_end = start + len(standard)

                replaced_ranges.append((start, new_end, standard))
                entities.append(
                    MedicalEntity(
                        text=matched_text,
                        normalized=standard,
                        medical_term=standard,
                        category="symptom",
                        confidence=0.95,
                        position=(start, new_end),
                    )
                )
                transformations.append(
                    Transformation(
                        stage="medical_term",
                        original=matched_text,
                        replacement=standard,
                        confidence=0.95,
                    )
                )
                break  # 每个标准词只替换一次

        return result, entities, transformations

    def _normalize_dialect_words(
        self, text: str
    ) -> tuple[str, list[MedicalEntity], list[Transformation]]:
        """
        Layer 2: 方言词汇转换
        将四川话词汇转换为标准普通话
        例如："脑阔痛" → "头痛"
        """
        result = text
        entities: list[MedicalEntity] = []
        transformations: list[Transformation] = []

        # 从最长到最短排序，避免"小手臂"被"手臂"截断
        sorted_entries = sorted(
            self._exact_index.items(),
            key=lambda x: len(x[0]),
            reverse=True,
        )

        # 标记已替换的区域
        replaced_ranges: list[tuple[int, int]] = []

        for dialect_word, entry in sorted_entries:
            pattern = re.escape(dialect_word)
            for m in re.finditer(pattern, result):
                start, end = m.start(), m.end()
                # 检查重叠
                if any(r[0] < end and r[1] > start for r in replaced_ranges):
                    continue

                result = result[:start] + entry.normalized + result[end:]

                entities.append(
                    MedicalEntity(
                        text=dialect_word,
                        normalized=entry.normalized,
                        medical_term=entry.medical_term,
                        category=entry.category,
                        confidence=entry.confidence,
                        position=(start, start + len(entry.normalized)),
                    )
                )
                transformations.append(
                    Transformation(
                        stage="dialect",
                        original=dialect_word,
                        replacement=entry.normalized,
                        confidence=entry.confidence,
                    )
                )
                break  # 每个方言词只替换一次

        return result, entities, transformations

    def _normalize_colloquial(
        self, text: str
    ) -> tuple[str, list[MedicalEntity], list[Transformation]]:
        """
        Layer 3: 口语症状解析
        将口语化症状描述转换为标准医学描述
        例如："嘴巴流口水" → "口角流涎"
        """
        result = text
        entities: list[MedicalEntity] = []
        transformations: list[Transformation] = []

        # 按长度从长到短排序
        sorted_items = sorted(
            self.symptom_map.items(),
            key=lambda x: len(x[0]),
            reverse=True,
        )

        replaced_ranges: list[tuple[int, int]] = []

        for colloquial, standard in sorted_items:
            pattern = re.escape(colloquial)
            for m in re.finditer(pattern, result, re.IGNORECASE):
                start, end = m.start(), m.end()
                if any(r[0] < end and r[1] > start for r in replaced_ranges):
                    continue

                result = result[:start] + standard + result[end:]

                entities.append(
                    MedicalEntity(
                        text=colloquial,
                        normalized=standard,
                        medical_term=standard,
                        category="symptom",
                        confidence=0.9,
                        position=(start, start + len(standard)),
                    )
                )
                transformations.append(
                    Transformation(
                        stage="colloquial",
                        original=colloquial,
                        replacement=standard,
                        confidence=0.9,
                    )
                )
                break

        return result, entities, transformations

    def _normalize_body_parts(
        self, text: str
    ) -> tuple[str, list[MedicalEntity], list[Transformation]]:
        """
        Layer 4: 身体部位标准化
        将方言身体部位名称标准化
        例如："小手臂" → "前臂"
        """
        # 身体部位的方言已经在 Layer 2 处理了
        # 这里可以做一些额外的规范化，如左右侧标注
        result = text
        entities: list[MedicalEntity] = []
        transformations: list[Transformation] = []

        # 检测左右侧描述
        lateral_pattern = re.compile(
            r"(左(?:侧|边|手|脚|腿|臂)|右(?:侧|边|手|脚|腿|臂)|" r"左侧|右侧|左边|右边)",
            re.IGNORECASE,
        )

        # 检测到的侧向描述已经可以直接使用
        for m in lateral_pattern.finditer(result):
            entities.append(
                MedicalEntity(
                    text=m.group(),
                    normalized=m.group(),
                    medical_term="lateral_descriptor",
                    category="lateral",
                    confidence=1.0,
                    position=(m.start(), m.end()),
                )
            )

        return result, entities, transformations

    def _detect_urgency_signs(self, text: str) -> list[str]:
        """
        检测紧迫性信号
        识别可能表示急危重症的关键词
        """
        urgency_signs: list[str] = []
        text_lower = text.lower()

        for keyword in self.emergency_keywords:
            if keyword.lower() in text_lower:
                # 避免重复添加
                if keyword not in urgency_signs:
                    urgency_signs.append(keyword)

        return urgency_signs

    def extract_symptoms(self, text: str) -> list[str]:
        """
        从文本中提取症状关键词
        返回标准化后的症状列表
        """
        result = self.normalize(text)
        symptoms = set()

        for entity in result.medical_entities:
            if entity.category == "symptom":
                symptoms.add(entity.normalized)

        return list(symptoms)

    def get_symptom_expansion_terms(self, symptom: str) -> list[str]:
        """
        获取症状的同义词扩展列表
        用于检索增强
        """
        # 在同义词表中查找
        for standard, variants in self.symptom_expansion.items():
            if symptom in variants or symptom == standard:
                return variants

        return [symptom]  # 未找到则返回原词


class DialectNormalizerFactory:
    """
    方言规范化器工厂
    支持创建不同配置的规范化器
    """

    @staticmethod
    def create_default() -> DialectNormalizer:
        """创建默认配置的规范化器"""
        return DialectNormalizer(
            dialect_dict=get_dialect_dict(),
            symptom_map=get_colloquial_map(),
            use_fuzzy=True,
        )

    @staticmethod
    def create_sichuan_only() -> DialectNormalizer:
        """仅处理四川话"""
        return DialectNormalizer(
            dialect_dict=[e for e in get_dialect_dict() if e.dialect == "sichuan"],
            symptom_map=get_colloquial_map(),
            use_fuzzy=False,
        )

    @staticmethod
    def create_strict() -> DialectNormalizer:
        """严格模式：仅使用高置信度映射"""
        return DialectNormalizer(
            dialect_dict=[e for e in get_dialect_dict() if e.confidence >= 0.85],
            symptom_map={k: v for k, v in get_colloquial_map().items()},
            use_fuzzy=False,
        )
