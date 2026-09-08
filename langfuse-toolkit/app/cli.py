"""Console adapter: parse, confirm destructive actions, and render returned data."""

import json
import sys
from dataclasses import replace

from app.application import dispatch, preflight, prepare
from app.command_parser import build_parser, to_command
from app.core.config import Config
from app.runtime import Runtime
from app.workflows.batch import execute_batch, read_commands


def prepare_workflow(path, *, offline=False):
    parser = build_parser()
    prepared = []
    for index, argv in enumerate(read_commands(path), 1):
        if any(arg == "--env" or arg.startswith("--env=") for arg in argv):
            raise ValueError("Per-step credential overrides are not supported")
        try:
            args = parser.parse_args(argv)
        except SystemExit:
            raise ValueError(f"Invalid workflow command {index}") from None
        command = to_command(args)
        if command.scope == "workflow":
            raise ValueError("Nested workflows are not supported")
        if "file" in command.arguments:
            command.arguments["file"] = (path.parent / command.arguments["file"]).resolve()
        item = prepare(command)
        if item.delete_target and not (offline or command.dry_run or command.confirmed):
            raise ValueError(f"Workflow deletion in command {index} requires explicit --yes")
        prepared.append(item)
    return prepared


def run(args, runtime):
    command = to_command(args)
    if command.scope == "workflow":
        offline = command.action == "validate" or command.dry_run
        commands = prepare_workflow(command.arguments["file"], offline=offline)
        if command.action == "validate":
            result = {"valid": True, "steps": len(commands)}
        else:
            if not offline:
                preflight(commands, runtime)
            result = execute_batch(commands, lambda item: dispatch(item, runtime, offline=offline))
        status = 0 if result.get("success", True) else 1
    else:
        item = prepare(command)
        if item.delete_target and not (command.dry_run or command.confirmed):
            if not sys.stdin.isatty():
                raise ValueError("Deletion needs a terminal confirmation or explicit --yes")
            if (
                input(f"Permanently delete {item.delete_target}? Type the exact target: ")
                != item.delete_target
            ):
                print(json.dumps({"cancelled": True}))
                return 1
            item = replace(item, command=replace(command, confirmed=True))
        preflight([item], runtime)
        result = dispatch(item, runtime)
        status = 0
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return status


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        with Runtime(Config.load(args.env)) as runtime:
            return run(args, runtime)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
