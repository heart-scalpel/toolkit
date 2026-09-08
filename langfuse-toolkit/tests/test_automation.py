import json

import httpx
import pytest

from app.cli import build_parser, run
from tests.support import execute_resource as execute
from tests.support import make_runtime
from tests.support import request_plan as plan


def args(*argv):
    return build_parser().parse_args(list(argv))


def connected(handler, *, project_id="project-a"):
    requests = []

    def dispatch(request):
        requests.append(request)
        if request.url.path == "/api/public/projects":
            return httpx.Response(200, json={"data": [{"id": "project-a", "name": "Test"}]})
        return handler(request)

    api = make_runtime(
        "http://langfuse.test",
        "public",
        "secret",
        project_id,
        transport=httpx.MockTransport(dispatch),
    )
    return (api, requests)


def body_file(tmp_path, body, name="body.json"):
    path = tmp_path / name
    path.write_text(json.dumps(body), encoding="utf-8")
    return str(path)


@pytest.mark.parametrize(
    "command,path,cursor",
    [
        (("project", "datasets", "list"), "/api/public/v2/datasets", False),
        (("project", "items", "list", "--dataset", "review/a"), "/api/public/dataset-items", False),
        (("project", "traces", "list"), "/api/public/v2/observations", True),
        (("project", "sessions", "list"), "/api/public/v2/observations", True),
        (("project", "observations", "list"), "/api/public/v2/observations", True),
        (("project", "observations", "list", "--legacy"), "/api/public/observations", False),
        (("project", "scores", "list"), "/api/public/v3/scores", True),
        (("project", "scores", "list", "--legacy"), "/api/public/v2/scores", False),
        (("project", "score-configs", "list"), "/api/public/score-configs", False),
        (
            ("project", "runs", "list", "--dataset", "review/a"),
            "/api/public/datasets/review%2Fa/runs",
            False,
        ),
        (
            ("project", "run-items", "list", "--dataset-id", "ds", "--run-name", "baseline"),
            "/api/public/dataset-run-items",
            False,
        ),
        (("project", "experiments", "list"), "/api/public/experiments", True),
        (
            ("project", "experiment-items", "list", "--experiment-id", "exp"),
            "/api/public/experiment-items",
            True,
        ),
    ],
)
def test_read_endpoints_and_pagination_match_contract(command, path, cursor):
    request = plan(args(*command))
    assert request.path == path
    assert request.cursor is cursor
    assert request.method == "GET"


def test_v4_trace_get_collects_observations_across_cursor_pages():

    def handler(request):
        assert request.url.path == "/api/public/v2/observations"
        assert request.url.params["traceId"] == "trace-a"
        assert "fromStartTime" in request.url.params
        second = "cursor" in request.url.params
        return httpx.Response(
            200,
            json={
                "data": [{"id": "obs-b" if second else "obs-a", "traceId": "trace-a"}],
                "meta": {} if second else {"cursor": "next-page"},
            },
        )

    (api, requests) = connected(handler)
    with api:
        result = execute(args("project", "traces", "get", "trace-a"), api)
    assert len(result["observations"]) == 2
    assert result["complete"] is True
    assert requests[-1].url.params["cursor"] == "next-page"


def test_v4_session_list_marks_partial_page_aggregation():
    (api, _) = connected(
        lambda _: httpx.Response(
            200,
            json={
                "data": [
                    {"id": "obs-a", "traceId": "t1", "sessionId": "s1"},
                    {"id": "obs-b", "traceId": "t2", "sessionId": "s1"},
                ],
                "meta": {"cursor": "more"},
            },
        )
    )
    with api:
        result = execute(args("project", "sessions", "list"), api)
    assert result["data"] == [{"id": "s1", "observationCount": 2, "traceIds": ["t1", "t2"]}]
    assert result["complete"] is False


