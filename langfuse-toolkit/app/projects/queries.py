"""Build project API requests from domain options."""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from app.core.validation import validate_name
from app.projects.catalog import RESOURCES
from app.projects.validation import validate_body


@dataclass(frozen=True)
class ResourceRequest:
    resource: str
    action: str
    identifier: str | None = None
    dataset: str | None = None
    filters: dict = field(default_factory=dict)
    body: dict | None = None
    limit: int = 50
    all_pages: bool = False
    max_pages: int = 100
    legacy: bool = False
    dry_run: bool = False


def timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamps must include a timezone, for example 2026-09-07T00:00:00Z")
    return parsed


@dataclass
class RequestPlan:
    method: str
    path: str
    params: dict
    body: dict | None = None
    cursor: bool = False
    collection: bool = False
    view: str | None = None


def bounded_window(params):
    now = datetime.now(UTC)
    params.setdefault("fromStartTime", (now - timedelta(days=1)).isoformat())
    params.setdefault("toStartTime", now.isoformat())
    if timestamp(params["fromStartTime"]) >= timestamp(params["toStartTime"]):
        raise ValueError("--from must be earlier than --to")


def modern_view(options: ResourceRequest, request, result, *, complete):
    if request.view is None:
        return result
    rows = result["data"]
    if request.view == "scores":
        if len(rows) != 1 or rows[0].get("id") != options.identifier:
            raise RuntimeError("No unique score was found for this ID")
        return rows[0]
    window = {key: request.params[key] for key in ("fromStartTime", "toStartTime")}
    if options.action == "get":
        return {
            "id": options.identifier,
            "foundInWindow": bool(rows),
            "observations": rows,
            "complete": complete,
            "window": window,
        }
    if request.view == "traces":
        grouped = {}
        for row in rows:
            if row.get("traceId"):
                grouped.setdefault(row["traceId"], {"id": row["traceId"], "roots": []})[
                    "roots"
                ].append(row)
    else:
        grouped = {}
        for row in rows:
            if row.get("sessionId"):
                item = grouped.setdefault(
                    row["sessionId"],
                    {"id": row["sessionId"], "observationCount": 0, "traceIds": []},
                )
                item["observationCount"] += 1
                if row["traceId"] not in item["traceIds"]:
                    item["traceIds"].append(row["traceId"])
    return {
        "data": list(grouped.values()),
        "complete": complete,
        "window": window,
        "meta": result.get("meta", {}),
        "observationCount": len(rows),
    }


