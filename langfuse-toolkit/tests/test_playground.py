import json
from pathlib import Path

import httpx
import pytest

from app.cli import build_parser, main, run
from app.projects.playground import compile_messages, load_input
from tests.support import execute_resource as execute
from tests.support import make_runtime


def args(*argv):
    return build_parser().parse_args(list(argv))


def input_file(tmp_path, **updates):
    value = {
        "modelParams": {"provider": "gateway", "model": "test-model"},
        "messages": [{"role": "user", "content": "{{question}}"}],
        "variables": {"question": "Hello"},
    }
    value.update(updates)
    if "prompt" in updates:
        value.pop("messages")
    path = tmp_path / "input.json"
    path.write_text(json.dumps(value))
    return str(path)


def connection(**updates):
    return {
        "id": "conn-1",
        "provider": "gateway",
        "adapter": "openai",
        "customModels": ["test-model"],
        "withDefaultModels": False,
        **updates,
    }


def api(
    handler=None,
    *,
    project_id="p1",
    cookie="next-auth.session-token=fake-session",
    connections=None,
):
    requests = []

    def dispatch(request):
        requests.append(request)
        if request.url.path == "/langfuse/api/public/projects":
            return httpx.Response(200, json={"data": [{"id": "p1", "name": "Test"}]})
        if request.url.path == "/langfuse/api/public/llm-connections":
            return httpx.Response(
                200,
                json={
                    "data": connections if connections is not None else [connection()],
                    "meta": {"totalPages": 1},
                },
            )
        return handler(request) if handler else httpx.Response(200, json={"content": "Hi"})

    return (
        make_runtime(
            "http://langfuse.test/langfuse",
            "public-key",
            "private-key",
            project_id,
            session_cookie=cookie,
            transport=httpx.MockTransport(dispatch),
        ),
        requests,
    )


def test_llms_discovery_drops_secrets_and_redacts_url():
    (client, requests) = api(
        connections=[
            connection(
                secretKey="never-print",
                displaySecretKey="also-omit",
                extraHeaders={"Authorization": "secret-header"},
                config={"password": "hidden"},
                baseURL="https://user:password@model.test/v1?key=private#token",
            )
        ]
    )
    with client:
        result = execute(args("project", "llms", "list", "--all"), client)
    row = result["data"][0]
    assert row["baseURL"] == "https://model.test/v1"
    assert row["customModels"] == ["test-model"]
    assert set(row) == {"id", "provider", "adapter", "customModels", "withDefaultModels", "baseURL"}
    assert all("cookie" not in request.headers for request in requests)


def test_llms_discovery_follows_pages_and_does_not_invent_default_models():
    calls = []

    def dispatch(request):
        calls.append(request)
        if request.url.path.endswith("/projects"):
            return httpx.Response(200, json={"data": [{"id": "p1", "name": "Test"}]})
        page = int(request.url.params["page"])
        return httpx.Response(
            200,
            json={
                "data": [
                    connection(
                        id=str(page), provider=str(page), customModels=[], withDefaultModels=True
                    )
                ],
                "meta": {"totalPages": 2, "totalItems": 2},
            },
        )

    with make_runtime(
        "http://test", "public", "secret", "p1", transport=httpx.MockTransport(dispatch)
    ) as client:
        result = execute(args("project", "llms", "list", "--all"), client)
    assert [r.url.params["page"] for r in calls[1:]] == ["1", "2"]
    assert result["count"] == 2
    assert result["data"][0]["customModels"] == []


def test_playground_uses_session_only_and_keeps_it_out_of_public_requests(tmp_path, capsys):
    (client, requests) = api(
        cookie="analytics=private; __Secure-next-auth.session-token.0=part-a; __Secure-next-auth.session-token.1=part-b"
    )
    with client:
        assert (
            run(args("project", "playground", "run", "--file", input_file(tmp_path)), client) == 0
        )
    post = requests[-1]
    assert post.url.path == "/langfuse/api/chatCompletion"
    assert post.method == "POST"
    assert "authorization" not in post.headers
    assert (
        post.headers["cookie"]
        == "__Secure-next-auth.session-token.0=part-a; __Secure-next-auth.session-token.1=part-b"
    )
    assert all(
        "cookie" not in request.headers and "authorization" in request.headers
        for request in requests[:-1]
    )
    body = json.loads(post.content)
    assert body["modelParams"]["adapter"] == "openai"
    assert body["messages"] == [{"role": "user", "type": "user", "content": "Hello"}]
    assert body["projectId"] == "p1" and body["streaming"] is False
    output = capsys.readouterr().out
    assert json.loads(output)["output"] == {"content": "Hi"}
    assert "part-a" not in output and "private-key" not in output


