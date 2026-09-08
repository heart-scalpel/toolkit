import ast
import base64
import json
from pathlib import Path

import httpx
import pytest

from app.application import dispatch, prepare
from app.cli import build_parser, main, run
from app.command_parser import to_command
from app.core.config import Config, KeyPair
from app.core.http import HttpClient
from app.projects.queries import ResourceRequest
from app.projects.resources import execute
from app.runtime import Runtime
from app.workflows.batch import execute_batch


@pytest.fixture(autouse=True)
def clean_credentials(monkeypatch):
    import os

    for key in os.environ:
        if key.startswith("LANGFUSE_"):
            monkeypatch.delenv(key, raising=False)


def command(*argv):
    return prepare(to_command(build_parser().parse_args(argv)))


def test_instance_health_works_without_keys_and_never_sends_auth(tmp_path, monkeypatch, capsys):
    env = tmp_path / "connection.env"
    env.write_text("LANGFUSE_BASE_URL=http://test\n")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"status": "OK", "version": "test"})

    monkeypatch.setattr(
        "app.cli.Runtime", lambda config: Runtime(config, transport=httpx.MockTransport(handler))
    )
    assert main(["--env", str(env), "instance", "health"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "OK"
    assert len(calls) == 1 and calls[0].url.path == "/api/public/health"
    assert "authorization" not in calls[0].headers and "cookie" not in calls[0].headers


def test_organization_discovery_needs_no_project_configuration(capsys):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"projects": [{"id": "p1", "name": "one"}]})

    with Runtime(
        Config(base_url="http://test", organization_keys=KeyPair("org-public", "org-secret")),
        transport=httpx.MockTransport(handler),
    ) as runtime:
        assert run(build_parser().parse_args(["org", "projects", "list"]), runtime) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["scope"] == "organization"
    assert "configuredProjectId" not in result
    assert len(requests) == 1
    assert (
        base64.b64decode(requests[0].headers["authorization"].split()[1]).decode()
        == "org-public:org-secret"
    )


def test_project_key_never_falls_back_to_organization_requests():
    with (
        Runtime(
            Config(base_url="http://test", project_keys=KeyPair("p", "s")),
            transport=httpx.MockTransport(lambda _: pytest.fail("HTTP used")),
        ) as runtime,
        pytest.raises(ValueError, match="LANGFUSE_ORG_PUBLIC_KEY"),
    ):
        dispatch(command("org", "projects", "list"), runtime)


def test_organization_key_never_falls_back_to_project_requests():
    with (
        Runtime(
            Config(base_url="http://test", organization_keys=KeyPair("org", "secret")),
            transport=httpx.MockTransport(lambda _: pytest.fail("HTTP used")),
        ) as runtime,
        pytest.raises(ValueError, match="LANGFUSE_PROJECT_PUBLIC_KEY"),
    ):
        dispatch(command("project", "info"), runtime)


def test_mixed_scope_workflow_selects_credentials_without_switching_env(tmp_path, capsys):
    workflow = tmp_path / "workflow.json"
    workflow.write_text(
        json.dumps(
            {
                "commands": [
                    ["instance", "health"],
                    ["org", "projects", "list"],
                    ["project", "llms", "list"],
                ]
            }
        )
    )
    requests = []

    def handler(request):
        requests.append(request)
        path = request.url.path
        if path.endswith("/organizations/projects"):
            return httpx.Response(200, json={"projects": [{"id": "p1", "name": "one"}]})
        if path.endswith("/projects"):
            return httpx.Response(200, json={"data": [{"id": "p1", "name": "one"}]})
        if path.endswith("/health"):
            return httpx.Response(200, json={"status": "OK"})
        return httpx.Response(200, json={"data": [], "meta": {"totalPages": 1}})

    config = Config(
        "http://test",
        "p1",
        KeyPair("project-public", "project-secret"),
        KeyPair("org-public", "org-secret"),
        "next-auth.session-token=unused-cookie",
    )
    with Runtime(config, transport=httpx.MockTransport(handler)) as runtime:
        assert (
            run(build_parser().parse_args(["workflow", "run", "--file", str(workflow)]), runtime)
            == 0
        )
    output = json.loads(capsys.readouterr().out)
    assert [step["command"] for step in output["results"]] == [
        "instance health",
        "org projects list",
        "project llms list",
    ]
    for request in requests:
        assert "cookie" not in request.headers
        if request.url.path.endswith("/health"):
            assert "authorization" not in request.headers
        else:
            auth = base64.b64decode(request.headers["authorization"].split()[1]).decode()
            assert auth == (
                "org-public:org-secret"
                if "/organizations/" in request.url.path
                else "project-public:project-secret"
            )


