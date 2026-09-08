from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import argilla as rg
import pytest

from app.cli import build_parser, run
from app.platforms.argilla import build_settings, clone_dataset, offline_client
from app.profiles import get_profile


@pytest.fixture
def clone_server(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    client = offline_client()
    client.api.vectors = None
    monkeypatch.setattr(rg.Argilla, "_default_client", client)
    settings = build_settings(get_profile("cozie-medical-review").task_spec("review"), 1, client)
    settings.guidelines = "Saved batch instructions, different from the current profile."
    settings.questions[0].title = "Saved question title"
    settings.vectors = [rg.VectorField(name="embedding", dimensions=3)]
    settings.allow_extra_metadata = True
    for prop in [*settings.fields, *settings.questions, *settings.metadata, *settings.vectors]:
        prop.api_model().id = uuid4()
    settings.get = Mock(return_value=settings)
    records = []
    for index, status in enumerate(["submitted", "draft", "discarded", None]):
        responses = (
            [
                rg.Response(
                    question_name="expected_safety_class",
                    value="general_health",
                    status=status,
                    user_id=uuid4(),
                )
            ]
            if status
            else []
        )
        records.append(
            rg.Record(
                id=f"case-{index}",
                fields={"user_input": f"Question {index}", "user_profile": "Original profile"},
                metadata={"case_id": f"case-{index}", "hidden": ["original"]},
                vectors={"embedding": [1.0, 2.0, 3.0]},
                responses=responses,
                suggestions=[
                    rg.Suggestion(question_name="expected_safety_class", value="general_health")
                ],
                _server_id=uuid4(),
            )
        )
    records[0]._model.status = "completed"
    source = SimpleNamespace(name="source", settings=settings, records=Mock(return_value=records))
    workspace = SimpleNamespace(datasets=[source])
    client.workspaces = Mock(return_value=workspace)
    state = SimpleNamespace(client=client, source=source, records=records, targets=[], corrupt=None)

    def make_dataset(*, name, workspace, settings, client):
        uploaded = []
        target = SimpleNamespace(name=name, settings=settings)
        target.create = Mock(return_value=target)
        target.records = Mock(side_effect=lambda **kwargs: uploaded)
        target.settings.get = Mock(return_value=settings)

        def log(rows):
            uploaded.extend(rg.Record.from_dict(record.to_dict()) for record in rows)
            if state.corrupt:
                state.corrupt(target, uploaded)

        target.records.log = Mock(side_effect=log)
        state.targets.append(target)
        return target

    monkeypatch.setattr(rg, "Dataset", make_dataset)
    return state


def clone(state: SimpleNamespace, **kwargs) -> dict:
    return clone_dataset(
        client=state.client,
        workspace="default",
        source_name="source",
        dataset_name="product",
        min_submitted=2,
        **kwargs,
    )


def test_clone_preserves_saved_task_and_all_records_without_feedback(clone_server) -> None:
    state = clone_server
    original_settings = deepcopy(state.source.settings.serialize())
    originals = deepcopy([record.to_dict() for record in state.records])

    summary = clone(state)

    assert summary["created"] is True
    assert summary["verified"] is True
    assert summary["records"] == 4
    assert summary["record_ids"] == [f"case-{index}" for index in range(4)]
    target = state.targets[0]
    target.create.assert_called_once()
    target.records.log.assert_called_once()
    expected_settings = deepcopy(original_settings)
    expected_settings["distribution"]["min_submitted"] = 2
    actual_settings = target.settings.serialize()
    for collection in ("fields", "questions", "metadata", "vectors"):
        for item in expected_settings[collection]:
            item["id"] = None
    assert actual_settings == expected_settings
    for copied, original in zip(target.records(), originals, strict=True):
        payload = copied.to_dict()
        for key in ("id", "fields", "metadata", "vectors"):
            assert payload[key] == original[key]
        assert copied._server_id is None
        assert payload["responses"] == {}
        assert payload["suggestions"] == {}
        assert copied.status == "pending"
    assert state.source.settings.serialize() == original_settings
    assert [record.to_dict() for record in state.records] == originals
    state.source.records.assert_called_once_with(
        with_responses=False, with_suggestions=False, with_vectors=True
    )


def test_clone_preview_reads_all_records_without_creating(clone_server) -> None:
    summary = clone(clone_server, dry_run=True)

    assert summary["records"] == 4
    assert summary["min_submitted"] == 2
    assert summary["dry_run"] is True
    assert summary["created"] is False
    assert summary["verified"] is False
    assert clone_server.targets == []
    clone_server.source.settings.get.assert_called_once()


@pytest.mark.parametrize("dry_run", [False, True])
def test_clone_refuses_existing_destination_before_loading_records(clone_server, dry_run) -> None:
    clone_server.client.workspaces.return_value.datasets.append(SimpleNamespace(name="product"))
    with pytest.raises(ValueError, match="already exists"):
        clone(clone_server, dry_run=dry_run)
    clone_server.source.records.assert_not_called()
    assert clone_server.targets == []


def test_clone_requires_exact_source_name(clone_server) -> None:
    clone_server.source.name = "source-other"
    with pytest.raises(ValueError, match="not found"):
        clone(clone_server)
    assert clone_server.targets == []


@pytest.mark.parametrize("invalid", ["empty", "missing_id", "duplicate_id"])
def test_clone_rejects_invalid_source_records_before_creation(clone_server, invalid) -> None:
    if invalid == "empty":
        clone_server.records.clear()
    elif invalid == "missing_id":
        clone_server.records[0].id = None
    else:
        clone_server.records[1].id = clone_server.records[0].id
    with pytest.raises(ValueError, match=r"no records|empty or duplicate"):
        clone(clone_server)
    assert clone_server.targets == []


@pytest.mark.parametrize(
    "corruption", ["missing_row", "content", "settings", "response", "suggestion", "status"]
)
def test_clone_detects_incomplete_or_changed_upload(clone_server, corruption) -> None:
    def corrupt(target, rows):
        if corruption == "missing_row":
            rows.pop()
        elif corruption == "content":
            rows[0].fields["user_input"] = "Changed question"
        elif corruption == "settings":
            target.settings.questions[0].title = "Changed title"
        elif corruption == "status":
            rows[0]._model.status = "completed"
        else:
            payload = rows[0].to_dict()
            key = "responses" if corruption == "response" else "suggestions"
            payload[key] = clone_server.records[0].to_dict()[key]
            rows[0] = rg.Record.from_dict(payload)

    clone_server.corrupt = corrupt
    with pytest.raises(ValueError, match=r"verification failed.*was created"):
        clone(clone_server)


@pytest.mark.parametrize(
    "options, message",
    [
        ([], "requires --dataset"),
        (["--dataset", "source"], "different names"),
        (["--dataset", "product", "--random"], "do not combine"),
        (["--dataset", "product", "--limit", "50"], "do not combine"),
        (["--dataset", "product", "--offset", "1"], "do not combine"),
        (["--dataset", "product", "--input", "cases.csv"], "do not combine"),
        (["--dataset", "product", "--profile", "cozie-medical-review"], "do not combine"),
        (["--dataset", "product", "--guidelines", "new.md"], "do not combine"),
        (["--dataset", "product", "--mode", "comparison"], "do not combine"),
        (["--dataset", "product", "--min-submitted", "0"], "at least 1"),
    ],
)
def test_clone_cli_rejects_invalid_options_before_connecting(monkeypatch, options, message) -> None:
    connect = Mock(side_effect=AssertionError("must validate before connecting"))
    monkeypatch.setattr("app.cli.rg.Argilla", connect)
    args = build_parser().parse_args(["--clone-dataset", "source", *options])
    args.platform = "argilla"
    with pytest.raises(ValueError, match=message):
        run(args)
    connect.assert_not_called()


@pytest.mark.parametrize("dry_run", [False, True])
def test_clone_cli_routes_without_loading_a_profile(monkeypatch, capsys, dry_run) -> None:
    client = SimpleNamespace(workspaces=[SimpleNamespace(name="default")])
    monkeypatch.setattr("app.cli.rg.Argilla", Mock(return_value=client))
    clone_action = Mock(return_value={"created": not dry_run})
    monkeypatch.setattr("app.cli.argilla.clone_dataset", clone_action)
    args = build_parser().parse_args(
        [
            "--clone-dataset",
            "source",
            "--dataset",
            "product",
            "--api-key",
            "test-key",
            *(["--dry-run"] if dry_run else []),
        ]
    )
    args.platform = "argilla"
    assert run(args) == 0
    clone_action.assert_called_once_with(
        client=client,
        workspace="default",
        source_name="source",
        dataset_name="product",
        min_submitted=2,
        dry_run=dry_run,
    )
    assert '"created":' in capsys.readouterr().out
