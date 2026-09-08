"""Project Playground input compilation and execution."""

import json
import re
from copy import deepcopy

from app.core.validation import positive_version, read_json, validate_name
from app.projects.llms import LLMService
from app.projects.prompts import PromptService

ADAPTERS = {"openai", "azure", "anthropic", "bedrock", "google-vertex-ai", "google-ai-studio"}
VARIABLE = re.compile(r"{{\s*([^{}]+?)\s*}}")
PARAMS = {
    "provider",
    "model",
    "temperature",
    "max_tokens",
    "top_p",
    "maxReasoningTokens",
    "providerOptions",
}


def compile_messages(messages, variables, placeholders):
    if not isinstance(messages, list):
        raise ValueError("messages must be an array")
    expanded = []
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("Each message must be an object")
        if message.get("type") == "placeholder":
            name = message.get("name")
            if not isinstance(name, str) or name not in placeholders:
                raise ValueError("Missing message placeholder value")
            values = placeholders[name]
            if not isinstance(values, list):
                raise ValueError("Message placeholder values must be arrays")
            expanded.extend(deepcopy(values))
        else:
            expanded.append(deepcopy(message))
    if not expanded:
        raise ValueError("At least one message is required after expanding placeholders")
    for message in expanded:
        if not isinstance(message, dict) or message.get("type") == "placeholder":
            raise ValueError("Placeholder values must be messages, not nested placeholders")
        role, content = message.get("role"), message.get("content")
        if role not in {"system", "developer", "user", "assistant", "model", "tool"}:
            raise ValueError("Unsupported message role")
        if not isinstance(content, str):
            raise ValueError("This command currently supports text message content only")

        def substitute(match):
            name = match.group(1).strip()
            if name not in variables:
                raise ValueError(f"Missing prompt variable: {name}")
            return variables[name]

        message["content"] = VARIABLE.sub(substitute, content)
        if role == "tool":
            call_id = message.pop("tool_call_id", None) or message.get("toolCallId")
            if not isinstance(call_id, str) or not call_id:
                raise ValueError("Tool result requires tool_call_id or toolCallId")
            message.update(type="tool-result", toolCallId=call_id)
        elif message.get("toolCalls") is not None:
            calls = message["toolCalls"]
            if (
                role != "assistant"
                or not isinstance(calls, list)
                or any(
                    not isinstance(call, dict)
                    or not isinstance(call.get("id"), str)
                    or not isinstance(call.get("name"), str)
                    or not isinstance(call.get("args"), dict)
                    for call in calls
                )
            ):
                raise ValueError("toolCalls require assistant messages and id, name, args fields")
            message["type"] = "assistant-tool-call"
        else:
            if set(message) - {"role", "content", "type"}:
                raise ValueError("Unsupported message fields; use toolCalls for tool requests")
            message["type"] = {"assistant": "assistant-text", "model": "model-text"}.get(role, role)
    return expanded


