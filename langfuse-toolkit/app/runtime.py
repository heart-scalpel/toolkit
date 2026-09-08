"""Composition root: construct each authenticated scope only when it is needed."""

from functools import cached_property

from app.core.http import HttpClient
from app.core.session import SessionClient
from app.instance.client import InstanceClient
from app.organizations.client import OrganizationClient
from app.projects.client import ProjectClient
from app.projects.prompts import PromptService


class Runtime:
    def __init__(self, config, *, transport=None):
        self.config = config
        self._transport = transport
        self._clients = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        for client in reversed(self._clients):
            client.close()

    def _http(self, **options):
        http = HttpClient(self.config.base_url, transport=self._transport, **options)
        self._clients.append(http)
        return http

    @cached_property
    def instance(self):
        return InstanceClient(self._http())

    @cached_property
    def organization(self):
        keys = self.config.organization_keys.require("LANGFUSE_ORG")
        return OrganizationClient(self._http(auth=keys))

    @cached_property
    def project(self):
        keys = self.config.project_keys.require("LANGFUSE_PROJECT")
        return ProjectClient(self._http(auth=keys), self.config.project_id)

    @cached_property
    def session(self):
        return SessionClient(self._http(timeout=120), self.config.session_cookie)

    @cached_property
    def prompts(self):
        return PromptService(self.project)
