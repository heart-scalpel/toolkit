"""Review generated consultation materials alongside actual engine predictions."""

# ruff: noqa: RUF001 -- Chinese punctuation is intentional user-facing copy.

from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path

from app.core import FieldSpec, MetadataSpec, ProfileInput, QuestionSpec, RecordSpec, TaskSpec
from app.inputs import read_csv
from app.profiles.cozie_safety import (
    BOUNDARY_LABELS,
    REASON_LABELS,
    SAFETY_LABELS,
    YES_NO_LABELS,
)

GUIDELINES_PATH = Path(__file__).resolve().parents[2] / "docs/medical_case_review_guidelines.md"
REQUIRED_COLUMNS = {
    "case_id",
    "user_input",
    "user_profile",
    "candidate_safety_class",
    "initial_assessment",
    "possible_consultation_response",
    "follow_ups",
    "predicted_safety_class",
}
METADATA_NAMES = (
    "case_id",
    "id_prefix",
    "local_id",
    "pair_key",
    "changed_factor",
    "draft_status",
    "engine_status",
    "candidate_safety_class",
    "predicted_safety_class",
)


def _text(value: object) -> str:
    """Render source values as text without interpreting their Markdown."""
    if value is None:
        return "未提供"
    if isinstance(value, (dict, list, bool)):
        value = json.dumps(value, ensure_ascii=False)
    return re.sub(r"([\\`*_{}\[\]()#+.!|>\-])", r"\\\1", escape(str(value), quote=False))


def _safety_label(value: str) -> str:
    return SAFETY_LABELS.get(value, "待裁定")


def _profile_materials(raw: str) -> str:
    profile = json.loads(raw)
    labels = {
        "stage": "所处阶段",
        "baby_age_days": "宝宝日龄（天）",
        "locale": "语言地区",
    }
    facts = [
        f"| {label} | {_text(profile[key]).replace(chr(10), ' ')} |"
        for key, label in labels.items()
        if key in profile
    ]
    sections = ["| 基本信息 | 内容 |\n| :--- | :--- |\n" + "\n".join(facts)] if facts else []
    if "background" in profile:
        background = profile["background"]
        if isinstance(background, list):
            details = "\n".join("- " + _text(item).replace("\n", "\n  ") for item in background)
            details = details or "未提供背景信息。"
        else:
            details = _text(background)
        sections.extend(["### 背景信息", details])
    for key, value in profile.items():
        if key not in {*labels, "background"}:
            sections.append(f"**{_text(key)}：** {_text(value)}")
    return "\n\n".join(sections) or "未提供画像信息。"


def _follow_up_materials(raw: str) -> str:
    items = json.loads(raw)
    if not items:
        return "候选材料未提供追问。"
    return "\n\n".join(
        f"{index}. **{_text(item['question']).replace(chr(10), chr(10) + '   ')}**\n\n"
        f"   追问目的：{_text(item['purpose']).replace(chr(10), chr(10) + '   ')}"
        for index, item in enumerate(items, start=1)
    )


def _engine_materials(row: dict[str, str]) -> str:
    prediction = row.get("predicted_safety_class", "")
    reasoning = row.get("model_reasoning", "") or row.get("reasoning", "")
    error = row.get("classifier_error", "") or row.get("error", "")
    if prediction:
        sections = [
            f"**引擎分类：{_safety_label(prediction)}**",
            "### 判断理由",
            _text(reasoning) if reasoning else "未提供判断理由。",
        ]
    else:
        sections = ["**引擎判断：未生成有效结果**"]
    if error:
        sections.append("本条模型调用失败，请以人工判断为准。")
    sections.append("模型预判仅供参考，请结合问题与画像独立审核。")
    return "\n\n".join(sections)


