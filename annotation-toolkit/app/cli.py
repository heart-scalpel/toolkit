"""Command-line interface for annotation platform imports."""

from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import argilla as rg
from dotenv import load_dotenv

from app.platforms import argilla
from app.profiles import get_profile, profile_names
from app.sampling import balanced_random_sample, ordered_sample

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV = PROJECT_ROOT / ".env"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "workbench" / "output"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import a review task into an annotation platform."
    )
    parser.add_argument(
        "--platform",
        choices=["argilla"],
        help="Defaults to ANNOTATION_PLATFORM or argilla",
    )
    parser.add_argument(
        "--profile",
        choices=profile_names(),
        help="Business profile; required when importing a CSV",
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="CSV input; defaults to the file declared by the selected profile",
    )
    parser.add_argument("--mode", default="review", help="Profile-defined annotation mode")
    parser.add_argument(
        "--dataset",
        help="Destination name; required for cloning, otherwise defaults to the profile name",
    )
    parser.add_argument("--guidelines", type=Path, help="Use batch-specific Markdown guidelines")
    parser.add_argument(
        "--limit",
        type=int,
        help=(
            "Import at most N CSV records after --offset "
            "(preserves CSV order unless --random is used)"
        ),
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Skip the first N CSV records before applying --limit (default: 0)",
    )
    parser.add_argument(
        "--random",
        action="store_true",
        help=(
            "Use balanced random sampling after --offset with the fields declared "
            "by the selected profile; requires --limit"
        ),
    )
    parser.add_argument("--workspace", help="Defaults to ARGILLA_WORKSPACE or default")
    parser.add_argument("--api-url", help="Defaults to ARGILLA_API_URL or http://localhost:6900")
    parser.add_argument("--api-key", help="Defaults to ARGILLA_API_KEY; prefer using an env file")
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--min-submitted", type=int, default=2)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate without writing; CSV imports are offline, cloning reads the platform",
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--clone-dataset",
        metavar="EXACT_NAME",
        help="Copy every record and the saved form to --dataset, without responses or suggestions",
    )
    actions.add_argument(
        "--delete-dataset",
        metavar="EXACT_NAME",
        help="Delete one dataset by its full exact name instead of importing records",
    )
    actions.add_argument(
        "--create-users",
        type=int,
        metavar="COUNT",
        help="Create COUNT annotator accounts and add them to the workspace",
    )
    actions.add_argument(
        "--progress-dataset",
        metavar="EXACT_NAME",
        help="Show compact per-user progress for one exact-name dataset",
    )
    actions.add_argument(
        "--export-dataset",
        metavar="EXACT_NAME",
        help="Export submitted responses from one exact-name dataset to CSV",
    )
    actions.add_argument(
        "--remove-user",
        metavar="EXACT_USERNAME",
        help="Remove one exact annotator from the workspace without deleting the account",
    )
    actions.add_argument(
        "--delete-user",
        metavar="EXACT_USERNAME",
        help="Permanently delete one exact annotator account",
    )
    actions.add_argument(
        "--delete-users",
        type=int,
        metavar="COUNT",
        help="Permanently delete a numbered annotator batch built from --user-prefix",
    )
    parser.add_argument(
        "--user-prefix",
        help="Username prefix for account operations; defaults to the selected profile",
    )
    parser.add_argument(
        "--credentials-out",
        type=Path,
        help="Credential CSV path; defaults to a timestamped ignored output file",
    )
    parser.add_argument(
        "--export-out",
        type=Path,
        help="Export CSV path; defaults to a timestamped ignored output file",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip typed confirmation for destructive delete actions",
    )
    return parser


def _write_credentials(path: Path, rows: list[dict[str, str]]) -> None:
    if path.exists():
        raise ValueError(f"refusing to overwrite credential file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "username",
        "initial_password",
        "role",
        "workspace",
        "login_url",
        "creation_status",
        "assigned_to",
        "distributed_at",
        "notes",
    ]
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        os.chmod(path, 0o600)
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _default_credentials_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return DEFAULT_OUTPUT_DIR / f"argilla_annotator_accounts_{stamp}.csv"


