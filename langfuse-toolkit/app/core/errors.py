class ApiError(RuntimeError):
    def __init__(self, method: str, path: str, status: int):
        self.status = status
        advice = {
            401: "Check the credentials configured for this scope.",
            403: "The API key does not have permission for this action.",
            404: "The resource or endpoint was not found.",
            429: "Rate limited; wait before retrying.",
        }.get(status, "Check the server and request parameters.")
        super().__init__(f"{method} {path}: HTTP {status}. {advice}")
