"""Project resource mutation validation."""

import json
import math

from app.core.validation import validate_name

WRITE_FIELDS = {
    "datasets": {"name", "description", "metadata", "inputSchema", "expectedOutputSchema"},
    "items": {
        "id",
        "datasetName",
        "input",
        "expectedOutput",
        "metadata",
        "sourceTraceId",
        "sourceObservationId",
        "status",
    },
    "scores": {
        "id",
        "name",
        "value",
        "traceId",
        "observationId",
        "sessionId",
        "datasetRunId",
        "comment",
        "metadata",
        "environment",
        "dataType",
        "configId",
        "source",
        "queueId",
    },
    "score-configs": {"name", "dataType", "categories", "minValue", "maxValue", "description"},
    "run-items": {
        "runName",
        "runDescription",
        "metadata",
        "datasetItemId",
        "traceId",
        "observationId",
        "datasetVersion",
        "createdAt",
    },
}


def validate_body(resource: str, action: str, body) -> dict:
    if not isinstance(body, dict) or not body:
        raise ValueError("Request body must be a nonempty JSON object")
    json.dumps(body, allow_nan=False)
    allowed = WRITE_FIELDS[resource]
    if resource == "score-configs" and action == "update":
        allowed = (allowed - {"dataType"}) | {"isArchived"}
    if unknown := set(body) - allowed:
        raise ValueError(f"Unknown {resource} fields: {', '.join(sorted(unknown))}")
    required = {
        "datasets": ["name"],
        "items": ["datasetName"],
        "scores": ["name", "value"],
        "score-configs": ["name", "dataType"],
        "run-items": ["runName", "datasetItemId"],
    }[resource]
    if action == "update":
        required = []
    for field in required:
        if field not in body or (
            field != "value" and (not isinstance(body[field], str) or not body[field].strip())
        ):
            raise ValueError(f"{resource} requires {field}")
    if resource == "items" and body.get("status", "ACTIVE") not in ("ACTIVE", "ARCHIVED"):
        raise ValueError("Dataset item status must be ACTIVE or ARCHIVED")
    if resource == "items" and "id" in body:
        validate_name(body["id"])
        if len(body["id"]) > 255:
            raise ValueError("Dataset item id must be at most 255 characters")
    if resource == "scores":
        if not any(body.get(field) for field in ("traceId", "sessionId", "datasetRunId")):
            raise ValueError("Score requires traceId, sessionId or datasetRunId")
        if sum(bool(body.get(field)) for field in ("traceId", "sessionId", "datasetRunId")) > 1:
            raise ValueError("Choose one score target: traceId, sessionId or datasetRunId")
        if body.get("observationId") and not body.get("traceId"):
            raise ValueError("observationId requires traceId")
        datatype = body.get("dataType", None if body.get("configId") else "NUMERIC")
        value = body["value"]
        if datatype in ("NUMERIC", "BOOLEAN"):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError("Numeric and boolean score values must be finite numbers")
            if datatype == "BOOLEAN" and value not in (0, 1):
                raise ValueError("BOOLEAN score value must be 0 or 1")
        elif datatype in ("CATEGORICAL", "TEXT", "CORRECTION"):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{datatype} score value must be a nonempty string")
            if datatype == "TEXT" and len(value) > 500:
                raise ValueError("TEXT score values must be at most 500 characters")
        elif datatype is not None:
            raise ValueError("Unsupported score dataType")
        if body.get("source", "API") not in ("API", "ANNOTATION"):
            raise ValueError("Score source must be API or ANNOTATION")
        if (
            body.get("source") == "ANNOTATION"
            and not body.get("configId")
            and datatype != "CORRECTION"
        ):
            raise ValueError("ANNOTATION scores require configId")
    if resource == "run-items" and not (body.get("traceId") or body.get("observationId")):
        raise ValueError("Run item requires traceId or observationId")
    return body
