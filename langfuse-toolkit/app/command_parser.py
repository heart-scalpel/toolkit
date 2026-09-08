"""CLI grammar and adaptation into application commands."""

import argparse
from pathlib import Path

from app.core.commands import Command
from app.projects.catalog import RESOURCES

ROOT = Path(__file__).resolve().parents[1]

OPTIONS = {
    "fromTimestamp": "from",
    "toTimestamp": "to",
    "fromStartTime": "from",
    "toStartTime": "to",
    "userId": "user-id",
    "sessionId": "session-id",
    "traceId": "trace-id",
    "observationId": "observation-id",
    "datasetName": "dataset",
    "datasetId": "dataset-id",
    "sourceTraceId": "source-trace-id",
    "sourceObservationId": "source-observation-id",
    "runName": "run-name",
    "configId": "config-id",
    "dataType": "data-type",
    "experimentId": "experiment-id",
    "experimentName": "experiment-name",
}


def add_prompt_commands(actions):
    listing = actions.add_parser("list", help="List prompt metadata, automatically following pages")
    for field in ("name", "label", "tag"):
        listing.add_argument(f"--{field}")
    get = actions.add_parser("get", help="Read one prompt; defaults to latest for maintenance")
    get.add_argument("name")
    selector = get.add_mutually_exclusive_group()
    selector.add_argument("--version", type=int)
    selector.add_argument("--label")
    validate = actions.add_parser(
        "validate", help="Validate a local definition without contacting API"
    )
    validate.add_argument("--file", type=Path, required=True)
    save = actions.add_parser(
        "save", help="Create a prompt or append a new version from a definition"
    )
    save.add_argument("--file", type=Path, required=True)
    save.add_argument("--commit-message", help="Override the definition's commitMessage")
    save.add_argument(
        "--dry-run", action="store_true", help="Read current version and show diff; no writes"
    )
    label = actions.add_parser(
        "label", help="Assign/move labels to a version (publish or roll back)"
    )
    label.add_argument("name")
    label.add_argument("--version", type=int, required=True)
    label.add_argument("--label", action="append", required=True, dest="labels")
    label.add_argument("--dry-run", action="store_true")
    delete = actions.add_parser("delete", help="Permanently delete one exact prompt version")
    delete.add_argument("name")
    delete.add_argument("--version", type=int, required=True)
    delete.add_argument("--dry-run", action="store_true")
    delete.add_argument(
        "--yes", action="store_true", help="Skip the typed name/version confirmation"
    )


def add_resource_commands(actions):
    for name, spec in RESOURCES.items():
        help_text = f"Manage {name} through the public API"
        if name in ("runs", "run-items"):
            help_text += " (legacy Langfuse v3 dataset runs)"
        root = actions.add_parser(name, help=help_text)
        root.set_defaults(resource=name)
        sub = root.add_subparsers(dest="action", required=True)
        for action in spec.actions:
            parser = sub.add_parser(action)
            if name == "runs":
                parser.add_argument("--dataset", required=True)
            if action in ("get", "delete", "update"):
                parser.add_argument("identifier", help="Exact resource name or ID")
            if name in ("traces", "sessions", "observations", "scores") and action in (
                "list",
                "get",
            ):
                parser.add_argument(
                    "--legacy", action="store_true", help="Use the legacy Langfuse v3 read endpoint"
                )
            if name in ("traces", "sessions", "observations") and action == "get":
                parser.add_argument("--from", dest="fromStartTime")
                parser.add_argument("--to", dest="toStartTime")
                parser.add_argument("--fields", default="core,basic,io,metadata,usage")
                parser.add_argument("--max-pages", type=int, default=100)
                if name == "observations":
                    parser.add_argument("--trace-id", dest="traceId")
            if action == "list":
                parser.add_argument("--limit", type=int, default=50, help="Page size, 1-100")
                parser.add_argument("--all", action="store_true", dest="all_pages")
                parser.add_argument(
                    "--max-pages", type=int, default=100, help="Stop with an error if exceeded"
                )
                for field in spec.filters:
                    parser.add_argument("--" + OPTIONS.get(field, field), dest=field)
                if name == "scores":
                    parser.add_argument(
                        "--id", help="Score ID filter; requires the default v3 scores API"
                    )
            if action in ("create", "upsert", "update"):
                parser.add_argument("--file", type=Path, required=True, help="JSON request body")
            if action in ("create", "upsert", "update", "delete"):
                parser.add_argument(
                    "--dry-run",
                    action="store_true",
                    help="Validate and show the request without writing",
                )
            if action == "delete":
                parser.add_argument("--yes", action="store_true")


def add_playground_commands(actions):
    root = actions.add_parser("playground", help="Run prompts using the project's configured LLMs")
    root.set_defaults(resource="playground")
    commands = root.add_subparsers(dest="action", required=True)
    for action in ("validate", "run"):
        parser = commands.add_parser(
            action, help="Validate input locally" if action == "validate" else "Execute Playground"
        )
        parser.add_argument("--file", type=Path, required=True, help="Playground input JSON")
        if action == "run":
            parser.add_argument(
                "--dry-run",
                action="store_true",
                help="Read connection and prompt, preview without calling the model",
            )


def build_parser():
    parser = argparse.ArgumentParser(
        description="Langfuse automation by instance, organization and project", allow_abbrev=False
    )
    parser.add_argument("--env", type=Path, default=ROOT / ".env")
    scopes = parser.add_subparsers(dest="scope", required=True)
    instance = scopes.add_parser("instance", help="Server health; no API key required")
    instance.add_subparsers(dest="resource", required=True).add_parser("health").set_defaults(
        action="get"
    )
    org = scopes.add_parser("org", help="Organization administration with organization API keys")
    org_resources = org.add_subparsers(dest="resource", required=True)
    org_resources.add_parser("projects").add_subparsers(dest="action", required=True).add_parser(
        "list"
    )
    project = scopes.add_parser("project", help="Project resources with project API keys")
    resources = project.add_subparsers(dest="resource", required=True)
    resources.add_parser(
        "info", help="Discover the project associated with the configured key"
    ).set_defaults(action="get")
    resources.add_parser("check", help="Verify LANGFUSE_PROJECT_ID against the key").set_defaults(
        action="get"
    )
    prompts = resources.add_parser("prompts")
    add_prompt_commands(prompts.add_subparsers(dest="action", required=True))
    add_resource_commands(resources)
    add_playground_commands(resources)
    workflow = scopes.add_parser("workflow", help="Sequential workflows across explicit scopes")
    runs = workflow.add_subparsers(dest="action", required=True)
    for action in ("run", "validate"):
        item = runs.add_parser(action)
        item.set_defaults(resource="batch")
        item.add_argument("--file", type=Path, required=True)
        if action == "run":
            item.add_argument("--dry-run", action="store_true")
    return parser


def to_command(args):
    options = {
        key: value
        for key, value in vars(args).items()
        if key not in {"scope", "resource", "action", "env", "dry_run", "yes"}
    }
    return Command(
        "organization" if args.scope == "org" else args.scope,
        args.resource,
        args.action,
        options,
        getattr(args, "dry_run", False),
        getattr(args, "yes", False),
    )