class CozieMedicalReviewProfile:
    name = "cozie-medical-review"
    modes = ("review",)
    default_dataset_prefix = "cozie_medical_review"
    default_input_name = "medical_engine_results.csv"
    default_user_prefix = "medical_reviewer"
    sampling_fields = ("id_prefix", "predicted_safety_class")

    def _validate_mode(self, mode: str) -> None:
        if mode not in self.modes:
            raise ValueError(f"unsupported mode for profile {self.name!r}: {mode}")

    def load_input(self, path: Path) -> ProfileInput:
        table = read_csv(path)
        missing = REQUIRED_COLUMNS - set(table.columns)
        if missing:
            raise ValueError(
                f"{path}: missing medical-review columns: {', '.join(sorted(missing))}"
            )
        rows = []
        ids = set()
        for source in table.rows:
            row = dict(source)
            case_id = row["case_id"].strip()
            if not case_id or case_id in ids:
                raise ValueError(f"{path}: empty or duplicate case_id: {case_id!r}")
            ids.add(case_id)
            for key in ("user_input", "initial_assessment", "possible_consultation_response"):
                if not row[key].strip():
                    raise ValueError(f"{case_id}: {key} cannot be empty")
            for key in ("user_profile", "follow_ups"):
                try:
                    value = json.loads(row[key])
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{case_id}: invalid {key} JSON") from exc
                if key == "user_profile" and not isinstance(value, dict):
                    raise ValueError(f"{case_id}: user_profile must be an object")
                if key == "follow_ups" and (
                    not isinstance(value, list)
                    or len(value) > 2
                    or any(
                        not isinstance(item, dict)
                        or set(item) != {"question", "purpose"}
                        or any(
                            not isinstance(text, str) or not text.strip() for text in item.values()
                        )
                        for item in value
                    )
                ):
                    raise ValueError(
                        f"{case_id}: follow_ups must contain 0-2 question/purpose pairs"
                    )
            if row["candidate_safety_class"] not in SAFETY_LABELS and not (
                not row["candidate_safety_class"] and row.get("boundary_note", "").strip()
            ):
                raise ValueError(f"{case_id}: invalid candidate_safety_class")
            row["model_reasoning"] = row.get("model_reasoning", "") or row.get("reasoning", "")
            row["classifier_error"] = row.get("classifier_error", "") or row.get("error", "")
            if row["classifier_error"].strip():
                if row["predicted_safety_class"].strip() or row["model_reasoning"].strip():
                    raise ValueError(
                        f"{case_id}: engine run failed but contains a prediction or reasoning"
                    )
                row["engine_status"] = "FAILED"
            else:
                if row["predicted_safety_class"] not in SAFETY_LABELS:
                    raise ValueError(f"{case_id}: engine prediction is missing or invalid")
                if not row["model_reasoning"].strip():
                    raise ValueError(f"{case_id}: engine supplied no reasoning")
                row["engine_status"] = "SUCCESS"
            rows.append(row)
        return ProfileInput(source_format="medical-case-engine-results", rows=rows)

    def task_spec(self, mode: str) -> TaskSpec:
        self._validate_mode(mode)
        return TaskSpec(
            guidelines=GUIDELINES_PATH.read_text(encoding="utf-8"),
            fields=(
                FieldSpec("user_input", "用户输入", required=True),
                FieldSpec("user_profile", "用户画像", required=True, use_markdown=True),
                FieldSpec(
                    "candidate_materials",
                    "候选问诊材料 · 待审核",
                    required=True,
                    use_markdown=True,
                ),
                FieldSpec(
                    "model_assessment",
                    "引擎分级 · 供参考",
                    required=True,
                    use_markdown=True,
                ),
            ),
            questions=(
                QuestionSpec(
                    "label",
                    "expected_safety_class",
                    "人工审定安全分类（单选）",
                    description="结合问题和画像选择一类；涉及多类时，按最严格的安全要求选择。",
                    labels=SAFETY_LABELS,
                    required=True,
                    visible_labels=5,
                ),
                QuestionSpec(
                    "multi_label",
                    "boundary_status",
                    "边界状态（可多选）",
                    description="勾选所有适用状态；“明确”只能单独选择。",
                    labels=BOUNDARY_LABELS,
                    required=True,
                    visible_labels=4,
                ),
                QuestionSpec(
                    "multi_label",
                    "reason_codes",
                    "分类要点（可多选）",
                    labels=REASON_LABELS,
                    required=True,
                    visible_labels=8,
                ),
                QuestionSpec(
                    "text",
                    "medical_rationale",
                    "安全分类医学逻辑（选填）",
                    description="可用1-2句话补充选择该安全分类的关键事实和理由；不需要补充可留空。",
                    required=False,
                ),
                QuestionSpec(
                    "label",
                    "material_review",
                    "候选材料审核",
                    description="判断左侧材料是否合适。选“需要修订”时填写要改的部分；选“原样接受”时，下方修改项留空。",
                    labels={"ACCEPT": "原样接受", "REVISE": "需要修订", "EXCLUDE": "排除该用例"},
                    required=True,
                    visible_labels=3,
                ),
                QuestionSpec(
                    "text",
                    "confirmed_consultation_response",
                    "问诊回应的修改意见（选填）",
                    description="回复要改时，直接写你建议的回复。初步判断有误或需排除用例，也可在这里简述问题；不修改可留空。",
                ),
                QuestionSpec(
                    "text",
                    "confirmed_follow_ups",
                    "问诊追问修改（选填）",
                    description="直接用文字写，最多2条，每条写清问题和追问目的。"
                    "请写出修改后保留的全部追问；不修改留空，删除全部追问填“无需追问”。",
                ),
                QuestionSpec(
                    "label",
                    "needs_expert_adjudication",
                    "是否需要专家裁决（医生直接选否）",
                    description="医生直接选“否”；非医生不确定、需要专家判断时选“是”，其余选“否”。",
                    labels=YES_NO_LABELS,
                    required=True,
                ),
            ),
            metadata=tuple(
                MetadataSpec(
                    name,
                    name,
                    name in {"case_id", "id_prefix", "engine_status"},
                )
                for name in METADATA_NAMES
            ),
        )

    def record_spec(self, row: dict[str, str], mode: str) -> RecordSpec:
        self._validate_mode(mode)
        sections = [
            f"**候选分类：{_safety_label(row['candidate_safety_class'])}**",
            "以下为生成阶段的候选材料，尚未经医生审定。",
        ]
        if row.get("boundary_note", "").strip():
            sections.append("**边界说明：** " + _text(row["boundary_note"]))
        sections.extend(
            [
                "---",
                "### 初步判断及依据",
                _text(row["initial_assessment"]),
                "---",
                "### 可能问诊回应",
                _text(row["possible_consultation_response"]),
                "---",
                "### 必要追问",
                _follow_up_materials(row["follow_ups"]),
            ]
        )
        materials = "\n\n".join(sections)
        return RecordSpec(
            id=row["case_id"].strip(),
            fields={
                "user_input": row["user_input"],
                "user_profile": _profile_materials(row["user_profile"]),
                "candidate_materials": materials,
                "model_assessment": _engine_materials(row),
            },
            metadata={name: row[name] for name in METADATA_NAMES if row.get(name)},
        )

    def default_dataset_name(self, mode: str) -> str:
        self._validate_mode(mode)
        return f"{self.default_dataset_prefix}_v1"


PROFILE = CozieMedicalReviewProfile()
