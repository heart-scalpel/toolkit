"""Test construction helpers for the CLI-to-application boundary."""

from app.application import dispatch, prepare
from app.command_parser import to_command
from app.core.config import Config, KeyPair
from app.projects.queries import plan
from app.runtime import Runtime


def make_runtime(
    base_url,
    public_key,
    secret_key,
    project_id="",
    *,
    session_cookie="",
    transport=None,
    organization_keys=None,
):
    return Runtime(
        Config(
            base_url=base_url,
            project_id=project_id,
            project_keys=KeyPair(public_key, secret_key),
            organization_keys=organization_keys or KeyPair(),
            session_cookie=session_cookie,
        ),
        transport=transport,
    )


def execute_resource(args, runtime):
    return dispatch(prepare(to_command(args)), runtime)


def request_plan(args):
    return plan(prepare(to_command(args)).payload)
