"""Loading, filtering, comparing, and summarizing review CSV data."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

SAFETY_LEVELS = (
    "non_health",
    "general_health",
    "personalized_health",
    "general_medical",
    "restricted_medical",
)
SAFETY_LEVEL_RANK = {label: index for index, label in enumerate(SAFETY_LEVELS, start=1)}

QUESTION_FIELDS = (
    "medical_review_label",
    "expected_safety_class",
    "boundary_status",
    "reason_codes",
    "material_review",
    "needs_expert_adjudication",
)
MULTI_VALUE_FIELDS = {"medical_review_label", "boundary_status", "reason_codes"}
DEFAULT_SEARCH_FIELDS = (
    "case_id",
    "user_input",
    "review_context",
    "model_assessment",
    "medical_rationale",
    "user_profile",
    "candidate_materials",
    "confirmed_consultation_response",
    "confirmed_follow_ups",
)


def normalize(value: object) -> str:
    """Normalize a scalar for case-insensitive matching."""

    return str(value or "").strip().casefold()


def parse_multi_value(value: object) -> tuple[str, ...]:
    """Decode an exported JSON list, or treat a scalar as one value."""

    text = str(value or "").strip()
    if not text:
        return ()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return (text,)
        if isinstance(parsed, list):
            return tuple(str(item) for item in parsed)
    return (text,)


def compare_value(field: str, value: object) -> tuple[str, ...] | str:
    """Return a canonical representation used for equality and agreement."""

    if field in MULTI_VALUE_FIELDS:
        return tuple(sorted({normalize(item) for item in parse_multi_value(value)}))
    return normalize(value)


def _reference_matches(reference: object, review: object, review_field: str) -> bool:
    """Match a reference value against a review answer."""

    if review_field in MULTI_VALUE_FIELDS:
        reference_values = {
            normalize(item) for item in parse_multi_value(reference) if normalize(item)
        }
        review_values = {normalize(item) for item in parse_multi_value(review) if normalize(item)}
        if not reference_values:
            return not review_values
        return reference_values <= review_values
    return compare_value(review_field, reference) == compare_value(review_field, review)


def strict_safety_level(value: object) -> int:
    """Return the strictest selected safety level using the project taxonomy."""

    return max(
        (SAFETY_LEVEL_RANK.get(normalize(item), 0) for item in parse_multi_value(value)),
        default=0,
    )


def _status_is_submitted(row: Mapping[str, str]) -> bool:
    status = row.get("response_status", "")
    return not status or normalize(status) == "submitted"


@dataclass(frozen=True)
class ReviewDataset:
    """An in-memory, ordered representation of a review CSV."""

    source: Path
    columns: tuple[str, ...]
    rows: tuple[dict[str, str], ...]

    @classmethod
    def from_csv(cls, path: Path) -> ReviewDataset:
        if not path.exists():
            raise FileNotFoundError(f"input CSV not found: {path}")
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            raw_columns = reader.fieldnames or []
            columns = tuple(str(column or "").strip() for column in raw_columns)
            if not columns or any(not column for column in columns):
                raise ValueError("input CSV must contain a non-empty header")
            if len(set(columns)) != len(columns):
                raise ValueError("input CSV contains duplicate column names")
            missing = {"case_id", "annotator_username"} - set(columns)
            if missing:
                raise ValueError(
                    "input CSV is missing required columns: " + ", ".join(sorted(missing))
                )
            rows: list[dict[str, str]] = []
            for line_number, raw_row in enumerate(reader, start=2):
                if None in raw_row:
                    raise ValueError(f"row {line_number} has more values than header columns")
                row = {
                    column: raw_row.get(raw_column, "") or ""
                    for column, raw_column in zip(columns, raw_columns, strict=True)
                }
                if not normalize(row["case_id"]):
                    raise ValueError(f"row {line_number} has an empty case_id")
                rows.append(row)
        if not rows:
            raise ValueError(f"input CSV contains no data rows: {path}")
        return cls(source=path, columns=columns, rows=tuple(rows))

    def case_groups(self) -> dict[str, list[dict[str, str]]]:
        """Group rows by case_id while preserving first-seen case order."""

        groups: dict[str, list[dict[str, str]]] = {}
        for row in self.rows:
            case_id = row["case_id"].strip()
            groups.setdefault(case_id, []).append(row)
        return groups

    def submitted_case_groups(self) -> dict[str, list[dict[str, str]]]:
        return {
            case_id: [row for row in rows if _status_is_submitted(row)]
            for case_id, rows in self.case_groups().items()
        }

    def paired_cases(self) -> dict[str, list[dict[str, str]]]:
        """Return cases with submitted responses from at least two annotators."""

        result: dict[str, list[dict[str, str]]] = {}
        for case_id, rows in self.submitted_case_groups().items():
            annotators = {normalize(row.get("annotator_username")) for row in rows}
            annotators.discard("")
            if len(annotators) >= 2:
                result[case_id] = rows
        return result

    def paired_case_ids(self) -> set[str]:
        return set(self.paired_cases())

    def _pair(
        self, rows: Sequence[Mapping[str, str]]
    ) -> tuple[dict[str, str], dict[str, str]] | None:
        by_annotator: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            if not _status_is_submitted(row):
                continue
            username = row.get("annotator_username", "").strip()
            if username:
                by_annotator[username].append(dict(row))
        annotators = sorted(by_annotator, key=str.casefold)
        if len(annotators) < 2:
            return None
        return by_annotator[annotators[0]][0], by_annotator[annotators[1]][0]

    def disagreement_fields(self, rows: Sequence[Mapping[str, str]]) -> list[str]:
        pair = self._pair(rows)
        if pair is None:
            return []
        first, second = pair
        return [
            field
            for field in QUESTION_FIELDS
            if field in self.columns
            and compare_value(field, first.get(field, ""))
            != compare_value(field, second.get(field, ""))
        ]

    def disagreement_case_ids(self, field: str = "any") -> set[str]:
        if field != "any" and field not in QUESTION_FIELDS:
            raise ValueError(f"unsupported disagreement field: {field}")
        result = set()
        for case_id, rows in self.paired_cases().items():
            fields = self.disagreement_fields(rows)
            if (field == "any" and fields) or (field != "any" and field in fields):
                result.add(case_id)
        return result

    def agreement_report(self) -> dict[str, object]:
        paired = self.paired_cases()
        fields: dict[str, dict[str, object]] = {}
        for field in QUESTION_FIELDS:
            if field not in self.columns:
                continue
            compared = 0
            agree = 0
            for rows in paired.values():
                pair = self._pair(rows)
                if pair is None:
                    continue
                compared += 1
                if compare_value(field, pair[0].get(field, "")) == compare_value(
                    field, pair[1].get(field, "")
                ):
                    agree += 1
            fields[field] = {
                "agree": agree,
                "disagree": compared - agree,
                "compared": compared,
                "rate": agree / compared if compared else None,
            }

        all_agree = sum(
            bool(self._pair(rows)) and not self.disagreement_fields(rows)
            for rows in paired.values()
        )
        strict_level_agree = 0
        safety_field = (
            "medical_review_label"
            if "medical_review_label" in self.columns
            else "expected_safety_class"
        )
        for rows in paired.values():
            pair = self._pair(rows)
            if pair is None or safety_field not in self.columns:
                continue
            if strict_safety_level(pair[0].get(safety_field)) == strict_safety_level(
                pair[1].get(safety_field)
            ):
                strict_level_agree += 1

        rationale_counts = Counter()
        expert_counts = Counter()
        for rows in paired.values():
            pair = self._pair(rows)
            if pair is None:
                continue
            for row in pair:
                username = row.get("annotator_username", "")
                if row.get("medical_rationale", "").strip():
                    rationale_counts[username] += 1
                if row.get("needs_expert_adjudication", ""):
                    expert_counts[
                        (username, normalize(row["needs_expert_adjudication"]).upper())
                    ] += 1

        return {
            "paired_cases": len(paired),
            "paired_rows": sum(len(rows) for rows in paired.values()),
            "fields": fields,
            "all_question_fields_agree": all_agree,
            "all_question_fields_agreement_rate": all_agree / len(paired) if paired else None,
            "strict_safety_level_agree": strict_level_agree,
            "strict_safety_level_agreement_rate": strict_level_agree / len(paired)
            if paired
            else None,
            "rationale_nonempty_by_annotator": dict(sorted(rationale_counts.items())),
            "expert_flag_by_annotator": {
                username: dict(sorted(counts.items()))
                for username, counts in _nested_counter(expert_counts).items()
            },
        }

    def reference_agreement_report(
        self,
        reference_field: str = "predicted_safety_class",
        review_field: str | None = None,
    ) -> dict[str, object]:
        """Compare a reference-engine field with each annotator's answer.

        For multi-value review fields, a scalar reference value is considered a
        match when it is included in the annotator's selected values. This fits
        the safety-class reference prediction versus the multi-select review
        label used by the source dataset.
        """

        review_field = review_field or (
            "medical_review_label"
            if "medical_review_label" in self.columns
            else "expected_safety_class"
        )
        for field in (reference_field, review_field):
            if field not in self.columns:
                raise ValueError(f"unknown CSV column: {field}")

        paired = self.paired_cases()
        annotator_stats: dict[str, dict[str, int]] = defaultdict(
            lambda: {"agree": 0, "disagree": 0, "compared": 0}
        )
        all_reviewers_agree = 0
        inconsistent_reference_cases = 0

        skipped = 0
        for row in self.rows:
            if not _status_is_submitted(row):
                continue
            if not row.get(reference_field, "").strip() or not parse_multi_value(
                row.get(review_field, "")
            ):
                skipped += 1
                continue
            matches = _reference_matches(row[reference_field], row[review_field], review_field)
            stats = annotator_stats[row.get("annotator_username", "")]
            stats["compared"] += 1
            stats["agree" if matches else "disagree"] += 1

        for rows in paired.values():
            pair = self._pair(rows)
            if pair is None:
                continue

            submitted_rows = [row for row in rows if _status_is_submitted(row)]
            reference_values = {
                compare_value(reference_field, row.get(reference_field, ""))
                for row in submitted_rows
            }
            if len(reference_values) > 1:
                inconsistent_reference_cases += 1
            reference_value = pair[0].get(reference_field, "")
            pair_agrees = []
            for row in pair:
                matches = _reference_matches(
                    reference_value, row.get(review_field, ""), review_field
                ) and bool(reference_value.strip() and parse_multi_value(row.get(review_field)))
                pair_agrees.append(matches)
            if pair_agrees and all(pair_agrees):
                all_reviewers_agree += 1

        compared = len(paired)
        return {
            "reference_field": reference_field,
            "review_field": review_field,
            "unit": "submitted_response",
            "compared_responses": sum(stats["compared"] for stats in annotator_stats.values()),
            "skipped_missing_responses": skipped,
            "paired_cases": compared,
            "inconsistent_reference_cases": inconsistent_reference_cases,
            "annotators": {
                username: {
                    **stats,
                    "rate": stats["agree"] / stats["compared"] if stats["compared"] else None,
                }
                for username, stats in sorted(annotator_stats.items())
            },
            "all_reviewers_agree": all_reviewers_agree,
            "all_reviewers_agreement_rate": all_reviewers_agree / compared if compared else None,
        }

    def summary(self) -> dict[str, object]:
        groups = self.case_groups()
        paired = self.paired_cases()
        missing = {
            column: count
            for column in self.columns
            if (count := sum(not row[column].strip() for row in self.rows))
        }
        return {
            "source": str(self.source),
            "rows": len(self.rows),
            "case_ids": len(groups),
            "paired_case_ids": len(paired),
            "single_response_case_ids": sum(
                len({row.get("annotator_username", "") for row in rows}) < 2
                for rows in groups.values()
            ),
            "annotators": dict(
                sorted(Counter(row["annotator_username"] for row in self.rows).items())
            ),
            "response_statuses": dict(
                sorted(Counter(row.get("response_status", "") for row in self.rows).items())
            ),
            "columns": list(self.columns),
            "missing_values": missing,
        }


def _nested_counter(values: Counter[tuple[str, str]]) -> dict[str, Counter[str]]:
    nested: dict[str, Counter[str]] = defaultdict(Counter)
    for (username, value), count in values.items():
        nested[username][value] += count
    return nested


def parse_assignment(raw: str) -> tuple[str, str]:
    """Parse FIELD=VALUE arguments without splitting values after the first equals sign."""

    if "=" not in raw:
        raise ValueError(f"expected FIELD=VALUE, got {raw!r}")
    field, value = raw.split("=", 1)
    field = field.strip()
    if not field:
        raise ValueError(f"field cannot be empty in {raw!r}")
    return field, value


def filter_rows(
    dataset: ReviewDataset,
    *,
    case_ids: Iterable[str] = (),
    annotators: Iterable[str] = (),
    equals: Mapping[str, str] | None = None,
    contains: Mapping[str, str] | None = None,
    labels: Mapping[str, str] | None = None,
    search: str = "",
    missing: Iterable[str] = (),
    completed_only: bool = False,
    disagreement: str | None = None,
) -> list[dict[str, str]]:
    """Filter rows while keeping the source order."""

    case_id_set = {value.strip() for value in case_ids if value.strip()}
    annotator_set = {normalize(value) for value in annotators if normalize(value)}
    equals = equals or {}
    contains = contains or {}
    labels = labels or {}
    missing_set = set(missing)
    for field in (*equals, *contains, *labels, *missing_set):
        if field not in dataset.columns:
            raise ValueError(f"unknown CSV column: {field}")

    allowed_cases = dataset.paired_case_ids() if completed_only else None
    if disagreement is not None:
        allowed_disagreement = dataset.disagreement_case_ids(disagreement)
        allowed_cases = (
            allowed_disagreement if allowed_cases is None else allowed_cases & allowed_disagreement
        )
    search_text = normalize(search)
    search_fields = [field for field in DEFAULT_SEARCH_FIELDS if field in dataset.columns]

    selected: list[dict[str, str]] = []
    for row in dataset.rows:
        row_case_id = row["case_id"].strip()
        if case_id_set and row_case_id not in case_id_set:
            continue
        if allowed_cases is not None and row_case_id not in allowed_cases:
            continue
        if annotator_set and normalize(row["annotator_username"]) not in annotator_set:
            continue
        if any(normalize(row[field]) != normalize(value) for field, value in equals.items()):
            continue
        if any(normalize(value) not in normalize(row[field]) for field, value in contains.items()):
            continue
        if any(
            normalize(value) not in {normalize(item) for item in parse_multi_value(row[field])}
            for field, value in labels.items()
        ):
            continue
        if any(bool(row[field].strip()) for field in missing_set):
            continue
        if search_text and not any(search_text in normalize(row[field]) for field in search_fields):
            continue
        selected.append(dict(row))
    return selected


def case_views(
    dataset: ReviewDataset, rows: Sequence[Mapping[str, str]]
) -> list[dict[str, object]]:
    """Collapse selected row results into one inspectable row per case."""

    selected_ids = {row["case_id"].strip() for row in rows}
    views: list[dict[str, object]] = []
    for case_id, group in dataset.case_groups().items():
        if case_id not in selected_ids:
            continue
        annotators = sorted(
            {
                row.get("annotator_username", "").strip()
                for row in group
                if row.get("annotator_username", "").strip()
            },
            key=str.casefold,
        )
        disagreement_fields = dataset.disagreement_fields(group)
        first = group[0]
        views.append(
            {
                "case_id": case_id,
                "response_rows": len(group),
                "annotators": annotators,
                "disagreement_fields": disagreement_fields,
                "sub_capability": first.get("sub_capability", ""),
                "priority": first.get("priority", ""),
                "difficulty": first.get("difficulty", ""),
                "predicted_safety_class": first.get("predicted_safety_class", ""),
                "expected_safety_class": first.get("expected_safety_class", ""),
                "user_input": first.get("user_input", ""),
            }
        )
    return views


def disagreement_views(dataset: ReviewDataset, field: str = "any") -> list[dict[str, object]]:
    """Return one compact row per paired case with differing answers."""

    if field != "any" and field not in QUESTION_FIELDS:
        raise ValueError(f"unsupported disagreement field: {field}")
    result: list[dict[str, object]] = []
    for case_id, group in dataset.paired_cases().items():
        pair = dataset._pair(group)
        fields = dataset.disagreement_fields(group)
        if pair is None or not fields or (field != "any" and field not in fields):
            continue
        first, second = pair
        annotator_values = {}
        for row in pair:
            username = row.get("annotator_username", "")
            annotator_values[username] = {name: row.get(name, "") for name in fields}
        result.append(
            {
                "case_id": case_id,
                "annotators": [
                    first.get("annotator_username", ""),
                    second.get("annotator_username", ""),
                ],
                "disagreement_fields": fields,
                "values_by_annotator": annotator_values,
                "user_input": first.get("user_input", ""),
            }
        )
    return result


def group_counts(
    dataset: ReviewDataset,
    field: str,
    *,
    rows: Sequence[Mapping[str, str]] | None = None,
    unit: str = "rows",
    explode: bool = False,
) -> list[dict[str, object]]:
    """Count a column by rows or unique cases, optionally exploding JSON lists."""

    if field not in dataset.columns:
        raise ValueError(f"unknown CSV column: {field}")
    if unit not in {"rows", "cases"}:
        raise ValueError("unit must be rows or cases")
    source_rows = list(dataset.rows if rows is None else rows)
    counts: Counter[str] = Counter()
    if unit == "rows":
        for row in source_rows:
            if explode:
                parsed = parse_multi_value(row[field])
                values = set(parsed) or ("(blank)",)
            else:
                values = (row[field] or "(blank)",)
            for value in values:
                counts[value or "(blank)"] += 1
    else:
        by_case: dict[str, list[Mapping[str, str]]] = {}
        for row in source_rows:
            by_case.setdefault(row["case_id"].strip(), []).append(row)
        for case_rows in by_case.values():
            values = set()
            for row in case_rows:
                if explode:
                    values.update(parse_multi_value(row[field]) or ("(blank)",))
                else:
                    values.add(row[field] or "(blank)")
            for value in values or {"(blank)"}:
                counts[value or "(blank)"] += 1
    total = (
        len(source_rows) if unit == "rows" else len({row["case_id"].strip() for row in source_rows})
    )
    return [
        {"value": value, "count": count, "rate": count / total if total else None}
        for value, count in sorted(counts.items(), key=lambda item: (-item[1], str(item[0])))
    ]


def rows_to_csv(columns: Sequence[str], rows: Sequence[Mapping[str, object]]) -> str:
    """Serialize rows with a UTF-8 BOM and CSV-safe quoting."""

    from io import StringIO

    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(columns), lineterminator="\r\n")
    writer.writeheader()
    writer.writerows({column: row.get(column, "") for column in columns} for row in rows)
    return "\ufeff" + stream.getvalue()