def test_playground_response_cookies_do_not_leak_to_later_public_calls(tmp_path):
    (client, requests) = api(
        lambda _: httpx.Response(
            200,
            json={"content": "ok"},
            headers={"set-cookie": "next-auth.session-token=response-secret; Path=/"},
        )
    )
    with client:
        run(args("project", "playground", "run", "--file", input_file(tmp_path)), client)
        execute(args("project", "llms", "list"), client)
    assert "cookie" not in requests[-1].headers


def test_saved_prompt_resolves_references_and_expands_variables_and_placeholders(tmp_path, capsys):

    def dispatch(request):
        if request.method == "GET":
            assert request.url.params["resolve"] == "true"
            assert request.url.params["version"] == "2"
            return httpx.Response(
                200,
                json={
                    "name": "support/a",
                    "type": "chat",
                    "version": 2,
                    "prompt": [
                        {"role": "system", "content": "Answer {{question}}"},
                        {"type": "placeholder", "name": "history"},
                    ],
                    "config": {"temperature": 999},
                },
            )
        return httpx.Response(200, json={"answer": 4})

    path = input_file(
        tmp_path,
        prompt={"name": "support/a", "version": 2},
        placeholders={"history": [{"role": "user", "content": "2 + 2"}]},
        structuredOutputSchema={"type": "object", "properties": {"answer": {"type": "number"}}},
    )
    (client, requests) = api(dispatch)
    with client:
        run(args("project", "playground", "run", "--file", path), client)
    body = json.loads(requests[-1].content)
    assert [m["content"] for m in body["messages"]] == ["Answer Hello", "2 + 2"]
    assert "temperature" not in body["modelParams"]
    assert body["structuredOutputSchema"]["type"] == "object"
    assert json.loads(capsys.readouterr().out)["prompt"]["version"] == 2


def test_text_prompt_dry_run_reads_only_and_needs_no_cookie(tmp_path, capsys):

    def dispatch(request):
        assert request.method == "GET" and request.url.params["label"] == "production"
        return httpx.Response(
            200, json={"name": "support", "type": "text", "version": 1, "prompt": "{{question}}"}
        )

    (client, requests) = api(dispatch, cookie="")
    with client:
        run(
            args(
                "project",
                "playground",
                "run",
                "--file",
                input_file(tmp_path, prompt={"name": "support", "label": "production"}),
                "--dry-run",
            ),
            client,
        )
    output = json.loads(capsys.readouterr().out)
    assert output["body"]["messages"][0]["content"] == "Hello"
    assert output["dryRun"] is True
    assert all(r.method == "GET" for r in requests)


@pytest.mark.parametrize(
    "cookie",
    [
        "",
        "analytics=not-a-session",
        "next-auth.session-token=value\r\nAuthorization: injection",
        "next-auth.session-token=非ASCII",
    ],
)
def test_invalid_cookie_stops_before_any_request(cookie, tmp_path):
    (client, requests) = api(cookie=cookie)
    with client, pytest.raises(ValueError, match="LANGFUSE_SESSION_COOKIE"):
        run(args("project", "playground", "run", "--file", input_file(tmp_path)), client)
    assert requests == []


@pytest.mark.parametrize("command", ["llms", "playground"])
def test_mismatched_project_stops_before_connections_or_execution(command, tmp_path):
    (client, requests) = api(project_id="other")
    argv = (
        ("project", "llms", "list")
        if command == "llms"
        else ("project", "playground", "run", "--file", input_file(tmp_path))
    )
    with client, pytest.raises(ValueError, match="does not match"):
        run(args(*argv), client)
    assert len(requests) == 1


@pytest.mark.parametrize(
    "status,match",
    [(401, "session expired"), (403, "cannot execute"), (302, "HTTP 302"), (500, "HTTP 500")],
)
def test_playground_errors_do_not_echo_secrets_follow_redirects_or_retry(status, match, tmp_path):
    (client, requests) = api(
        lambda _: httpx.Response(
            status,
            json={"message": "secret-from-provider"},
            headers={"location": "https://other.test/steal"},
        )
    )
    with client, pytest.raises(RuntimeError, match=match) as error:
        run(args("project", "playground", "run", "--file", input_file(tmp_path)), client)
    assert "secret-from-provider" not in str(error.value)
    assert len([r for r in requests if r.method == "POST"]) == 1
    assert all(r.url.host == "langfuse.test" for r in requests)


