"""Instance operations use only the server address, never project credentials."""


class InstanceClient:
    def __init__(self, http):
        self.http = http

    def health(self):
        return self.http.request("GET", "/api/public/health")