def test_missing_later_scope_credentials_stops_workflow_before_first_write(tmp_path):
    (tmp_path / "dataset.json").write_text('{"name":"synthetic"}')
    workflow = tmp_path / "workflow.json"
    workflow.write_text(
        json.dumps(
            {
                "commands": [
                    ["project", "datasets", "upsert", "--file", "dataset.json"],
                    ["org", "projects", "list"],
                ]
            }
        )
    )
    with (
        Runtime(
            Config("http://test", "p1", KeyPair("p", "s")),
            transport=httpx.MockTransport(
                lambda _: pytest.fail("HTTP before local credential preflight")
            ),
        ) as runtime,
        pytest.raises(ValueError, match="LANGFUSE_ORG"),
    ):
        run(build_parser().parse_args(["workflow", "run", "--file", str(workflow)]), runtime)


@pytest.mark.parametrize("action,extra", [("validate", []), ("run", ["--dry-run"])])
def test_workflow_offline_modes_need_no_connection_or_keys(tmp_path, action, extra, capsys):
    (tmp_path / "dataset.json").write_text('{"name":"synthetic"}')
    workflow = tmp_path / "workflow.json"
    workflow.write_text(
        json.dumps(
            {
                "commands": [
                    ["instance", "health"],
                    ["org", "projects", "list"],
                    ["project", "datasets", "upsert", "--file", "dataset.json"],
                ]
            }
        )
    )
    with Runtime(
        Config(), transport=httpx.MockTransport(lambda _: pytest.fail("HTTP used"))
    ) as runtime:
        assert (
            run(
                build_parser().parse_args(["workflow", action, "--file", str(workflow), *extra]),
                runtime,
            )
            == 0
        )
    result = json.loads(capsys.readouterr().out)
    assert result.get("valid", result.get("success")) is True


def test_batch_uses_return_values_and_does_not_parse_stdout(capsys):
    prepared = command("instance", "health")
    value = {"message": "not serialized beforehand", "items": [1, {"n": 2}]}
    result = execute_batch([prepared], lambda _: value)
    assert result["results"][0]["result"] is value
    assert capsys.readouterr().out == ""


def test_business_dispatch_returns_data_without_printing(capsys):
    prepared = command("project", "prompts", "list")

    def handler(request):
        return (
            httpx.Response(200, json={"data": [{"id": "p1", "name": "one"}]})
            if request.url.path.endswith("/projects")
            else httpx.Response(200, json={"data": [], "meta": {"totalPages": 1}})
        )

    with Runtime(
        Config("http://test", "p1", KeyPair("p", "s")), transport=httpx.MockTransport(handler)
    ) as runtime:
        assert dispatch(prepared, runtime) == {"count": 0, "data": []}
    assert capsys.readouterr().out == ""


def test_domain_resources_do_not_require_argparse_objects():
    def handler(request):
        return (
            httpx.Response(200, json={"data": [{"id": "p1", "name": "one"}]})
            if request.url.path.endswith("/projects")
            else httpx.Response(200, json={"data": [], "meta": {"totalPages": 1}})
        )

    with Runtime(
        Config("http://test", "p1", KeyPair("p", "s")), transport=httpx.MockTransport(handler)
    ) as runtime:
        result = execute(ResourceRequest("datasets", "list", all_pages=True), runtime.project)
    assert result["complete"] is True


def test_project_transport_rejects_organization_and_session_endpoints():
    with Runtime(
        Config("http://test", "p1", KeyPair("p", "s")),
        transport=httpx.MockTransport(lambda _: pytest.fail("HTTP used")),
    ) as runtime:
        for path in ("/api/public/organizations/projects", "/api/chatCompletion"):
            with pytest.raises(ValueError, match="does not belong"):
                runtime.project.request("GET", path)