def test_trace_tags_do_not_drop_user_or_time_filters():
    request = plan(args("project", "traces", "list", "--tags", "smoke", "--user-id", "u1"))
    conditions = json.loads(request.params["filter"])
    assert {item["column"] for item in conditions} == {
        "tags",
        "isRootObservation",
        "userId",
        "startTime",
    }


def test_observation_get_requires_trace_and_preserves_all_filters():
    with pytest.raises(ValueError, match="--trace-id"):
        plan(args("project", "observations", "get", "obs-a"))
    request = plan(args("project", "observations", "get", "obs-a", "--trace-id", "trace-a"))
    conditions = json.loads(request.params["filter"])
    assert {item["column"] for item in conditions} == {"id", "traceId", "startTime"}


def test_scores_get_uses_v3_id_filter():

    def handler(request):
        assert request.url.path == "/api/public/v3/scores"
        assert request.url.params["id"] == "score-a"
        return httpx.Response(200, json={"data": [{"id": "score-a", "value": 0.9}], "meta": {}})

    (api, _) = connected(handler)
    with api:
        assert execute(args("project", "scores", "get", "score-a"), api)["value"] == 0.9


@pytest.mark.parametrize(
    "resource,action,body",
    [
        ("datasets", "create", {"name": "review/a", "metadata": {"owner": "qa"}}),
        (
            "items",
            "upsert",
            {
                "datasetName": "review/a",
                "id": "case-a",
                "input": {"q": "hello"},
                "expectedOutput": "answer",
            },
        ),
        (
            "score-configs",
            "create",
            {"name": "quality", "dataType": "NUMERIC", "minValue": 0, "maxValue": 1},
        ),
    ],
)
def test_synchronous_writes_are_read_back(resource, action, body, tmp_path):
    stored = {**body, "id": body.get("id", "new-id")}

    def handler(request):
        if request.method == "POST":
            assert json.loads(request.content) == body
        return httpx.Response(200, json=stored)

    (api, requests) = connected(handler)
    with api:
        result = execute(
            args("project", resource, action, "--file", body_file(tmp_path, body)), api
        )
    assert result["verified"] is True
    assert requests[-1].method == "GET"
    if resource == "datasets":
        assert requests[-1].url.raw_path.endswith(b"review%2Fa")


def test_score_creation_reports_acceptance_not_readback(tmp_path):
    body = {
        "id": "score-a",
        "name": "quality",
        "value": 1,
        "dataType": "BOOLEAN",
        "traceId": "trace-a",
    }
    (api, requests) = connected(lambda _: httpx.Response(200, json={"id": "score-a"}))
    with api:
        result = execute(
            args("project", "scores", "create", "--file", body_file(tmp_path, body)), api
        )
    assert result["accepted"] is True
    assert "verified" not in result
    assert [(r.method, r.url.path) for r in requests][1:] == [("POST", "/api/public/scores")]


@pytest.mark.parametrize(
    "body",
    [
        {"name": "x", "value": 1},
        {"name": "x", "value": 2, "traceId": "t", "dataType": "BOOLEAN"},
        {"name": "x", "value": True, "traceId": "t", "dataType": "BOOLEAN"},
        {"name": "x", "value": 1, "traceId": "t", "sessionId": "s"},
        {"name": "x", "value": 1, "traceId": "t", "source": "EVAL"},
    ],
)
def test_invalid_scores_fail_before_any_request(body, tmp_path):
    (api, requests) = connected(lambda _: pytest.fail("Network used"))
    with api, pytest.raises(ValueError):
        execute(args("project", "scores", "create", "--file", body_file(tmp_path, body)), api)
    assert requests == []


def test_dry_run_can_preview_request_without_a_project(tmp_path):
    (api, requests) = connected(lambda _: pytest.fail("Network used"), project_id="")
    with api:
        result = execute(
            args(
                "project",
                "items",
                "upsert",
                "--file",
                body_file(tmp_path, {"datasetName": "d", "input": 0}),
                "--dry-run",
            ),
            api,
        )
    assert result["dryRun"] is True
    assert result["body"]["input"] == 0
    assert requests == []


