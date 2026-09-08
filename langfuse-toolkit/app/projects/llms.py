"""LLM discovery reusable by both CLI operations and Playground."""

from app.projects.queries import ResourceRequest
from app.projects.resources import execute


class LLMService:
    def __init__(self, client):
        self.client = client

    def list(self, *, limit=100, all_pages=False, max_pages=100):
        return execute(
            ResourceRequest("llms", "list", limit=limit, all_pages=all_pages, max_pages=max_pages),
            self.client,
        )
