import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from app.cli import build_parser, main, run
from app.core.config import KeyPair
from app.core.errors import ApiError
from app.projects.prompt_definitions import load_definition
from app.runtime import Runtime
from tests.support import make_runtime

PROJECT = {"id": "project-a", "name": "Test project"}
NAME = "medical/folder/prompt"
PROMPT = {
    "name": NAME,
    "version": 2,
    "type": "chat",
    "prompt": [{"role": "system", "content": "Original {{variable}}"}],
    "config": {"model": "existing-model", "temperature": 0.3},
    "tags": ["medical"],
    "labels": ["latest", "production"],
}


class Server:
    """An API contract double: maintain versions/labels across real HTTP requests."""

    def __init__(self):
        self.requests = []
        self.project = deepcopy(PROJECT)
        self.versions = {2: deepcopy(PROMPT)}

    def __call__(self, request):
        self.requests.append(request)
        path = request.url.path
        if path == "/api/public/projects":
            return httpx.Response(200, json={"data": [self.project]})
        if request.method == "GET" and path == "/api/public/v2/prompts":
            rows = [{"name": NAME, "versions": sorted(self.versions)}] if self.versions else []
            return httpx.Response(
                200, json={"data": rows, "meta": {"totalPages": 1, "totalItems": len(rows)}}
            )
        if request.method == "POST" and path == "/api/public/v2/prompts":
            payload = json.loads(request.content)
            version = max(self.versions, default=0) + 1
            payload.update(version=version, labels=[*payload["labels"], "latest"])
            self.versions[version] = payload
            return httpx.Response(200, json=payload)
        if request.method == "PATCH":
            version = int(path.rsplit("/", 1)[-1])
            labels = json.loads(request.content)["newLabels"]
            for number, prompt in self.versions.items():
                if number != version:
                    prompt["labels"] = [label for label in prompt["labels"] if label not in labels]
            target = self.versions[version]
            target["labels"] = list(dict.fromkeys([*target["labels"], *labels]))
            return httpx.Response(200, json=target)
        if request.method == "DELETE":
            del self.versions[int(request.url.params["version"])]
            return httpx.Response(204)
        if request.method == "GET" and path == f"/api/public/v2/prompts/{NAME}":
            if "version" in request.url.params:
                prompt = self.versions.get(int(request.url.params["version"]))
            else:
                label = request.url.params["label"]
                prompt = next(
                    (p for p in reversed(list(self.versions.values())) if label in p["labels"]),
                    None,
                )
            return httpx.Response(200, json=prompt) if prompt else httpx.Response(404, json={})
        return httpx.Response(404, json={})


def client(handler):
    return make_runtime(
        "http://langfuse.test",
        "public-test",
        "secret-test",
        PROJECT["id"],
        transport=httpx.MockTransport(handler),
    )


