"""Cozie AI safety-classification review profile."""

from __future__ import annotations

import csv
import json
from pathlib import Path

NAME = "cozie-safety"
DEFAULT_DATASET_PREFIX = "cozie_safety_review"

SAFETY_LABELS = {
    "non_health": "非健康 / Non-health",
    "general_health": "通用健康 / General health",
    "personalized_health": "个性化健康 / Personalized health",
    "general_medical": "一般医学 / General medical",
    "restricted_medical": "受限医学 / Restricted medical",
}

BOUNDARY_LABELS = {
    "CLEAR": "明确 / Clear",
    "UNCLEAR": "不明确 / Unclear",
    "INSUFFICIENT_INFO": "信息不足 / Insufficient information",
    "OUT_OF_SCOPE": "体系外 / Out of scope",
}

REASON_LABELS = {
    "NON_HEALTH_OPERATION": "非健康或功能操作 / Non-health or operation",
    "GENERAL_INFO": "通用健康信息 / General information",
    "PERSONAL_LOW_RISK": "个体低风险建议 / Personalized low-risk advice",
    "GENERAL_MEDICAL": "一般医学知识 / General medical knowledge",
    "INDIVIDUAL_CLINICAL": "个体临床判断 / Individual clinical judgment",
    "EMERGENCY": "紧急风险信号 / Emergency signal",
    "CONTEXT_INSUFFICIENT": "上下文不足 / Insufficient context",
    "TAXONOMY_GAP": "分类体系缺口 / Taxonomy gap",
}

REASONABLENESS_LABELS = {
    "EXPECTED_BETTER": "原标签更合理 / Expected label is better",
    "PREDICTED_BETTER": "模型标签更合理 / Predicted label is better",
    "BOTH_ACCEPTABLE": "两者都可接受 / Both are acceptable",
    "NEITHER_ACCEPTABLE": "两者都不合理 / Neither is acceptable",
    "INSUFFICIENT_INFO": "信息不足 / Insufficient information",
}

YES_NO_LABELS = {
    "YES": "是 / Yes",
    "NO": "否 / No",
}

REQUIRED_COLUMNS = {
    "case_id",
    "user_profile",
    "conversation_history",
    "user_input",
    "expected_safety_class",
    "predicted_safety_class",
}

METADATA_NAMES = (
    "case_id",
    "priority",
    "difficulty",
    "turn_type",
    "sub_capability",
    "expected_safety_class",
    "predicted_safety_class",
    "conflict_pair",
    "boundary_precheck",
    "review_route",
)

VISIBLE_METADATA = {
    "case_id",
    "priority",
    "difficulty",
    "turn_type",
    "sub_capability",
}


def load_rows(path: Path) -> list[dict[str, str]]:
    """Load and validate a reviewed CSV without changing its order."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_COLUMNS - columns)
        if missing:
            raise ValueError(f"{path}: missing columns: {', '.join(missing)}")
        rows = list(reader)

    if not rows:
        raise ValueError(f"{path}: no records found")

    case_ids = [row["case_id"].strip() for row in rows]
    if any(not case_id for case_id in case_ids):
        raise ValueError(f"{path}: case_id cannot be empty")
    if len(case_ids) != len(set(case_ids)):
        raise ValueError(f"{path}: duplicate case_id found")
    return rows


def _format_json(raw: str) -> str:
    if not raw.strip():
        return "无 / None"
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    return f"```json\n{json.dumps(value, ensure_ascii=False, indent=2)}\n```"


def review_context(row: dict[str, str]) -> str:
    return "\n\n".join(
        [
            "### 用户画像 / User profile",
            _format_json(row.get("user_profile", "")),
            "### 历史消息 / Conversation history",
            _format_json(row.get("conversation_history", "")),
        ]
    )


def comparison_context(row: dict[str, str]) -> str:
    expected = row["expected_safety_class"].strip()
    predicted = row["predicted_safety_class"].strip()
    return "\n".join(
        [
            f"- 原标签（待验证）/ Expected: `{expected}`",
            f"- 模型标签 / Predicted: `{predicted}`",
        ]
    )


def record_metadata(row: dict[str, str]) -> dict[str, str]:
    return {
        name: row[name].strip()
        for name in METADATA_NAMES
        if name in row and row[name].strip()
    }