def test_playground_timeout_is_reported_as_uncertain_without_retry(tmp_path):

    def timeout(request):
        raise httpx.ReadTimeout("private-provider-details", request=request)

    (client, requests) = api(timeout)
    with client, pytest.raises(RuntimeError, match="model may have run") as error:
        run(args("project", "playground", "run", "--file", input_file(tmp_path)), client)
    assert "private-provider-details" not in str(error.value)
    assert len([r for r in requests if r.method == "POST"]) == 1


@pytest.mark.parametrize(
    "updates",
    [
        {"projectId": "other"},
        {"modelParams": {"provider": "gateway", "model": "test", "adapter": "openai"}},
        {"variables": {}},
        {"prompt": {"name": "test", "version": 1, "label": "latest"}},
        {"messages": [{"role": "user", "content": []}]},
        {
            "tools": [{"name": "test", "description": "", "parameters": {}}],
            "structuredOutputSchema": {},
        },
    ],
)
def test_bad_inputs_fail_before_any_request(updates, tmp_path):
    (client, requests) = api()
    with client, pytest.raises(ValueError):
        run(args("project", "playground", "run", "--file", input_file(tmp_path, **updates)), client)
    assert requests == []


def test_missing_variable_in_saved_prompt_stops_before_model_call(tmp_path):
    (client, requests) = api(
        lambda _: httpx.Response(
            200, json={"name": "support", "type": "text", "version": 1, "prompt": "{{missing}}"}
        )
    )
    with client, pytest.raises(ValueError, match="Missing prompt variable"):
        run(
            args(
                "project",
                "playground",
                "run",
                "--file",
                input_file(tmp_path, prompt={"name": "support"}),
            ),
            client,
        )
    assert all(r.method == "GET" for r in requests)


def test_local_validate_needs_no_credentials(tmp_path, monkeypatch, capsys):
    for name in (
        "LANGFUSE_BASE_URL",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_PROJECT_ID",
        "LANGFUSE_SESSION_COOKIE",
    ):
        monkeypatch.delenv(name, raising=False)
    assert (
        main(
            [
                "--env",
                str(tmp_path / "absent.env"),
                "project",
                "playground",
                "validate",
                "--file",
                input_file(tmp_path),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["valid"] is True


def test_tool_messages_and_literal_variable_replacements():
    result = compile_messages(
        [
            {"role": "user", "content": "{{question}}"},
            {
                "role": "assistant",
                "content": "",
                "toolCalls": [{"id": "call1", "name": "weather", "args": {}}],
            },
            {"role": "tool", "content": "sunny", "tool_call_id": "call1"},
        ],
        {"question": "{{literal}}"},
        {},
    )
    assert result[0]["content"] == "{{literal}}"
    assert result[1]["type"] == "assistant-tool-call"
    assert result[2]["toolCallId"] == "call1"


def test_batch_preview_is_offline_and_playground_input_is_validated(tmp_path, capsys):
    input_file(tmp_path)
    batch = tmp_path / "batch.json"
    batch.write_text(
        json.dumps(
            {
                "commands": [
                    ["project", "llms", "list"],
                    ["project", "playground", "run", "--file", "input.json"],
                ]
            }
        )
    )
    (client, requests) = api(cookie="")
    with client:
        assert run(args("workflow", "run", "--file", str(batch), "--dry-run"), client) == 0
    assert requests == []
    assert json.loads(capsys.readouterr().out)["completed"] == 2
    input_file(tmp_path, variables={})
    with pytest.raises(ValueError, match="Missing prompt variable"):
        load_input(Path(tmp_path / "input.json"))


def test_batch_missing_cookie_is_detected_before_earlier_writes(tmp_path):
    input_file(tmp_path)
    (tmp_path / "dataset.json").write_text('{"name":"synthetic"}')
    batch = tmp_path / "batch.json"
    batch.write_text(
        json.dumps(
            {
                "commands": [
                    ["project", "datasets", "upsert", "--file", "dataset.json"],
                    ["project", "playground", "run", "--file", "input.json"],
                ]
            }
        )
    )
    (client, requests) = api(cookie="")
    with client, pytest.raises(ValueError, match="LANGFUSE_SESSION_COOKIE"):
        run(args("workflow", "run", "--file", str(batch)), client)
    assert requests == []