def definition(tmp_path, **extra):
    path = tmp_path / "prompt.json"
    path.write_text(
        json.dumps(
            {
                "name": NAME,
                "type": "chat",
                "prompt": [{"role": "system", "content": "Updated {{variable}}"}],
                **extra,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_wrong_project_blocks_mutation():
    server = Server()
    server.project["id"] = "other-project"
    with client(server) as api, pytest.raises(ValueError, match="does not match"):
        api.prompts.create_version(PROMPT)
    assert [request.method for request in server.requests] == ["GET"]
    assert server.requests[0].url.path == "/api/public/projects"


def test_list_follows_pages_and_retains_filters():
    pages = []

    def handler(request):
        if request.url.path.endswith("/projects"):
            return httpx.Response(200, json={"data": [PROJECT]})
        pages.append(dict(request.url.params))
        return httpx.Response(
            200,
            json={
                "data": [{"name": "prompt-" + request.url.params["page"]}],
                "meta": {"totalPages": 2, "totalItems": 2},
            },
        )

    with client(handler) as api:
        assert [item["name"] for item in api.prompts.list_prompts(tag="medical")] == [
            "prompt-1",
            "prompt-2",
        ]
    assert pages == [
        {"tag": "medical", "page": "1", "limit": "100"},
        {"tag": "medical", "page": "2", "limit": "100"},
    ]


def test_nested_name_is_encoded_and_maintenance_defaults_to_latest():
    server = Server()
    with client(server) as api:
        assert api.prompts.get_prompt(NAME)["version"] == 2
    request = server.requests[-1]
    assert b"medical%2Ffolder%2Fprompt" in request.url.raw_path
    assert dict(request.url.params) == {"resolve": "false", "label": "latest"}
    assert request.headers["authorization"].startswith("Basic ")


def test_save_preserves_config_tags_and_does_not_promote_production(tmp_path):
    server = Server()
    with client(server) as api:
        (payload, current) = api.prompts.prepare_save(load_definition(definition(tmp_path)))
        assert current["version"] == 2
        saved = api.prompts.create_version(payload)
    assert saved["version"] == 3
    assert saved["config"] == PROMPT["config"]
    assert saved["tags"] == ["medical"]
    assert saved["labels"] == ["latest"]
    assert saved["prompt"][0]["content"] == "Updated {{variable}}"
    assert [r.method for r in server.requests] == ["GET", "GET", "POST", "GET"]
    assert server.requests[-1].url.params["version"] == "3"


def test_new_prompt_404_is_checked_against_list_before_creation(tmp_path):
    server = Server()
    server.versions = {}
    with client(server) as api:
        (payload, current) = api.prompts.prepare_save(load_definition(definition(tmp_path)))
        assert current is None
        assert api.prompts.create_version(payload)["version"] == 1
    assert any(
        r.url.path == "/api/public/v2/prompts" and r.method == "GET" for r in server.requests
    )


def test_existing_prompt_missing_latest_does_not_create(tmp_path):
    server = Server()
    server.versions[2]["labels"] = ["production"]
    with client(server) as api, pytest.raises(RuntimeError, match="latest could not be read"):
        api.prompts.prepare_save(load_definition(definition(tmp_path)))
    assert all(r.method == "GET" for r in server.requests)


def test_save_dry_run_reads_but_never_writes(tmp_path, capsys):
    server = Server()
    args = build_parser().parse_args(
        ["project", "prompts", "save", "--file", str(definition(tmp_path)), "--dry-run"]
    )
    with client(server) as api:
        assert run(args, api) == 0
    assert all(r.method == "GET" for r in server.requests)
    output = capsys.readouterr().out
    assert "Original {{variable}}" in output and "Updated {{variable}}" in output
    assert '"dryRun": true' in output


def test_label_can_roll_production_back_to_a_prior_version():
    server = Server()
    server.versions[1] = {**deepcopy(PROMPT), "version": 1, "labels": ["staging"]}
    with client(server) as api:
        saved = api.prompts.assign_labels(NAME, 1, ["production"])
    assert set(saved["labels"]) == {"staging", "production"}
    assert "production" not in server.versions[2]["labels"]
    patch = next(r for r in server.requests if r.method == "PATCH")
    assert json.loads(patch.content) == {"newLabels": ["production"]}
    assert patch.url.raw_path.endswith(b"/medical%2Ffolder%2Fprompt/versions/1")


def test_latest_label_cannot_be_assigned():
    server = Server()
    with client(server) as api, pytest.raises(ValueError, match="managed by Langfuse"):
        api.prompts.assign_labels(NAME, 2, ["latest"])
    assert not server.requests


def test_delete_only_one_version_and_verify_absence():
    server = Server()
    server.versions[1] = {**deepcopy(PROMPT), "version": 1}
    with client(server) as api:
        api.prompts.delete_version(NAME, 1)
    assert set(server.versions) == {2}
    deleted = next(r for r in server.requests if r.method == "DELETE")
    assert dict(deleted.url.params) == {"version": "1"}
    assert server.requests[-1].method == "GET"


def test_delete_noninteractive_requires_explicit_yes(monkeypatch):
    server = Server()
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    args = build_parser().parse_args(["project", "prompts", "delete", NAME, "--version", "2"])
    with client(server) as api, pytest.raises(ValueError, match="explicit --yes"):
        run(args, api)
    assert all(r.method == "GET" for r in server.requests)


@pytest.mark.parametrize("command", ["label", "delete"])
def test_label_and_delete_dry_run_never_mutate(command, capsys):
    server = Server()
    argv = ["project", "prompts", command, NAME, "--version", "2", "--dry-run"]
    if command == "label":
        argv += ["--label", "production"]
    with client(server) as api:
        assert run(build_parser().parse_args(argv), api) == 0
    assert all(r.method == "GET" for r in server.requests)
    assert '"dryRun": true' in capsys.readouterr().out


def test_http_error_omits_response_body_and_credentials():
    with (
        client(lambda _: httpx.Response(401, text="secret-test")) as api,
        pytest.raises(ApiError) as error,
    ):
        api.project.check()
    assert "secret-test" not in str(error.value)
    assert "HTTP 401" in str(error.value)


def test_redirect_does_not_forward_credentials():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "http://other-host.test/"})

    with client(handler) as api, pytest.raises(ApiError):
        api.project.check()
    assert len(requests) == 1
    assert requests[0].url.host == "langfuse.test"


def test_ambiguous_write_timeout_is_not_retried():
    server = Server()

    def handler(request):
        if request.method == "POST":
            server.requests.append(request)
            raise httpx.ReadTimeout("secret-test", request=request)
        return server(request)

    with client(handler) as api, pytest.raises(RuntimeError, match="outcome is unknown") as error:
        api.prompts.create_version(PROMPT)
    assert sum(r.method == "POST" for r in server.requests) == 1
    assert "secret-test" not in str(error.value)


def test_definition_resolves_relative_files_and_supports_placeholders(tmp_path):
    (tmp_path / "system.txt").write_text("你好 {{user}}", encoding="utf-8")
    (tmp_path / "config.json").write_text('{"temperature": 0.1}', encoding="utf-8")
    path = definition(
        tmp_path,
        prompt=[
            {"role": "system", "contentFile": "system.txt"},
            {"type": "placeholder", "name": "history"},
        ],
        configFile="config.json",
    )
    payload = load_definition(path)
    assert payload["prompt"] == [
        {"role": "system", "content": "你好 {{user}}"},
        {"type": "placeholder", "name": "history"},
    ]
    assert payload["config"] == {"temperature": 0.1}
    assert "configFile" not in payload


@pytest.mark.parametrize(
    "extra",
    [
        {"labels": ["latest"]},
        {"unexpected": True},
        {"prompt": [{"role": "user", "content": "x", "contentFile": "x"}]},
    ],
)
def test_invalid_definition_fails_before_api(tmp_path, extra):
    with pytest.raises(ValueError):
        load_definition(definition(tmp_path, **extra))


def test_validate_builtin_definitions_is_offline(monkeypatch, capsys):
    monkeypatch.setattr(
        "app.core.http.HttpClient.request", lambda *args, **kwargs: pytest.fail("API used")
    )
    root = Path(__file__).resolve().parents[1]
    for name in ("questions", "review"):
        assert (
            main(
                [
                    "project",
                    "prompts",
                    "validate",
                    "--file",
                    str(root / "definitions" / f"{name}.json"),
                ]
            )
            == 0
        )
    assert capsys.readouterr().out.count('"valid": true') == 2


def test_text_file_definition_can_create_a_new_prompt(tmp_path):
    server = Server()
    server.versions = {}
    (tmp_path / "text.txt").write_text("Summarize {{text}}", encoding="utf-8")
    path = tmp_path / "text.json"
    path.write_text(json.dumps({"name": NAME, "type": "text", "promptFile": "text.txt"}))
    with client(server) as api:
        (payload, _) = api.prompts.prepare_save(load_definition(path))
        saved = api.prompts.create_version(payload)
    assert saved["prompt"] == "Summarize {{text}}"
    assert saved["type"] == "text"


def test_save_does_not_report_success_when_server_changes_content(tmp_path):
    server = Server()

    def handler(request):
        response = server(request)
        if request.method == "POST":
            server.versions[3]["prompt"] = [{"role": "system", "content": "Unexpected"}]
        return response

    with client(handler) as api:
        (payload, _) = api.prompts.prepare_save(load_definition(definition(tmp_path)))
        with pytest.raises(RuntimeError, match="read-back differs"):
            api.prompts.create_version(payload)
    assert sum(request.method == "POST" for request in server.requests) == 1


@pytest.mark.parametrize("configured_id", ["", "a-different-project"])
def test_projects_cli_works_before_selecting_a_matching_project(configured_id, monkeypatch, capsys):
    server = Server()
    for key, value in {
        "LANGFUSE_BASE_URL": "http://langfuse.test",
        "LANGFUSE_PUBLIC_KEY": "public-test",
        "LANGFUSE_SECRET_KEY": "secret-test",
        "LANGFUSE_PROJECT_ID": configured_id,
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(
        "app.cli.Runtime", lambda config: Runtime(config, transport=httpx.MockTransport(server))
    )
    assert main(["project", "info"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["count"] == 1
    assert result["data"] == [PROJECT]
    assert result["scope"] == "project"
    assert result["configuredProjectVisible"] == (False if configured_id else None)
    assert [r.url.path for r in server.requests] == ["/api/public/projects"]
    assert all(r.method == "GET" for r in server.requests)


def test_organization_projects_uses_organization_endpoint_and_response_shape(capsys):
    projects = [PROJECT, {"id": "project-b", "name": "Second project"}]
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"projects": projects})

    args = build_parser().parse_args(["org", "projects", "list"])
    with make_runtime(
        "http://langfuse.test",
        "",
        "",
        organization_keys=KeyPair("org-public", "org-secret"),
        transport=httpx.MockTransport(handler),
    ) as api:
        assert run(args, api) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["scope"] == "organization"
    assert result["data"] == projects
    assert "configuredProjectVisible" not in result
    assert [(r.method, r.url.path) for r in requests] == [
        ("GET", "/api/public/organizations/projects")
    ]