def _default_export_path(dataset_name: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return DEFAULT_OUTPUT_DIR / f"{dataset_name}_submitted_{stamp}.csv"


def _write_export(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    if path.exists():
        raise ValueError(f"refusing to overwrite export file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> int:
    if args.platform != "argilla":
        raise ValueError(f"unsupported platform: {args.platform}")
    if args.clone_dataset:
        if not args.dataset or not args.dataset.strip():
            raise ValueError("--clone-dataset requires --dataset with a new destination name")
        if args.dataset == args.clone_dataset:
            raise ValueError("clone source and destination must have different names")
        if (
            args.profile
            or args.input is not None
            or args.guidelines is not None
            or args.limit is not None
            or args.offset != 0
            or args.random
            or args.mode != "review"
        ):
            raise ValueError(
                "--clone-dataset copies all saved records and settings; "
                "do not combine it with --profile, --input, --guidelines, --limit, "
                "--offset, --random, or a different --mode"
            )
    profile = get_profile(args.profile) if args.profile else None
    user_prefix = args.user_prefix or (
        profile.default_user_prefix if profile is not None else "annotator"
    )
    if profile is not None and args.mode not in profile.modes:
        choices = ", ".join(profile.modes)
        raise ValueError(
            f"unsupported mode for profile {profile.name!r}: {args.mode}; "
            f"available modes: {choices}"
        )
    if args.min_submitted < 1:
        raise ValueError("--min-submitted must be at least 1")
    if args.limit is not None and args.limit < 1:
        raise ValueError("--limit must be at least 1")
    if args.offset < 0:
        raise ValueError("--offset must be at least 0")
    if args.random and args.limit is None:
        raise ValueError("--random requires --limit")

    api_url = args.api_url or os.getenv("ARGILLA_API_URL", "http://localhost:6900")
    api_key = args.api_key or os.getenv("ARGILLA_API_KEY")

    if args.clone_dataset:
        if not api_key:
            raise ValueError(
                "ARGILLA_API_KEY is missing. Copy it from Argilla > My Settings into .env."
            )
        client = rg.Argilla(api_url=api_url, api_key=api_key)
        requested_workspace = args.workspace or os.getenv("ARGILLA_WORKSPACE", "default")
        workspace = argilla.resolve_workspace(client, requested_workspace)
        summary = argilla.clone_dataset(
            client=client,
            workspace=workspace,
            source_name=args.clone_dataset,
            dataset_name=args.dataset,
            min_submitted=args.min_submitted,
            dry_run=args.dry_run,
        )
        print(json.dumps(summary | {"url": api_url}, ensure_ascii=False, indent=2))
        return 0

    if args.export_dataset:
        if args.dry_run:
            raise ValueError("--dry-run cannot be combined with --export-dataset")
        if not api_key:
            raise ValueError(
                "ARGILLA_API_KEY is missing. Copy it from Argilla > My Settings into .env."
            )
        client = rg.Argilla(api_url=api_url, api_key=api_key)
        requested_workspace = args.workspace or os.getenv("ARGILLA_WORKSPACE", "default")
        workspace = argilla.resolve_workspace(client, requested_workspace)
        columns, rows = argilla.submitted_response_rows(
            client,
            workspace,
            args.export_dataset,
        )
        output_path = args.export_out or _default_export_path(args.export_dataset)
        _write_export(output_path, columns, rows)
        print(
            json.dumps(
                {
                    "exported_dataset": args.export_dataset,
                    "workspace": workspace,
                    "submitted_rows": len(rows),
                    "columns": columns,
                    "output_file": str(output_path),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    user_management_requested = any(
        [
            args.create_users is not None,
            args.progress_dataset,
            args.remove_user,
            args.delete_user,
            args.delete_users is not None,
        ]
    )
    if user_management_requested:
        if args.dry_run:
            raise ValueError(
                "--dry-run cannot be combined with account creation or progress lookup"
            )
        if not api_key:
            raise ValueError(
                "ARGILLA_API_KEY is missing. Copy it from Argilla > My Settings into .env."
            )
        client = rg.Argilla(api_url=api_url, api_key=api_key)
        requested_workspace = args.workspace or os.getenv("ARGILLA_WORKSPACE", "default")
        workspace = argilla.resolve_workspace(client, requested_workspace)

        if args.progress_dataset:
            progress = argilla.dataset_user_progress(
                client,
                workspace,
                args.progress_dataset,
            )
            print(json.dumps(progress, ensure_ascii=False, indent=2))
            return 0

        if args.remove_user:
            argilla.remove_annotator_from_workspace(
                client,
                workspace,
                args.remove_user,
            )
            print(
                json.dumps(
                    {
                        "removed_from_workspace": args.remove_user,
                        "workspace": workspace,
                        "account_deleted": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        if args.delete_user or args.delete_users is not None:
            usernames = (
                [args.delete_user]
                if args.delete_user
                else argilla.batch_usernames(user_prefix, args.delete_users)
            )
            users = argilla.resolve_deletable_annotators(client, usernames)
            if not args.yes:
                print("Annotator accounts selected for permanent deletion:")
                for username in usernames:
                    print(f"- {username}")
                confirmation = input(f"Type DELETE {len(usernames)} USERS to confirm: ").strip()
                if confirmation != f"DELETE {len(usernames)} USERS":
                    print("Deletion cancelled: confirmation did not match.")
                    return 1
            argilla.delete_annotators(users)
            print(
                json.dumps(
                    {
                        "deleted_users": usernames,
                        "count": len(usernames),
                        "workspace": workspace,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        usernames = argilla.batch_usernames(user_prefix, args.create_users)
        argilla.ensure_users_do_not_exist(client, usernames)
        credentials_path = args.credentials_out or _default_credentials_path()
        credentials = [
            {
                "username": username,
                "initial_password": argilla.generate_password(),
                "role": "annotator",
                "workspace": workspace,
                "login_url": api_url,
                "creation_status": "planned",
                "assigned_to": "",
                "distributed_at": "",
                "notes": "",
            }
            for username in usernames
        ]
        _write_credentials(credentials_path, credentials)

        created = 0
        try:
            for credential in credentials:
                argilla.create_annotator(
                    client,
                    workspace,
                    credential["username"],
                    credential["initial_password"],
                )
                credential["creation_status"] = "created"
                created += 1
        finally:
            credentials_path.unlink(missing_ok=True)
            _write_credentials(credentials_path, credentials)

        print(
            json.dumps(
                {
                    "created_users": created,
                    "role": "annotator",
                    "workspace": workspace,
                    "credentials_file": str(credentials_path),
                    "file_mode": "0600",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.delete_dataset:
        if args.dry_run:
            raise ValueError("--dry-run cannot be combined with --delete-dataset")
        if not api_key:
            raise ValueError(
                "ARGILLA_API_KEY is missing. Copy it from Argilla > My Settings into .env."
            )

        client = rg.Argilla(api_url=api_url, api_key=api_key)
        requested_workspace = args.workspace or os.getenv("ARGILLA_WORKSPACE", "default")
        workspace = argilla.resolve_workspace(client, requested_workspace)
        target = argilla.get_dataset(client, workspace, args.delete_dataset)

        if not args.yes:
            print(f"Dataset selected for deletion: {target.name!r} in workspace {workspace!r}")
            confirmation = input("Type the full dataset name to confirm deletion: ").strip()
            if confirmation != target.name:
                print("Deletion cancelled: confirmation did not match the dataset name.")
                return 1

        argilla.delete_dataset(client, workspace, target.name)
        print(
            json.dumps(
                {
                    "deleted": target.name,
                    "platform": args.platform,
                    "workspace": workspace,
                    "url": api_url,
                },
                ensure_ascii=False,
            )
        )
        return 0

    if profile is None:
        raise ValueError(
            "--profile is required when importing a CSV; "
            f"available profiles: {', '.join(profile_names())}"
        )

    input_path = args.input or PROJECT_ROOT / "workbench" / "input" / profile.default_input_name
    profile_input = profile.load_input(input_path)
    rows = profile_input.rows
    source_records = len(rows)
    if args.offset >= source_records:
        raise ValueError(
            f"--offset {args.offset} is outside the input containing {source_records} CSV records"
        )
    rows = rows[args.offset :]
    if args.random:
        sampling = balanced_random_sample(
            rows,
            args.limit,
            profile.sampling_fields,
        )
    else:
        sampling = ordered_sample(rows, args.limit)
    rows = sampling.rows
    dataset_name = args.dataset or profile.default_dataset_name(args.mode)

    task_spec = profile.task_spec(args.mode)
    if args.guidelines:
        guidelines = args.guidelines.read_text(encoding="utf-8")
        if not guidelines.strip():
            raise ValueError(f"{args.guidelines}: guidelines cannot be empty")
        task_spec = replace(task_spec, guidelines=guidelines)

    if args.dry_run:
        client = argilla.offline_client()
    else:
        if not api_key:
            raise ValueError(
                "ARGILLA_API_KEY is missing. Copy it from Argilla > My Settings into .env."
            )
        client = rg.Argilla(api_url=api_url, api_key=api_key)

    record_specs = [profile.record_spec(row, args.mode) for row in rows]
    settings = argilla.build_settings(task_spec, args.min_submitted, client)
    records = argilla.build_records(record_specs)
    summary = {
        "platform": args.platform,
        "profile": args.profile,
        "input_format": profile_input.source_format,
        "mode": args.mode,
        "dataset": dataset_name,
        "source_records": source_records,
        "offset": args.offset,
        "sampling": "balanced_random" if args.random else "ordered",
        "sampling_fields": list(profile.sampling_fields) if args.random else [],
        "excluded_empty_sampling_fields": sampling.excluded_missing_fields,
        "records": len(records),
        "questions": [question.name for question in settings.questions],
        "min_submitted": args.min_submitted,
    }

    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    requested_workspace = args.workspace or os.getenv("ARGILLA_WORKSPACE", "default")
    workspace = argilla.resolve_workspace(client, requested_workspace)
    print(f"Connected as: {client.me.username}")
    argilla.create_dataset(
        client=client,
        workspace=workspace,
        dataset_name=dataset_name,
        settings=settings,
        records=records,
    )
    print(json.dumps(summary | {"url": api_url, "workspace": workspace}, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv(args.env)
    args.platform = args.platform or os.getenv("ANNOTATION_PLATFORM", "argilla")
    try:
        return run(args)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}")
        return 2