def test_missing_project_still_blocks_resource_mutations(tmp_path):
    (api, requests) = connected(lambda _: pytest.fail("Network used"), project_id="")
    with api, pytest.raises(ValueError, match="Run 'project info' first"):
        execute(
            args("project", "datasets", "create", "--file", body_file(tmp_path, {"name": "test"})),
            api,
        )
    assert requests == []


def test_cursor_limit_does_not_report_truncated_results_as_complete():
    (api, _) = connected(
        lambda _: httpx.Response(200, json={"data": [{"id": "a"}], "meta": {"cursor": "more"}})
    )
    with api, pytest.raises(RuntimeError, match="incomplete"):
        execute(args("project", "scores", "list", "--all", "--max-pages", "1"), api)


def test_dataset_pagination_uses_page_numbers():

    def handler(request):
        return httpx.Response(
            200,
            json={
                "data": [{"id": request.url.params["page"]}],
                "meta": {"totalPages": 2, "totalItems": 2},
            },
        )

    (api, requests) = connected(handler)
    with api:
        result = execute(args("project", "datasets", "list", "--all"), api)
    assert result["complete"] is True
    assert [r.url.params["page"] for r in requests[1:]] == ["1", "2"]


def test_batch_prevalidates_all_steps_before_writing(tmp_path):
    body_file(tmp_path, {"name": "demo"}, "dataset.json")
    batch = body_file(
        tmp_path,
        {
            "commands": [
                ["project", "datasets", "create", "--file", "dataset.json"],
                ["project", "prompts", "label", "prompt", "--version", "1", "--label", "latest"],
            ]
        },
        "batch.json",
    )
    (api, requests) = connected(lambda _: pytest.fail("Network used"))
    with api, pytest.raises(ValueError, match="managed by Langfuse"):
        run(args("workflow", "run", "--file", batch), api)
    assert requests == []


def test_batch_dry_run_previews_writes_and_reads_without_request(tmp_path, capsys):
    body_file(tmp_path, {"name": "demo"}, "dataset.json")
    batch = body_file(
        tmp_path,
        {
            "commands": [
                ["project", "datasets", "create", "--file", "dataset.json"],
                ["project", "datasets", "get", "demo"],
                ["project", "info"],
            ]
        },
        "batch.json",
    )
    (api, requests) = connected(lambda _: pytest.fail("Network used"))
    with api:
        assert run(args("workflow", "run", "--file", batch, "--dry-run"), api) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["completed"] == 3
    assert all(item["result"]["dryRun"] for item in result["results"])
    assert requests == []


def test_batch_stops_after_failure_and_reports_completed_steps(tmp_path, capsys):
    body_file(tmp_path, {"name": "quality", "value": 1, "traceId": "t"}, "score.json")
    body_file(tmp_path, {"name": "demo"}, "dataset.json")
    batch = body_file(
        tmp_path,
        {
            "commands": [
                ["project", "scores", "create", "--file", "score.json"],
                ["project", "datasets", "create", "--file", "dataset.json"],
                ["project", "items", "list"],
            ]
        },
        "batch.json",
    )

    def handler(request):
        return (
            httpx.Response(200, json={"id": "s"})
            if request.url.path.endswith("/scores")
            else httpx.Response(500)
        )

    (api, requests) = connected(handler)
    with api:
        assert run(args("workflow", "run", "--file", batch), api) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["completed"] == 1 and result["failedStep"] == 2
    assert not any(r.url.path.endswith("/dataset-items") for r in requests)


@pytest.mark.parametrize(
    "command",
    [["project", "items", "delete", "item-a"], ["workflow", "run", "--file", "nested.json"]],
)
def test_batch_rejects_unconfirmed_deletion_and_nesting(command, tmp_path):
    batch = body_file(tmp_path, {"commands": [command]})
    (api, requests) = connected(lambda _: pytest.fail("Network used"))
    with api, pytest.raises(ValueError):
        run(args("workflow", "run", "--file", batch), api)
    assert requests == []
