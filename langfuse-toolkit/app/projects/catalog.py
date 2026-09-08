"""Project resource API contracts; no command-line parsing."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Resource:
    path: str
    actions: tuple[str, ...]
    filters: tuple[str, ...] = ()
    cursor: bool = False
    time_window: bool = False


RESOURCES = {
    "llms": Resource("/llm-connections", ("list",)),
    "datasets": Resource("/v2/datasets", ("list", "get", "create", "upsert")),
    "items": Resource(
        "/dataset-items",
        ("list", "get", "upsert", "delete"),
        ("datasetName", "sourceTraceId", "sourceObservationId", "version"),
    ),
    "traces": Resource(
        "/traces",
        ("list", "get", "delete"),
        (
            "name",
            "userId",
            "sessionId",
            "fromTimestamp",
            "toTimestamp",
            "tags",
            "environment",
            "fields",
        ),
    ),
    "observations": Resource(
        "/v2/observations",
        ("list", "get"),
        (
            "name",
            "traceId",
            "userId",
            "sessionId",
            "type",
            "level",
            "fromStartTime",
            "toStartTime",
            "environment",
            "fields",
            "filter",
        ),
        True,
        True,
    ),
    "sessions": Resource(
        "/sessions", ("list", "get"), ("fromTimestamp", "toTimestamp", "environment")
    ),
    "scores": Resource(
        "/v3/scores",
        ("list", "get", "create", "delete"),
        (
            "name",
            "traceId",
            "observationId",
            "sessionId",
            "configId",
            "dataType",
            "fromTimestamp",
            "toTimestamp",
            "environment",
        ),
    ),
    "score-configs": Resource("/score-configs", ("list", "get", "create", "update")),
    "runs": Resource("/datasets/{dataset}/runs", ("list", "get", "delete")),
    "run-items": Resource("/dataset-run-items", ("list", "create"), ("datasetId", "runName")),
    "experiments": Resource(
        "/experiments",
        ("list",),
        ("id", "name", "datasetId", "fromStartTime", "toStartTime", "fields"),
        True,
        True,
    ),
    "experiment-items": Resource(
        "/experiment-items",
        ("list",),
        ("experimentId", "experimentName", "datasetId", "fromStartTime", "toStartTime", "fields"),
        True,
        True,
    ),
}
