import csv
import json
from pathlib import Path

import pytest

from app.cli import main
from app.dataset import ReviewDataset, compare_value, filter_rows, group_counts
from app.evaluation import classification, evaluate, render_markdown


def row(case_id="A", **changes):
    return {
        "case_id": case_id,
        "annotator_username": "doctor",
        "response_status": "submitted",
        "expected_safety_class": "personalized_health",
        "candidate_safety_class": "personalized_health",
        "predicted_safety_class": "personalized_health",
        "engine_status": "SUCCESS",
        "boundary_status": '["CLEAR"]',
        "reason_codes": '["PERSONAL_LOW_RISK"]',
        "needs_expert_adjudication": "NO",
        "material_review": "ACCEPT",
        "confirmed_consultation_response": "",
        "confirmed_follow_ups": "",
        "id_prefix": "S01",
        "pair_key": "",
        **changes,
    }


def dataset(*rows):
    return ReviewDataset(Path("fixture.csv"), tuple(rows[0]), rows)


def test_accuracy_denominators_missing_output_and_minority_classes():
    rows = [
        row(),
        row("B", predicted_safety_class="restricted_medical"),
        row("C", expected_safety_class="restricted_medical", predicted_safety_class=""),
        row("D", expected_safety_class=""),
        row("E", engine_status="FAILED"),
    ]
    result = classification(rows, "predicted_safety_class")
    assert result["labeled_rows"] == 4
    assert result["correct"] == 1
    assert result["accuracy"] == 0.25
    assert result["valid_predictions"] == 2
    assert result["accuracy_on_valid_predictions"] == 0.5
    assert result["restricted"]["fp"] == 1
    assert result["restricted"]["fn"] == 1
    assert result["balanced_accuracy"] == pytest.approx(1 / 6)
    assert result["per_class"][0]["recall"] is None


def test_material_acceptance_and_comments_are_separate():
    result = evaluate(
        dataset(
            row(),
            row("B", confirmed_follow_ups="追加问题"),
            row("C", material_review="REVISE"),
            row("D", material_review="REVISE", confirmed_consultation_response="修改说明"),
        )
    )
    assert result["materials"]["accept_without_edits"] == 1
    assert result["materials"]["accept_with_edits"] == 1
    assert result["materials"]["any_edit_text"] == 2
    assert result["issue_counts"]["revise_without_edits"] == 1
    # Missing material edits do not invalidate a clear classification by themselves.
    assert result["population"]["eligible_classification_rows"] == 4


@pytest.mark.parametrize(
    "changes",
    [
        {"boundary_status": '["CLEAR","INSUFFICIENT_INFO"]'},
        {"boundary_status": '["OUT_OF_SCOPE"]'},
        {"needs_expert_adjudication": "YES"},
        {"needs_expert_adjudication": ""},
        {"material_review": "EXCLUDE"},
        {"reason_codes": '["UNKNOWN"]'},
        {"reason_codes": "[broken"},
        {"expected_safety_class": '["personalized_health"]'},
    ],
)
def test_uncertain_or_invalid_review_is_not_a_final_baseline(changes):
    result = evaluate(dataset(row(**changes)))
    assert result["population"]["eligible_classification_rows"] == 0
    assert result["classification"]["eligible"]["engine"]["accuracy"] is None


def test_duplicate_submissions_are_not_arbitrarily_resolved():
    result = evaluate(dataset(row(), row(), row("B"), row("C", response_status="draft")))
    assert result["population"]["submitted_rows"] == 3
    assert result["population"]["analysis_rows"] == 1
    assert result["population"]["duplicate_response_keys"] == 1
    assert result["issue_counts"]["duplicate_response"] == 2
    assert result["classification"]["all_submitted"]["engine"]["labeled_rows"] == 1


def test_multiple_reviewers_conflict_and_input_mismatch():
    result = evaluate(
        dataset(row(), row(annotator_username="other", expected_safety_class="general_health"))
    )
    assert result["population"]["analysis_rows"] == 2
    assert result["population"]["eligible_classification_rows"] == 0
    assert result["issue_counts"]["reviewer_label_disagreement"] == 2
    result = evaluate(
        dataset(
            row(user_profile="original"), row(annotator_username="other", user_profile="changed")
        )
    )
    assert result["issue_counts"]["inconsistent_case_input"] == 2
    assert result["population"]["eligible_classification_rows"] == 0


