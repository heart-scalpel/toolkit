"""Workflow validation and sequential execution with structured return values."""

from app.core.validation import read_json


def read_commands(path):
    data = read_json(path)
    if not isinstance(data, dict) or set(data) != {"commands"}:
        raise ValueError("Workflow file must contain only a commands array")
    commands = data["commands"]
    if not isinstance(commands, list) or not 1 <= len(commands) <= 1000:
        raise ValueError("Workflow requires 1-1000 commands")
    for index, argv in enumerate(commands, 1):
        if not isinstance(argv, list) or not argv or any(not isinstance(arg, str) for arg in argv):
            raise ValueError(f"Command {index} must be an array of argument strings")
    return commands


def execute_batch(commands, dispatch):
    results = []
    for index, prepared in enumerate(commands, 1):
        try:
            value = dispatch(prepared)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
            return {
                "success": False,
                "completed": index - 1,
                "failedStep": index,
                "error": str(error),
                "results": results,
            }
        results.append({"step": index, "command": prepared.command.name, "result": value})
    return {"success": True, "completed": len(commands), "results": results}
