"""Project discovery and a mandatory project guard for resource requests."""


class ProjectClient:
    def __init__(self, http, project_id):
        self.http = http
        self.project_id = project_id
        self._project = None

    def discover(self):
        response = self.http.request("GET", "/api/public/projects")
        rows = response.get("data") if isinstance(response, dict) else None
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) or not row.get("id") or not row.get("name") for row in rows
        ):
            raise RuntimeError("Server returned an invalid project list")
        return rows

    def check(self):
        if not self.project_id:
            raise ValueError(
                "Run 'project info' first, then set LANGFUSE_PROJECT_ID for project operations"
            )
        if self._project is None:
            projects = self.discover()
            if len(projects) != 1 or projects[0]["id"] != self.project_id:
                actual = ", ".join(str(project["id"]) for project in projects) or "none"
                raise ValueError(
                    f"API key project does not match LANGFUSE_PROJECT_ID; expected {self.project_id}, returned {actual}; stopped"
                )
            self._project = projects[0]
        return self._project

    def request(self, method, path, *, params=None, body=None):
        if path.startswith("/api/public/organizations/") or not path.startswith("/api/public/"):
            raise ValueError("This endpoint does not belong to project data operations")
        self.check()
        return self.http.request(method, path, params=params, body=body)