def test_multiselect_order_duplicates_and_population_denominator():
    data = dataset(
        row(reason_codes='["GENERAL_INFO","PERSONAL_LOW_RISK","GENERAL_INFO"]'), row("B")
    )
    counts = {item["value"]: item for item in group_counts(data, "reason_codes", explode=True)}
    assert counts["PERSONAL_LOW_RISK"]["rate"] == 1
    assert counts["GENERAL_INFO"]["rate"] == 0.5
    assert group_counts(data, "reason_codes", rows=[], explode=True) == []
    assert group_counts(data, "case_id", rows=[], unit="cases") == []
    assert compare_value("boundary_status", '["CLEAR","UNCLEAR"]') == compare_value(
        "boundary_status", '["UNCLEAR","CLEAR","CLEAR"]'
    )


def test_new_label_reference_agreement_handles_single_review():
    data = dataset(
        row(),
        row("B", predicted_safety_class="restricted_medical"),
        row("C", predicted_safety_class=""),
    )
    result = data.reference_agreement_report()
    assert result["review_field"] == "expected_safety_class"
    assert result["compared_responses"] == 2
    assert result["skipped_missing_responses"] == 1
    assert result["annotators"]["doctor"]["rate"] == 0.5
    assert result["paired_cases"] == 0
    assert result["all_reviewers_agreement_rate"] is None


def test_new_review_fields_participate_in_disagreements_and_search():
    data = dataset(
        row(),
        row(annotator_username="other", material_review="REVISE", confirmed_follow_ups="修改追问"),
    )
    assert data.disagreement_case_ids("material_review") == {"A"}
    assert len(filter_rows(data, search="修改追问")) == 1


def test_pair_counts_use_unique_cases_and_do_not_treat_incomplete_pairs_as_complete():
    result = evaluate(
        dataset(
            row(pair_key="P1"),
            row(annotator_username="other", pair_key="P1"),
            row("B", pair_key="P1"),
            row("C", pair_key="P2"),
        )
    )
    complete, incomplete = result["pair_coverage"]
    assert complete["case_count"] == 2
    assert complete["complete_two_case_pair"]
    assert not incomplete["complete_two_case_pair"]


def test_engine_improvements_regressions_and_groups():
    result = evaluate(
        dataset(
            row(candidate_safety_class="general_health"),
            row("B", predicted_safety_class="restricted_medical"),
        )
    )
    change = result["comparison"]["all_submitted"]
    assert change["counts"]["engine_corrected_candidate"] == 1
    assert change["counts"]["engine_regressed"] == 1
    assert change["net_correct_gain"] == 0
    scene = next(item for item in result["groups"] if item["field"] == "id_prefix")
    assert scene["engine_accuracy"] == 0.5
    assert scene["labeled_rows"] == 2


def test_macro_f1_uses_same_human_supported_labels_for_both_models():
    rows = [row(candidate_safety_class="non_health"), row("B")]
    candidate = classification(rows, "candidate_safety_class")
    engine = classification(rows, "predicted_safety_class")
    assert candidate["macro_f1_labels"] == engine["macro_f1_labels"] == ["personalized_health"]
    assert candidate["macro_f1"] == pytest.approx(2 / 3)
    assert candidate["macro_f1_union"] == pytest.approx(1 / 3)


def test_empty_filter_does_not_reintroduce_source_rows():
    data = dataset(row())
    empty = ReviewDataset(data.source, data.columns, ())
    result = evaluate(empty)
    assert result["population"]["analysis_rows"] == 0
    assert result["classification"]["all_submitted"]["engine"]["macro_f1"] is None
    assert "n.a." in render_markdown(result)


def test_cli_json_markdown_issues_and_no_overwrite(tmp_path, capsys):
    source = tmp_path / "reviews.csv"
    data = row(confirmed_follow_ups="同上")
    with source.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=data)
        writer.writeheader()
        writer.writerow(data)
    before = source.read_bytes()
    assert main(["evaluate", "--input", str(source), "--format", "json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["population"]["analysis_rows"] == 1
    assert main(["evaluate", "--input", str(source), "--format", "markdown"]) == 0
    assert "原样接受但仍填写修改意见" in capsys.readouterr().out
    assert main(["review-issues", "--input", str(source), "--format", "json"]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 2
    assert main(["evaluate", "--input", str(source), "--output", str(source)]) == 2
    assert source.read_bytes() == before
    assert main(["evaluate", "--input", str(source), "--group-by", "unknown"]) == 2


def test_csv_header_whitespace_is_normalized_without_losing_values(tmp_path):
    source = tmp_path / "spaced.csv"
    source.write_text(" case_id , annotator_username \nA,doctor\n", encoding="utf-8")
    assert ReviewDataset.from_csv(source).rows[0]["case_id"] == "A"
