"""Prepare and dispatch domain operations; no printing, prompts or argparse."""

import difflib
import json
from copy import deepcopy

from app.core.commands import PreparedCommand
from app.core.validation import positive_version, read_json, string_list, validate_name
from app.projects.catalog import RESOURCES
from app.projects.playground import PlaygroundService, load_input
from app.projects.prompt_definitions import load_definition
from app.projects.queries import ResourceRequest, plan
from app.projects.resources import execute


def prepare(command):
    options = command.arguments
    resource, action = command.resource, command.action
    target = None
    payload = None
    if command.scope == "project" and resource in RESOURCES:
        fields = set(RESOURCES[resource].filters) | {
            "fromStartTime",
            "toStartTime",
            "fields",
            "traceId",
            "id",
        }
        payload = ResourceRequest(
            resource,
            action,
            identifier=options.get("identifier"),
            dataset=options.get("dataset"),
            filters={
                key: value for key, value in options.items() if key in fields and value is not None
            },
            body=read_json(options["file"]) if "file" in options else None,
            limit=options.get("limit", 50),
            all_pages=options.get("all_pages", False),
            max_pages=options.get("max_pages", 100),
            legacy=options.get("legacy", False),
            dry_run=command.dry_run,
        )
        plan(payload)
        if action == "delete":
            target = f"project {resource}:{options.get('dataset', '')}/{options['identifier']}"
    elif command.scope == "project" and resource == "prompts":
        if action in ("save", "validate"):
            payload = load_definition(options["file"])
            if options.get("commit_message") is not None:
                payload["commitMessage"] = options["commit_message"]
        elif action != "list":
            validate_name(options["name"])
            if options.get("version") is not None:
                positive_version(options["version"])
            if action == "label":
                string_list(options["labels"], "labels")
            if action == "delete":
                target = f"{options['name']}@{options['version']}"
    elif command.scope == "project" and resource == "playground":
        payload = load_input(options["file"])
    elif (command.scope, resource) not in {
        ("instance", "health"),
        ("organization", "projects"),
        ("project", "info"),
        ("project", "check"),
    }:
        raise ValueError("Unsupported command scope or resource")
    return PreparedCommand(command, payload, target)


def requirements(prepared):
    command = prepared.command
    if command.scope == "instance":
        return {"instance"}
    if command.scope == "organization":
        return {"organization"}
    if command.action == "validate":
        return set()
    if command.resource in RESOURCES and command.dry_run:
        return set()
    needed = {"project"}
    if command.resource != "info":
        needed.add("project-check")
    if command.resource == "playground" and not command.dry_run:
        needed.add("session")
    return needed


def preflight(commands, runtime):
    needed = set().union(*(requirements(command) for command in commands))
    # Resolve all local credential requirements before the first HTTP request or mutation.
    if "session" in needed:
        runtime.session.require()
    if "organization" in needed:
        _ = runtime.organization
    if "project" in needed:
        _ = runtime.project
    if "instance" in needed:
        _ = runtime.instance
    if "project-check" in needed:
        runtime.project.check()


def summary(prompt):
    return {field: prompt.get(field) for field in ("name", "version", "type", "labels", "tags")}


def dispatch(prepared, runtime, *, offline=False):
    command = prepared.command
    options = command.arguments
    resource, action = command.resource, command.action
    if offline:
        if command.scope == "project" and resource in RESOURCES:
            request = plan(prepared.payload)
            return {
                "dryRun": True,
                "method": request.method,
                "path": request.path,
                "query": request.params,
                "body": request.body,
            }
        return {
            "dryRun": True,
            "command": command.name,
            "input": prepared.payload
            if prepared.payload is not None
            else {key: value for key, value in options.items() if key != "file"},
        }
    if prepared.delete_target and not (command.dry_run or command.confirmed):
        raise ValueError("Deletion requires confirmation or explicit --yes")
    if command.scope == "instance":
        return runtime.instance.health()
    if command.scope == "organization":
        projects = runtime.organization.list_projects()
        return {"scope": "organization", "count": len(projects), "data": projects}
    if resource == "info":
        projects = runtime.project.discover()
        project_id = runtime.config.project_id
        return {
            "scope": "project",
            "count": len(projects),
            "data": projects,
            "configuredProjectId": project_id or None,
            "configuredProjectVisible": any(project["id"] == project_id for project in projects)
            if project_id
            else None,
        }
    if resource == "check":
        return {"connected": True, "project": runtime.project.check()}
    if resource in RESOURCES:
        if command.dry_run:
            return dispatch(prepared, runtime, offline=True)
        return execute(prepared.payload, runtime.project)
    if resource == "playground":
        if action == "validate":
            params = prepared.payload["modelParams"]
            return {"valid": True, "provider": params["provider"], "model": params["model"]}
        return PlaygroundService(runtime.project, None if command.dry_run else runtime.session).run(
            prepared.payload, dry_run=command.dry_run
        )
    if action == "validate":
        return {"valid": True, "name": prepared.payload["name"], "type": prepared.payload["type"]}
    prompts = runtime.prompts
    if action == "list":
        rows = prompts.list_prompts(
            **{field: options.get(field) for field in ("name", "label", "tag")}
        )
        return {"count": len(rows), "data": rows}
    if action == "get":
        return prompts.get_prompt(
            options["name"], version=options.get("version"), label=options.get("label")
        )
    if action == "save":
        payload, current = prompts.prepare_save(deepcopy(prepared.payload))
        if command.dry_run:
            before = {key: current.get(key) for key in payload} if current else {}
            diff = "".join(
                difflib.unified_diff(
                    (json.dumps(before, ensure_ascii=False, indent=2) + "\n").splitlines(
                        keepends=True
                    ),
                    (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").splitlines(
                        keepends=True
                    ),
                    fromfile="current",
                    tofile="new version",
                )
            )
            return {
                "action": "create_version",
                "name": payload["name"],
                "currentVersion": current["version"] if current else None,
                "newVersionLabels": payload["labels"],
                "dryRun": True,
                "diff": diff,
            }
        return {"created": True, "verified": True, **summary(prompts.create_version(payload))}
    if action == "label":
        if command.dry_run:
            current = prompts.get_prompt(options["name"], version=options["version"])
            return {
                "action": "assign_labels",
                "dryRun": True,
                "prompt": summary(current),
                "assignLabels": options["labels"],
            }
        return {
            "updated": True,
            "verified": True,
            **summary(
                prompts.assign_labels(options["name"], options["version"], options["labels"])
            ),
        }
    if action == "delete":
        if command.dry_run:
            return {
                "action": "delete_version",
                "dryRun": True,
                "prompt": summary(prompts.get_prompt(options["name"], version=options["version"])),
            }
        prompts.delete_version(options["name"], options["version"])
        return {
            "deleted": True,
            "verified": True,
            "name": options["name"],
            "version": options["version"],
        }
    raise ValueError("Unsupported project action")