def plan(options: ResourceRequest) -> RequestPlan:
    spec = RESOURCES[options.resource]
    modern = (
        options.resource in ("traces", "sessions", "observations", "scores")
        and options.action in ("list", "get")
        and not options.legacy
    )
    path = spec.path
    if options.resource == "runs":
        path = path.format(dataset=quote(validate_name(options.dataset), safe=""))
    if options.action in ("get", "update", "delete"):
        if options.resource == "observations":
            path = "/observations"
        if options.resource == "scores" and options.action == "delete":
            path = "/scores"
        if options.resource == "scores" and options.action == "get":
            path = "/v2/scores"
        path += "/" + quote(validate_name(options.identifier), safe="")
    if options.resource == "scores" and options.action == "create":
        path = "/scores"
    params, body, cursor = {}, None, spec.cursor
    if options.action == "list":
        if not 1 <= options.limit <= 100 or options.max_pages < 1:
            raise ValueError("limit must be 1-100 and max-pages must be positive")
        params = {
            field: options.filters.get(field)
            for field in spec.filters
            if options.filters.get(field) is not None
        }
        params["limit"] = options.limit
        if options.resource == "observations" and options.legacy:
            path, cursor = "/observations", False
        if options.resource == "scores":
            if modern:
                path, cursor = "/v3/scores", True
                if options.filters.get("id"):
                    params["id"] = options.filters["id"]
            else:
                path, cursor = "/v2/scores", False
                if options.filters.get("id"):
                    raise ValueError("scores list --id is not supported with --legacy")
        if spec.time_window:
            bounded_window(params)
        for lower, upper in (("fromStartTime", "toStartTime"), ("fromTimestamp", "toTimestamp")):
            for field in (lower, upper):
                if field in params:
                    timestamp(params[field])
            if (
                lower in params
                and upper in params
                and timestamp(params[lower]) >= timestamp(params[upper])
            ):
                raise ValueError("--from must be earlier than --to")
        if (
            options.resource == "items"
            and options.filters.get("version")
            and not options.filters.get("datasetName")
        ):
            raise ValueError("items list --version requires --dataset")
        if options.resource == "run-items" and not (
            options.filters.get("datasetId") and options.filters.get("runName")
        ):
            raise ValueError("run-items list requires --dataset-id and --run-name")
        if "filter" in params and not isinstance(json.loads(params["filter"]), list):
            raise ValueError("filter must be a JSON array")
        if "filter" in params and any(
            key in params
            for key in ("name", "traceId", "userId", "sessionId", "type", "level", "environment")
        ):
            raise ValueError(
                "Put all observation conditions in --filter instead of combining it with direct filters"
            )
    view = None
    collection = options.action == "list"
    if modern and options.resource in ("traces", "sessions", "observations"):
        path, cursor = "/v2/observations", True
        if options.resource in ("traces", "sessions"):
            view = options.resource
        if options.action == "get":
            collection = True
            view = options.resource
            params = {
                key: options.filters.get(key)
                for key in ("fromStartTime", "toStartTime", "fields")
                if options.filters.get(key) is not None
            }
            params["limit"] = 100
            if options.max_pages < 1:
                raise ValueError("max-pages must be positive")
            if options.resource == "observations":
                if not options.filters.get("traceId"):
                    raise ValueError("observations get requires --trace-id on Langfuse v4")
                params["filter"] = json.dumps(
                    [
                        {
                            "type": "string",
                            "column": "id",
                            "operator": "=",
                            "value": options.identifier,
                        },
                        {
                            "type": "string",
                            "column": "traceId",
                            "operator": "=",
                            "value": options.filters.get("traceId"),
                        },
                    ]
                )
            else:
                params["traceId" if options.resource == "traces" else "sessionId"] = (
                    options.identifier
                )
        else:
            if "fromTimestamp" in params:
                params["fromStartTime"] = params.pop("fromTimestamp")
            if "toTimestamp" in params:
                params["toStartTime"] = params.pop("toTimestamp")
            if options.resource == "traces":
                params["isRootObservation"] = "true"
                if "tags" in params:
                    params["filter"] = json.dumps(
                        [
                            {
                                "type": "arrayOptions",
                                "column": "tags",
                                "operator": "all of",
                                "value": [params.pop("tags")],
                            },
                            {
                                "type": "boolean",
                                "column": "isRootObservation",
                                "operator": "=",
                                "value": True,
                            },
                        ]
                    )
        bounded_window(params)
        if "filter" in params:
            conditions = json.loads(params["filter"])
            for key in ("name", "userId", "sessionId", "environment"):
                if key in params:
                    conditions.append(
                        {"type": "string", "column": key, "operator": "=", "value": params[key]}
                    )
            conditions.extend(
                [
                    {
                        "type": "datetime",
                        "column": "startTime",
                        "operator": ">=",
                        "value": params["fromStartTime"],
                    },
                    {
                        "type": "datetime",
                        "column": "startTime",
                        "operator": "<",
                        "value": params["toStartTime"],
                    },
                ]
            )
            params["filter"] = json.dumps(conditions)
    if modern and options.resource == "scores" and options.action == "get":
        path, cursor, collection, view = "/v3/scores", True, True, "scores"
        params = {"id": options.identifier, "limit": 100}
    if options.action in ("create", "upsert", "update"):
        body = validate_body(options.resource, options.action, options.body)
    method = {
        "list": "GET",
        "get": "GET",
        "create": "POST",
        "upsert": "POST",
        "update": "PATCH",
        "delete": "DELETE",
    }[options.action]
    return RequestPlan(method, "/api/public" + path, params, body, cursor, collection, view)
