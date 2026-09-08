"""Execute project resource requests and verify their results."""

from urllib.parse import quote, urlsplit, urlunsplit

from app.projects.catalog import RESOURCES
from app.projects.queries import ResourceRequest, modern_view, plan


def connection_summary(connection):
    """Return model discovery fields; never forward connection credentials."""
    if not isinstance(connection, dict) or any(
        not isinstance(connection.get(key), str) or not connection[key]
        for key in ("id", "provider", "adapter")
    ):
        raise RuntimeError("Server returned an invalid LLM connection")
    fields = ("id", "provider", "adapter", "customModels", "withDefaultModels")
    result = {key: connection.get(key) for key in fields}
    if connection.get("baseURL"):
        url = urlsplit(connection["baseURL"])
        result["baseURL"] = urlunsplit(
            (url.scheme, url.netloc.rsplit("@", 1)[-1], url.path, "", "")
        )
    else:
        result["baseURL"] = None
    return result


def execute(options: ResourceRequest, client) -> dict:
    request = plan(options)
    if options.dry_run:
        return {
            "dryRun": True,
            "method": request.method,
            "path": request.path,
            "query": request.params,
            "body": request.body,
        }
    client.check()
    if not request.collection:
        result = client.request(
            request.method, request.path, params=request.params, body=request.body
        )
        if request.method == "GET":
            return result
        if request.method == "POST" and (not isinstance(result, dict) or not result.get("id")):
            raise RuntimeError(
                "Write did not return a resource ID; inspect the server before retrying"
            )
        if request.body and request.body.get("id") and result.get("id") != request.body["id"]:
            raise RuntimeError("Write returned a different ID; inspect the server before retrying")
        if request.method in ("POST", "PATCH") and options.resource in (
            "datasets",
            "items",
            "score-configs",
        ):
            identifier = (
                request.body["name"]
                if options.resource == "datasets"
                else (options.identifier if request.method == "PATCH" else result["id"])
            )
            saved = client.request(
                "GET",
                "/api/public" + RESOURCES[options.resource].path + "/" + quote(identifier, safe=""),
            )
            if any(saved.get(field) != value for field, value in request.body.items()):
                raise RuntimeError("Write succeeded but read-back differs; inspect before retrying")
            return {
                "accepted": True,
                "verified": True,
                "resource": options.resource,
                "action": options.action,
                "response": saved,
            }
        # Return the server acknowledgement. Scores/deletes can be asynchronously applied.
        return {
            "accepted": True,
            "resource": options.resource,
            "action": options.action,
            "response": result,
        }
    collected, page, cursors, seen = [], 1, set(), set()
    all_pages = options.action == "get" or options.all_pages
    while True:
        query = dict(request.params)
        if not request.cursor:
            query["page"] = page
        result = client.request("GET", request.path, params=query)
        if not isinstance(result, dict) or not isinstance(result.get("data"), list):
            raise RuntimeError("Server returned an invalid paginated response")
        if options.resource == "llms":
            result = {
                "data": [connection_summary(row) for row in result["data"]],
                "meta": result.get("meta", {}),
            }
        if all_pages:
            for item in result["data"]:
                if "id" in item:
                    identity = (item.get("traceId"), item["id"])
                    if identity in seen:
                        raise RuntimeError("Pagination repeated a resource; incomplete result")
                    seen.add(identity)
        collected.extend(result["data"])
        if not all_pages:
            return modern_view(
                options, request, result, complete=not bool(result.get("meta", {}).get("cursor"))
            )
        meta = result.get("meta", {})
        if request.cursor:
            next_cursor = meta.get("cursor")
            more = bool(next_cursor)
            if more:
                if next_cursor in cursors:
                    raise RuntimeError("Server repeated a pagination cursor; incomplete result")
                cursors.add(next_cursor)
                request.params["cursor"] = next_cursor
        else:
            total_pages = meta.get("totalPages")
            more = (
                page < total_pages
                if total_pages is not None
                else len(result["data"]) == options.limit
            )
            if more and not result["data"]:
                raise RuntimeError("Server returned an empty intermediate page; incomplete result")
        if not more:
            if (
                not request.cursor
                and meta.get("totalItems") is not None
                and len(collected) != meta["totalItems"]
            ):
                raise RuntimeError("Resource count changed during pagination; incomplete result")
            return modern_view(
                options,
                request,
                {"data": collected, "count": len(collected), "pages": page, "complete": True},
                complete=True,
            )
        if page >= options.max_pages:
            raise RuntimeError(
                "Reached --max-pages; result is incomplete. Narrow filters or raise the limit"
            )
        page += 1