def test_raw_transport_rejects_other_origins_without_forwarding_auth():
    http = HttpClient(
        "http://test",
        auth=("p", "s"),
        transport=httpx.MockTransport(lambda _: pytest.fail("HTTP used")),
    )
    try:
        with pytest.raises(ValueError, match="relative"):
            http.request("GET", "https://other.test/api/public/projects")
    finally:
        http.close()


def test_config_keeps_key_families_separate_and_does_not_mutate_environment(tmp_path, monkeypatch):
    import os

    env = tmp_path / "config.env"
    env.write_text(
        "LANGFUSE_BASE_URL=http://test\nLANGFUSE_PROJECT_PUBLIC_KEY=file-public\nLANGFUSE_PROJECT_SECRET_KEY=file-secret\nLANGFUSE_ORG_PUBLIC_KEY=org-public\nLANGFUSE_ORG_SECRET_KEY=org-secret\nLANGFUSE_SESSION_COOKIE=session-secret\n"
    )
    monkeypatch.setenv("LANGFUSE_PROJECT_PUBLIC_KEY", "env-public")
    before = dict(os.environ)
    config = Config.load(env)
    assert config.project_keys.require("LANGFUSE_PROJECT") == ("env-public", "file-secret")
    assert config.organization_keys.require("LANGFUSE_ORG") == ("org-public", "org-secret")
    assert dict(os.environ) == before
    assert not any(
        value in repr(config)
        for value in ("env-public", "file-secret", "org-secret", "session-secret")
    )


def test_legacy_project_names_still_work_but_do_not_supply_org_keys(tmp_path):
    env = tmp_path / "config.env"
    env.write_text("LANGFUSE_PUBLIC_KEY=old-public\nLANGFUSE_SECRET_KEY=old-secret\n")
    config = Config.load(env)
    assert config.project_keys.require("LANGFUSE_PROJECT") == ("old-public", "old-secret")
    with pytest.raises(ValueError, match="LANGFUSE_ORG"):
        config.organization_keys.require("LANGFUSE_ORG")


def test_partial_new_key_pair_never_borrows_legacy_secret(tmp_path):
    env = tmp_path / "config.env"
    env.write_text("LANGFUSE_PROJECT_PUBLIC_KEY=new-public\nLANGFUSE_SECRET_KEY=old-secret\n")
    with pytest.raises(ValueError, match="LANGFUSE_PROJECT"):
        Config.load(env).project_keys.require("LANGFUSE_PROJECT")


def test_legacy_environment_overrides_new_names_in_file(tmp_path, monkeypatch):
    env = tmp_path / "config.env"
    env.write_text(
        "LANGFUSE_PROJECT_PUBLIC_KEY=file-public\nLANGFUSE_PROJECT_SECRET_KEY=file-secret\n"
    )
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "env-public")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "env-secret")
    assert Config.load(env).project_keys.require("LANGFUSE_PROJECT") == ("env-public", "env-secret")


def test_unconfirmed_programmatic_delete_is_blocked():
    prepared = command("project", "items", "delete", "item")
    with (
        Runtime(
            Config(), transport=httpx.MockTransport(lambda _: pytest.fail("HTTP used"))
        ) as runtime,
        pytest.raises(ValueError, match="confirmation"),
    ):
        dispatch(prepared, runtime)


def test_layer_dependencies_do_not_point_back_to_cli_or_application():
    root = Path(__file__).resolve().parents[1] / "app"
    for layer in ("core", "instance", "organizations", "projects", "workflows"):
        for path in (root / layer).glob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                modules = (
                    [node.module or ""]
                    if isinstance(node, ast.ImportFrom)
                    else [item.name for item in node.names]
                    if isinstance(node, ast.Import)
                    else []
                )
                for module in modules:
                    assert module not in {
                        "argparse",
                        "app.cli",
                        "app.command_parser",
                        "app.application",
                        "app.runtime",
                    }, (path, module)
                    if module.startswith("app."):
                        assert module.startswith("app.core.") or module.startswith(
                            f"app.{layer}."
                        ), (path, module)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    assert node.func.id not in {"print", "input"}, path
