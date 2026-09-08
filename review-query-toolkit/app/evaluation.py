"""Reproducible evaluation of single-label medical review exports, without diagnosis."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from app.dataset import SAFETY_LEVELS, ReviewDataset, normalize, parse_multi_value

Row = Mapping[str, str]
BOUNDARIES = {"CLEAR", "UNCLEAR", "INSUFFICIENT_INFO", "OUT_OF_SCOPE"}
REASONS = {
    "NON_HEALTH_OPERATION",
    "GENERAL_INFO",
    "PERSONAL_LOW_RISK",
    "GENERAL_MEDICAL",
    "INDIVIDUAL_CLINICAL",
    "EMERGENCY",
    "CONTEXT_INSUFFICIENT",
    "TAXONOMY_GAP",
}
REQUIRED = {
    "expected_safety_class",
    "predicted_safety_class",
    "candidate_safety_class",
    "response_status",
    "boundary_status",
    "reason_codes",
    "material_review",
    "needs_expert_adjudication",
    "confirmed_consultation_response",
    "confirmed_follow_ups",
}
ISSUE_LABELS = {
    "duplicate_response": "同一用例和审核人有重复提交，未自动选取版本",
    "missing_annotator": "缺少审核人",
    "invalid_human_label": "人工分类为空或不在五类中",
    "invalid_boundary": "边界状态为空或含未知值",
    "clear_with_other_boundary": "CLEAR 与其他边界状态同时选择",
    "invalid_reason_codes": "分类要点为空或含未知值",
    "invalid_material_review": "素材处置为空或含未知值",
    "invalid_expert_flag": "专家裁决状态为空或含未知值",
    "accept_with_edits": "原样接受但仍填写修改意见",
    "revise_without_edits": "需要修订但两个修改字段均为空",
    "exclude_without_reason_in_response": "排除原因未填写在规定的回应修改字段",
    "context_dependent_edit": "修改意见引用上文或上一版本，需要补全上下文",
    "follow_up_deletion_alias": "删除追问使用了“无需追问”以外的表达",
    "expert_requested": "已标记需要专家裁决",
    "reviewer_label_disagreement": "同一用例的审核人分类不一致",
    "inconsistent_case_input": "同一用例的原始输入或模型结果不一致",
}
METHOD = [
    "只分析 response_status=submitted。统计单位是审核响应；同一 case_id × 审核人重复提交全部暂缓，不任取第一条。",
    "全量分类结果仅对照有效的人工单选标签。缺失、非法或失败的引擎结果计入未命中，同时单列有效输出覆盖率与有效输出准确率。",
    "筛选分类集要求人工标签有效、边界仅 CLEAR、专家裁决 NO、素材处置 ACCEPT/REVISE、分类要点有效，且同用例无分类分歧或输入冲突。这是操作性筛选规则，不等于已完成最终裁决。",
    "素材是否需要修订与安全分类是否正确分别统计；REVISE 不自动排除出分类集。意见字段非空表示提出了修改或说明，不代表已形成完整定稿。",
    "多选分布按响应计数，每条同一标签只计一次，比例分母为响应数，合计可超过 100%。CLEAR 与其他状态共选按冲突记录。",
    "precision 无预测时为 null；recall 无人工样本时为 null。主表宏平均 F1 和平衡准确率均在人工有样本的同一组类别上平均，便于两模型对比；无预测但有人工样本的 F1 为 0。JSON 另列按人工或预测出现类别计算的 macro_f1_union。",
    "多数类基线在同一评估集合上计算，仅用于说明类别不平衡。restricted_medical 的误升与漏分是分类比较，不等同于急诊分诊结论。",
    "分组样本量与分母一并报告；对照组仅识别当前文件中每组两条不同用例的完整性，不从相同标签推断回复是否正确适应画像。",
    "内容规则只能发现结构与填写问题，不能核实医学事实。单人审核无法计算医生间一致性，选择性小样本不能直接外推线上表现。",
]


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def tags(row: Row, field: str) -> set[str]:
    return {item.strip().upper() for item in parse_multi_value(row.get(field, "")) if item.strip()}


def has_edits(row: Row) -> bool:
    return any(
        row.get(field, "").strip()
        for field in (
            "confirmed_consultation_response",
            "confirmed_follow_ups",
        )
    )


def row_key(row: Row) -> tuple[str, str]:
    return row["case_id"].strip(), normalize(row.get("annotator_username"))


def baseline_blocks(row: Row) -> list[str]:
    reasons = []
    if normalize(row.get("expected_safety_class")) not in SAFETY_LEVELS:
        reasons.append("invalid_human_label")
    if tags(row, "boundary_status") != {"CLEAR"}:
        reasons.append("boundary_not_clear_only")
    if normalize(row.get("needs_expert_adjudication")) != "no":
        reasons.append("expert_not_no")
    if normalize(row.get("material_review")) not in {"accept", "revise"}:
        reasons.append("material_not_accept_or_revise")
    if not tags(row, "reason_codes") or not tags(row, "reason_codes") <= REASONS:
        reasons.append("invalid_reason_codes")
    return reasons


def review_issues(row: Row) -> list[str]:
    issues = []
    boundary = tags(row, "boundary_status")
    if normalize(row.get("expected_safety_class")) not in SAFETY_LEVELS:
        issues.append("invalid_human_label")
    if not boundary or not boundary <= BOUNDARIES:
        issues.append("invalid_boundary")
    if "CLEAR" in boundary and len(boundary) > 1:
        issues.append("clear_with_other_boundary")
    if not tags(row, "reason_codes") or not tags(row, "reason_codes") <= REASONS:
        issues.append("invalid_reason_codes")
    material = normalize(row.get("material_review"))
    if material not in {"accept", "revise", "exclude"}:
        issues.append("invalid_material_review")
    if normalize(row.get("needs_expert_adjudication")) not in {"yes", "no"}:
        issues.append("invalid_expert_flag")
    if material == "accept" and has_edits(row):
        issues.append("accept_with_edits")
    if material == "revise" and not has_edits(row):
        issues.append("revise_without_edits")
    if material == "exclude" and not row.get("confirmed_consultation_response", "").strip():
        issues.append("exclude_without_reason_in_response")
    if any(
        re.search(r"同上|上一(?:版|版本)|之前回答过|同之前", row.get(field, ""))
        for field in (
            "confirmed_consultation_response",
            "confirmed_follow_ups",
        )
    ):
        issues.append("context_dependent_edit")
    follow_up = row.get("confirmed_follow_ups", "").strip().rstrip("。.!！")
    if follow_up in {"不需要追问", "不用追问", "无需再追问"}:
        issues.append("follow_up_deletion_alias")
    if normalize(row.get("needs_expert_adjudication")) == "yes":
        issues.append("expert_requested")
    return issues


def prediction(row: Row, field: str) -> str:
    value = normalize(row.get(field))
    status = normalize(row.get("engine_status"))
    if field == "predicted_safety_class" and status and status != "success":
        return "(missing_or_invalid)"
    return value if value in SAFETY_LEVELS else "(missing_or_invalid)"


def classification(rows: Sequence[Row], field: str) -> dict[str, Any]:
    labeled = [row for row in rows if normalize(row.get("expected_safety_class")) in SAFETY_LEVELS]
    matrix = Counter(
        (normalize(row["expected_safety_class"]), prediction(row, field)) for row in labeled
    )
    support = Counter(normalize(row["expected_safety_class"]) for row in labeled)
    predicted = Counter(prediction(row, field) for row in labeled)
    correct = sum(matrix[label, label] for label in SAFETY_LEVELS)
    valid_predictions = sum(predicted[label] for label in SAFETY_LEVELS)
    metrics = []
    for label in SAFETY_LEVELS:
        tp = matrix[label, label]
        metrics.append(
            {
                "label": label,
                "support": support[label],
                "predicted": predicted[label],
                "tp": tp,
                "precision": ratio(tp, predicted[label]),
                "recall": ratio(tp, support[label]),
                "f1": ratio(2 * tp, support[label] + predicted[label]),
            }
        )
    active = [item for item in metrics if item["support"]]
    union = [item for item in metrics if item["support"] or item["predicted"]]
    recalls = [item["recall"] for item in metrics if item["support"]]
    restricted = "restricted_medical"
    tp = matrix[restricted, restricted]
    false_positive = sum(
        count
        for (truth, pred), count in matrix.items()
        if pred == restricted and truth != restricted
    )
    false_negative = support[restricted] - tp
    return {
        "reference_field": field,
        "rows": len(rows),
        "labeled_rows": len(labeled),
        "invalid_human_rows": len(rows) - len(labeled),
        "correct": correct,
        "accuracy": ratio(correct, len(labeled)),
        "valid_predictions": valid_predictions,
        "prediction_coverage": ratio(valid_predictions, len(labeled)),
        "accuracy_on_valid_predictions": ratio(correct, valid_predictions),
        "macro_f1": sum(item["f1"] for item in active) / len(active) if active else None,
        "macro_f1_labels": [item["label"] for item in active],
        "macro_f1_union": sum(item["f1"] for item in union) / len(union) if union else None,
        "balanced_accuracy": sum(recalls) / len(recalls) if recalls else None,
        "majority_class": support.most_common(1)[0][0] if support else None,
        "majority_baseline_accuracy": ratio(max(support.values(), default=0), len(labeled)),
        "per_class": metrics,
        "confusion": [
            {"human": truth, "prediction": pred, "count": count}
            for (truth, pred), count in sorted(matrix.items())
        ],
        "restricted": {
            "tp": tp,
            "fp": false_positive,
            "fn": false_negative,
            "precision": ratio(tp, predicted[restricted]),
            "recall": ratio(tp, support[restricted]),
            "false_positive_rate": ratio(false_positive, len(labeled) - support[restricted]),
        },
        "errors": [
            {
                "case_id": row["case_id"],
                "annotator": row["annotator_username"],
                "human": normalize(row["expected_safety_class"]),
                "prediction": prediction(row, field),
            }
            for row in labeled
            if normalize(row["expected_safety_class"]) != prediction(row, field)
        ],
    }


def distribution(rows: Sequence[Row], field: str, *, multi: bool = False) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for row in rows:
        values = tags(row, field) if multi else {row.get(field, "").strip()}
        counts.update(values or {"(blank)"})
    return [
        {"value": value or "(blank)", "count": count, "rate": ratio(count, len(rows))}
        for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def material_report(rows: Sequence[Row]) -> dict[str, Any]:
    accepts = [row for row in rows if normalize(row.get("material_review")) == "accept"]
    revised = [row for row in rows if normalize(row.get("material_review")) == "revise"]
    edit_matrix = Counter(
        (
            bool(row.get("confirmed_consultation_response", "").strip()),
            bool(row.get("confirmed_follow_ups", "").strip()),
        )
        for row in revised
    )
    groups = []
    for match in (True, False):
        selected = [
            row
            for row in rows
            if normalize(row.get("expected_safety_class")) in SAFETY_LEVELS
            and (
                normalize(row["expected_safety_class"]) == prediction(row, "predicted_safety_class")
            )
            == match
        ]
        groups.append(
            {
                "engine_matches_human": match,
                "rows": len(selected),
                "decisions": distribution(selected, "material_review"),
            }
        )
    clean = [row for row in accepts if not has_edits(row)]
    return {
        "rows": len(rows),
        "decisions": distribution(rows, "material_review"),
        "accept_without_edits": len(clean),
        "accept_without_edits_rate": ratio(len(clean), len(rows)),
        "accept_with_edits": len(accepts) - len(clean),
        "any_edit_text": sum(has_edits(row) for row in rows),
        "response_edit_text": sum(
            bool(row.get("confirmed_consultation_response", "").strip()) for row in rows
        ),
        "follow_up_edit_text": sum(
            bool(row.get("confirmed_follow_ups", "").strip()) for row in rows
        ),
        "rationale_text": sum(bool(row.get("medical_rationale", "").strip()) for row in rows),
        "revision_edit_matrix": [
            {
                "response_edit": response,
                "follow_up_edit": follow,
                "count": edit_matrix[response, follow],
            }
            for response, follow in ((True, True), (True, False), (False, True), (False, False))
        ],
        "engine_match_by_material": groups,
        "engine_correct_and_accept_without_edits": sum(
            normalize(row.get("expected_safety_class")) == prediction(row, "predicted_safety_class")
            for row in clean
        ),
    }


def comparison_report(rows: Sequence[Row]) -> dict[str, Any]:
    cells: Counter[str] = Counter()
    changes = []
    for row in rows:
        truth = normalize(row.get("expected_safety_class"))
        if truth not in SAFETY_LEVELS:
            continue
        candidate_ok = prediction(row, "candidate_safety_class") == truth
        engine_ok = prediction(row, "predicted_safety_class") == truth
        key = (
            "both_correct"
            if candidate_ok and engine_ok
            else "both_wrong"
            if not candidate_ok and not engine_ok
            else "engine_corrected_candidate"
            if engine_ok
            else "engine_regressed"
        )
        cells[key] += 1
        if candidate_ok != engine_ok:
            changes.append(
                {"case_id": row["case_id"], "annotator": row["annotator_username"], "change": key}
            )
    return {
        "counts": {
            key: cells[key]
            for key in (
                "both_correct",
                "both_wrong",
                "engine_corrected_candidate",
                "engine_regressed",
            )
        },
        "net_correct_gain": cells["engine_corrected_candidate"] - cells["engine_regressed"],
        "changed_cases": changes,
    }


def evaluate(dataset: ReviewDataset, group_fields: Sequence[str] | None = None) -> dict[str, Any]:
    missing = REQUIRED - set(dataset.columns)
    if missing:
        raise ValueError("evaluate requires medical-review columns: " + ", ".join(sorted(missing)))
    group_fields = (
        list(group_fields)
        if group_fields is not None
        else [
            field
            for field in (
                "id_prefix",
                "expected_safety_class",
                "predicted_safety_class",
                "annotator_username",
            )
            if field in dataset.columns
        ]
    )
    for field in group_fields:
        if field not in dataset.columns:
            raise ValueError(f"unknown grouping column: {field}")
    submitted = [
        row for row in dataset.rows if normalize(row.get("response_status")) == "submitted"
    ]
    keys = Counter(row_key(row) for row in submitted)
    analysis_rows = [row for row in submitted if keys[row_key(row)] == 1 and row_key(row)[1]]
    by_case: dict[str, list[Row]] = defaultdict(list)
    for row in analysis_rows:
        by_case[row["case_id"].strip()].append(row)
    conflict_cases = set()
    input_conflict_cases = set()
    for case_id, rows in by_case.items():
        if len({normalize(row.get("expected_safety_class")) for row in rows}) > 1:
            conflict_cases.add(case_id)
        if any(
            len({row.get(field, "") for row in rows}) > 1
            for field in (
                "user_input",
                "user_profile",
                "candidate_materials",
                "candidate_safety_class",
                "predicted_safety_class",
                "engine_status",
            )
        ):
            input_conflict_cases.add(case_id)
    eligible = []
    issues = []
    blocks = []
    for row in submitted:
        row_issues = review_issues(row)
        row_blocks = baseline_blocks(row)
        if keys[row_key(row)] > 1:
            row_issues.append("duplicate_response")
            row_blocks.append("duplicate_response")
        if not row_key(row)[1]:
            row_issues.append("missing_annotator")
            row_blocks.append("missing_annotator")
        for cases, issue in (
            (conflict_cases, "reviewer_label_disagreement"),
            (input_conflict_cases, "inconsistent_case_input"),
        ):
            if row["case_id"].strip() in cases:
                row_issues.append(issue)
                row_blocks.append(issue)
        if not row_blocks:
            eligible.append(row)
        else:
            blocks.append(
                {
                    "case_id": row["case_id"],
                    "annotator": row["annotator_username"],
                    "reasons": row_blocks,
                }
            )
        for issue in row_issues:
            issues.append(
                {
                    "case_id": row["case_id"],
                    "annotator": row["annotator_username"],
                    "issue": issue,
                    "description": ISSUE_LABELS[issue],
                }
            )
    groups = []
    eligible_keys = {row_key(row) for row in eligible}
    for field in group_fields:
        for value in sorted({row.get(field, "").strip() for row in analysis_rows}):
            rows = [row for row in analysis_rows if row.get(field, "").strip() == value]
            engine = classification(rows, "predicted_safety_class")
            candidate = classification(rows, "candidate_safety_class")
            decisions = Counter(normalize(row["material_review"]) for row in rows)
            groups.append(
                {
                    "field": field,
                    "value": value or "(blank)",
                    "rows": len(rows),
                    "labeled_rows": engine["labeled_rows"],
                    "engine_correct": engine["correct"],
                    "engine_accuracy": engine["accuracy"],
                    "candidate_accuracy": candidate["accuracy"],
                    "accept": decisions["accept"],
                    "revise": decisions["revise"],
                    "exclude": decisions["exclude"],
                    "accept_without_edits": sum(
                        normalize(row["material_review"]) == "accept" and not has_edits(row)
                        for row in rows
                    ),
                    "eligible_rows": sum(row_key(row) in eligible_keys for row in rows),
                }
            )
    pair_groups: dict[str, set[str]] = defaultdict(set)
    for row in analysis_rows:
        if row.get("pair_key", "").strip():
            pair_groups[row["pair_key"].strip()].add(row["case_id"])
    return {
        "source": str(dataset.source.resolve()),
        "methodology": METHOD,
        "population": {
            "input_rows": len(dataset.rows),
            "submitted_rows": len(submitted),
            "analysis_rows": len(analysis_rows),
            "unique_cases": len(by_case),
            "annotators": len({row_key(row)[1] for row in analysis_rows}),
            "duplicate_response_keys": sum(count > 1 for count in keys.values()),
            "excluded_duplicate_or_anonymous_rows": len(submitted) - len(analysis_rows),
            "eligible_classification_rows": len(eligible),
            "blocked_rows": len(blocks),
        },
        "classification": {
            "all_submitted": {
                "engine": classification(analysis_rows, "predicted_safety_class"),
                "candidate": classification(analysis_rows, "candidate_safety_class"),
            },
            "eligible": {
                "engine": classification(eligible, "predicted_safety_class"),
                "candidate": classification(eligible, "candidate_safety_class"),
            },
        },
        "comparison": {
            "all_submitted": comparison_report(analysis_rows),
            "eligible": comparison_report(eligible),
        },
        "materials": material_report(analysis_rows),
        "distributions": {
            field: distribution(
                analysis_rows, field, multi=field in {"boundary_status", "reason_codes"}
            )
            for field in (
                "expected_safety_class",
                "boundary_status",
                "reason_codes",
                "needs_expert_adjudication",
                "engine_status",
            )
            if field in dataset.columns
        },
        "groups": groups,
        "baseline_blocks": blocks,
        "issues": issues,
        "issue_counts": dict(Counter(item["issue"] for item in issues)),
        "pair_coverage": [
            {
                "pair_key": key,
                "case_count": len(ids),
                "complete_two_case_pair": len(ids) == 2,
                "case_ids": sorted(ids),
                "eligible_case_ids": sorted(
                    {row["case_id"] for row in eligible if row["case_id"] in ids}
                ),
            }
            for key, ids in sorted(pair_groups.items())
        ],
    }


def _percent(value: float | None) -> str:
    return "n.a." if value is None else f"{value:.1%}"


def _table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    def escape(value: object) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")

    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(escape(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def render_markdown(report: Mapping[str, Any]) -> str:
    """Readable report using the same computed results as JSON; no medical text generation."""
    population = report["population"]
    parts = [
        "# 医生审核多维评估",
        f"来源：`{report['source']}`",
        f"已提交 {population['submitted_rows']} 条；纳入统计 {population['analysis_rows']} 条响应，"
        f"{population['unique_cases']} 个用例、{population['annotators']} 位审核人。"
        f"符合分类筛选规则 {population['eligible_classification_rows']} 条。",
        "## 分类结果",
        "全量对照包含暂定或待裁决标签；筛选集的规则见文末。",
    ]
    parts.append(
        _table(
            [
                "口径",
                "模型来源",
                "命中/人工有效数",
                "准确率",
                "宏平均 F1",
                "平衡准确率",
                "多数类基线",
            ],
            [
                [
                    scope,
                    model,
                    f"{metrics['correct']}/{metrics['labeled_rows']}",
                    _percent(metrics["accuracy"]),
                    _percent(metrics["macro_f1"]),
                    _percent(metrics["balanced_accuracy"]),
                    _percent(metrics["majority_baseline_accuracy"]),
                ]
                for scope, models in report["classification"].items()
                for model, metrics in models.items()
            ],
        )
    )
    engine = report["classification"]["all_submitted"]["engine"]
    parts.extend(
        [
            "### 引擎各分类表现（全量）",
            _table(
                ["人工类别", "人工数", "预测数", "命中", "Precision", "Recall", "F1"],
                [
                    [
                        item["label"],
                        item["support"],
                        item["predicted"],
                        item["tp"],
                        _percent(item["precision"]),
                        _percent(item["recall"]),
                        _percent(item["f1"]),
                    ]
                    for item in engine["per_class"]
                ],
            ),
            "### 引擎混淆明细（全量）",
            _table(
                ["人工分类", "引擎分类", "条数"],
                [
                    [item["human"], item["prediction"], item["count"]]
                    for item in engine["confusion"]
                ],
            ),
        ]
    )
    restricted = engine["restricted"]
    parts.append(
        f"restricted_medical：命中 {restricted['tp']}，误升 {restricted['fp']}，漏分 {restricted['fn']}；"
        f"Precision {_percent(restricted['precision'])}，Recall {_percent(restricted['recall'])}。"
        f"引擎有效输出覆盖率 {_percent(engine['prediction_coverage'])}。"
    )
    parts.extend(
        [
            "### 候选分类与引擎的变化",
            _table(
                ["口径", "两者均对", "两者均错", "引擎纠正", "引擎退步", "净增加命中"],
                [
                    [
                        scope,
                        *[
                            data["counts"][key]
                            for key in (
                                "both_correct",
                                "both_wrong",
                                "engine_corrected_candidate",
                                "engine_regressed",
                            )
                        ],
                        data["net_correct_gain"],
                    ]
                    for scope, data in report["comparison"].items()
                ],
            ),
        ]
    )
    materials = report["materials"]
    parts.extend(
        [
            "## 候选材料与修改意见",
            _table(
                ["素材处置", "条数", "占比"],
                [
                    [item["value"], item["count"], _percent(item["rate"])]
                    for item in materials["decisions"]
                ],
            ),
            f"ACCEPT 且无修改意见 {materials['accept_without_edits']} 条（{_percent(materials['accept_without_edits_rate'])}）；"
            f"ACCEPT 但有修改意见 {materials['accept_with_edits']} 条。"
            f"回应修改字段非空 {materials['response_edit_text']} 条，追问修改字段非空 {materials['follow_up_edit_text']} 条，"
            f"至少一个修改字段非空 {materials['any_edit_text']} 条，分类医学逻辑非空 {materials['rationale_text']} 条。",
            _table(
                ["REVISE 回应字段非空", "追问字段非空", "条数"],
                [
                    [item["response_edit"], item["follow_up_edit"], item["count"]]
                    for item in materials["revision_edit_matrix"]
                ],
            ),
            _table(
                ["引擎分类与医生一致", "总数", "素材处置", "条数", "组内占比"],
                [
                    [
                        group["engine_matches_human"],
                        group["rows"],
                        item["value"],
                        item["count"],
                        _percent(item["rate"]),
                    ]
                    for group in materials["engine_match_by_material"]
                    for item in group["decisions"]
                ],
            ),
            f"引擎分类正确且 ACCEPT 无修改意见：{materials['engine_correct_and_accept_without_edits']} 条。"
            "这只是字段交集，不代表材料已完成医学核验。",
        ]
    )
    parts.append("## 分布与分组")
    for field, values in report["distributions"].items():
        parts.extend(
            [
                f"### {field}",
                _table(
                    ["取值", "条数", "响应占比"],
                    [[item["value"], item["count"], _percent(item["rate"])] for item in values],
                ),
            ]
        )
    for field in dict.fromkeys(item["field"] for item in report["groups"]):
        parts.extend(
            [
                f"### 按 {field} 分组",
                _table(
                    [
                        "分组",
                        "样本",
                        "引擎命中/有效人工数",
                        "引擎准确率",
                        "候选准确率",
                        "接受",
                        "修订",
                        "排除",
                        "无意见接受",
                        "分类筛选数",
                    ],
                    [
                        [
                            item["value"],
                            item["rows"],
                            f"{item['engine_correct']}/{item['labeled_rows']}",
                            _percent(item["engine_accuracy"]),
                            _percent(item["candidate_accuracy"]),
                            item["accept"],
                            item["revise"],
                            item["exclude"],
                            item["accept_without_edits"],
                            item["eligible_rows"],
                        ]
                        for item in report["groups"]
                        if item["field"] == field
                    ],
                ),
            ]
        )
    parts.extend(
        [
            "## 待整理事项（可重叠）",
            _table(
                ["问题", "响应数", "用例"],
                [
                    [
                        ISSUE_LABELS[issue],
                        count,
                        "、".join(
                            sorted(
                                {
                                    item["case_id"]
                                    for item in report["issues"]
                                    if item["issue"] == issue
                                }
                            )
                        ),
                    ]
                    for issue, count in report["issue_counts"].items()
                ],
            ),
            "### 未纳入分类筛选集",
            _table(
                ["用例", "审核人", "原因"],
                [
                    [item["case_id"], item["annotator"], ", ".join(item["reasons"])]
                    for item in report["baseline_blocks"]
                ],
            ),
            "### 引擎分类差异清单（全量）",
            _table(
                ["用例", "审核人", "人工分类", "引擎分类"],
                [
                    [item["case_id"], item["annotator"], item["human"], item["prediction"]]
                    for item in engine["errors"]
                ],
            ),
            "## 对照用例覆盖",
            _table(
                ["对照组", "不同用例数", "当前两条齐全", "用例", "分类筛选保留用例"],
                [
                    [
                        item["pair_key"],
                        item["case_count"],
                        item["complete_two_case_pair"],
                        "、".join(item["case_ids"]),
                        "、".join(item["eligible_case_ids"]),
                    ]
                    for item in report["pair_coverage"]
                ],
            ),
            "## 统计口径与限制",
            "\n".join(f"{index}. {line}" for index, line in enumerate(report["methodology"], 1)),
        ]
    )
    return "\n\n".join(parts) + "\n"
