"""Organization administration, authenticated exclusively with organization keys."""


class OrganizationClient:
    def __init__(self, http):
        self.http = http

    def list_projects(self):
        response = self.http.request("GET", "/api/public/organizations/projects")
        rows = response.get("projects") if isinstance(response, dict) else None
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) or not row.get("id") or not row.get("name") for row in rows
        ):
            raise RuntimeError("Server returned an invalid organization project list")
        return rows
