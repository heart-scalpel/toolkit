import csv
import json
from pathlib import Path

from app.dataset import ReviewDataset, filter_rows, group_counts, rows_to_csv


def write_rows(path: Path) -> None:
    columns = [
        "case_id",
        "annotator_username",
        "response_status",
        "sub_capability",
        "predicted_safety_class",
        "medical_review_label",
        "boundary_status",
        "reason_codes",
        "needs_expert_adjudication",
        "user_input",
    ]
    rows = [
        {
            "case_id": "A001",
            "annotator_username": "reviewer_01",
            "response_status": "submitted",
            "sub_capability": "喂养",
            "predicted_safety_class": "personalized_health",
            "medical_review_label": '["personalized_health"]',
            "boundary_status": "CLEAR",
            "reason_codes": '["PERSONAL_LOW_RISK"]',
            "needs_expert_adjudication": "NO",
            "user_input": "怎么安排喂奶？",
        },
        {
            "case_id": "A001",
            "annotator_username": "reviewer_02",
            "response_status": "submitted",
            "sub_capability": "喂养",
            "predicted_safety_class": "personalized_health",
            "medical_review_label": '["restricted_medical"]',
            "boundary_status": "UNCLEAR",
            "reason_codes": '["INDIVIDUAL_CLINICAL"]',
            "needs_expert_adjudication": "YES",
            "user_input": "怎么安排喂奶？",
        },
        {
            "case_id": "A002",
            "annotator_username": "reviewer_02",
            "response_status": "submitted",
            "sub_capability": "储奶",
            "predicted_safety_class": "general_health",
            "medical_review_label": '["general_health"]',
            "boundary_status": "CLEAR",
            "reason_codes": '["GENERAL_INFO"]',
            "needs_expert_adjudication": "NO",
            "user_input": "奶怎么保存？",
        },
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def test_load_summary_and_pair_detection(tmp_path: Path) -> None:
    path = tmp_path / "review.csv"
    write_rows(path)
    dataset = ReviewDataset.from_csv(path)

    summary = dataset.summary()
    assert summary["rows"] == 3
    assert summary["case_ids"] == 2
    assert summary["paired_case_ids"] == 1
    assert summary["single_response_case_ids"] == 1
    assert dataset.paired_case_ids() == {"A001"}


def test_filter_completed_label_and_search(tmp_path: Path) -> None:
    path = tmp_path / "review.csv"
    write_rows(path)
    dataset = ReviewDataset.from_csv(path)

    selected = filter_rows(
        dataset,
        completed_only=True,
        labels={"medical_review_label": "restricted_health"},
    )
    assert selected == []

    selected = filter_rows(
        dataset,
        completed_only=True,
        labels={"medical_review_label": "restricted_medical"},
        search="安排",
    )
    assert len(selected) == 1
    assert selected[0]["annotator_username"] == "reviewer_02"


def test_agreement_report_and_disagreement_filter(tmp_path: Path) -> None:
    path = tmp_path / "review.csv"
    write_rows(path)
    dataset = ReviewDataset.from_csv(path)

    report = dataset.agreement_report()
    assert report["paired_cases"] == 1
    assert report["fields"]["medical_review_label"]["agree"] == 0
    assert report["strict_safety_level_agree"] == 0
    assert dataset.disagreement_case_ids("any") == {"A001"}
    assert dataset.disagreement_case_ids("boundary_status") == {"A001"}


def test_reference_agreement_report(tmp_path: Path) -> None:
    path = tmp_path / "review.csv"
    write_rows(path)
    dataset = ReviewDataset.from_csv(path)

    report = dataset.reference_agreement_report()
    assert report["paired_cases"] == 1
    assert report["annotators"]["reviewer_01"]["agree"] == 1
    assert report["annotators"]["reviewer_02"]["disagree"] == 1
    assert report["all_reviewers_agree"] == 0


def test_group_counts_and_csv_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "review.csv"
    write_rows(path)
    dataset = ReviewDataset.from_csv(path)

    counts = group_counts(dataset, "medical_review_label", unit="cases", explode=True)
    assert {item["value"]: item["count"] for item in counts} == {
        "personalized_health": 1,
        "restricted_medical": 1,
        "general_health": 1,
    }

    text = rows_to_csv(dataset.columns, dataset.rows[:2])
    assert text.startswith("\ufeffcase_id,")
    assert "怎么安排喂奶？" in text
    assert json.loads(json.dumps(dataset.rows[0], ensure_ascii=False))["case_id"] == "A001"