def load_input(path):
    data = read_json(path)
    if not isinstance(data, dict):
        raise ValueError("Playground input must be a JSON object")
    allowed = {
        "messages",
        "prompt",
        "variables",
        "placeholders",
        "modelParams",
        "tools",
        "structuredOutputSchema",
    }
    if set(data) - allowed:
        raise ValueError("Unknown Playground fields; project and credentials belong in .env")
    json.dumps(data, allow_nan=False)
    if ("messages" in data) == ("prompt" in data):
        raise ValueError("Provide either messages or a saved prompt selector")
    params = data.get("modelParams")
    if not isinstance(params, dict) or set(params) - PARAMS:
        raise ValueError(
            "modelParams requires provider and model; adapter is inferred from the connection"
        )
    for key in ("provider", "model"):
        if not isinstance(params.get(key), str) or not params[key].strip():
            raise ValueError(f"modelParams requires {key}")
    for key in ("temperature", "max_tokens", "top_p", "maxReasoningTokens"):
        if key in params and (
            isinstance(params[key], bool) or not isinstance(params[key], (int, float))
        ):
            raise ValueError(f"modelParams.{key} must be a number")
    if "providerOptions" in params and not isinstance(params["providerOptions"], dict):
        raise ValueError("providerOptions must be an object")
    variables, placeholders = data.get("variables", {}), data.get("placeholders", {})
    if not isinstance(variables, dict) or any(
        not isinstance(value, str) for value in variables.values()
    ):
        raise ValueError("variables must map names to strings; serialize objects as JSON strings")
    if not isinstance(placeholders, dict):
        raise ValueError("placeholders must be an object")
    for values in placeholders.values():
        if not isinstance(values, list):
            raise ValueError("Message placeholder values must be arrays")
        if values:
            compile_messages(values, variables, {})
    if "messages" in data:
        compile_messages(data["messages"], variables, placeholders)
    else:
        selector = data["prompt"]
        if not isinstance(selector, dict) or set(selector) - {"name", "version", "label"}:
            raise ValueError("prompt selector supports name and either version or label")
        validate_name(selector.get("name"))
        if "version" in selector and "label" in selector:
            raise ValueError("Choose prompt version or label, not both")
        if "version" in selector:
            positive_version(selector["version"])
        if "label" in selector and (
            not isinstance(selector["label"], str) or not selector["label"].strip()
        ):
            raise ValueError("Prompt label must be nonempty")
    if "structuredOutputSchema" in data and not isinstance(data["structuredOutputSchema"], dict):
        raise ValueError("structuredOutputSchema must be a JSON Schema object")
    if "tools" in data:
        if not isinstance(data["tools"], list) or any(
            not isinstance(tool, dict)
            or set(tool) != {"name", "description", "parameters"}
            or not isinstance(tool["name"], str)
            or not tool["name"]
            or not isinstance(tool["description"], str)
            or not isinstance(tool["parameters"], dict)
            for tool in data["tools"]
        ):
            raise ValueError("tools require name, description and parameters")
        if data["tools"] and "structuredOutputSchema" in data:
            raise ValueError(
                "Choose tools or structuredOutputSchema; Playground does not execute both together"
            )
    return data


def prepare(data, client):
    client.check()
    connections = LLMService(client).list(all_pages=True)["data"]
    selected = [
        connection
        for connection in connections
        if connection["provider"] == data["modelParams"]["provider"]
    ]
    if len(selected) != 1:
        raise ValueError(
            "No unique LLM connection for provider; run 'project llms list --all' first"
        )
    adapter = selected[0]["adapter"]
    if adapter not in ADAPTERS:
        raise ValueError("This LLM adapter is not supported by the Playground endpoint")
    prompt_info = None
    if "prompt" in data:
        selector = data["prompt"]
        prompt = PromptService(client).get_prompt(
            selector["name"],
            version=selector.get("version"),
            label=selector.get("label"),
            resolve=True,
        )
        prompt_info = {key: prompt[key] for key in ("name", "version", "type")}
        if prompt["type"] == "text":
            messages = [{"role": "user", "content": prompt["prompt"]}]
        elif prompt["type"] == "chat":
            messages = prompt["prompt"]
        else:
            raise ValueError("Unsupported saved prompt type")
    else:
        messages = data["messages"]
    body = {
        "projectId": client.project_id,
        "messages": compile_messages(
            messages, data.get("variables", {}), data.get("placeholders", {})
        ),
        "modelParams": {**data["modelParams"], "adapter": adapter},
        "streaming": False,
    }
    for field in ("tools", "structuredOutputSchema"):
        if field in data:
            body[field] = data[field]
    return body, prompt_info


class PlaygroundService:
    def __init__(self, client, session=None):
        self.client = client
        self.session = session

    def run(self, data, *, dry_run=False):
        if not dry_run:
            if self.session is None:
                raise ValueError("Playground execution requires a session client")
            self.session.require()
        body, prompt = prepare(data, self.client)
        if dry_run:
            return {"dryRun": True, "path": "/api/chatCompletion", "body": body, "prompt": prompt}
        result = self.session.complete(self.client.project_id, body)
        return {
            "completed": True,
            "projectId": self.client.project_id,
            "provider": body["modelParams"]["provider"],
            "model": body["modelParams"]["model"],
            "prompt": prompt,
            "output": result,
        }
