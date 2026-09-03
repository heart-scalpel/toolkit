"""Command-line interface for annotation platform imports."""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import argilla as rg
from dotenv import load_dotenv

from app.platforms import argilla
from app.profiles import cozie_safety

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV = PROJECT_ROOT / ".env"
DEFAULT_INPUT = PROJECT_ROOT / "workbench" / "input" / "safety_classifier_false_复核_医学标注.csv"
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
    parser.add_argument("--profile", choices=["cozie-safety"], default="cozie-safety")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--mode", choices=["review", "comparison"], default="review")
    parser.add_argument("--dataset", help="Defaults to a profile- and mode-specific v1 name")
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
            "Randomly sample after --offset; within each round, sub_capability and "
            "predicted_safety_class are each unique; requires --limit"
        ),
    )
    parser.add_argument("--workspace", help="Defaults to ARGILLA_WORKSPACE or default")
    parser.add_argument("--api-url", help="Defaults to ARGILLA_API_URL or http://localhost:6900")
    parser.add_argument("--api-key", help="Defaults to ARGILLA_API_KEY; prefer using an env file")
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--min-submitted", type=int, default=2)
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate without contacting a platform"
    )
    actions = parser.add_mutually_exclusive_group()
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
        default="medical_reviewer",
        help="Username prefix for --create-users (default: medical_reviewer)",
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


def _balanced_random_sample(
    rows: list[dict[str, str]],
    limit: int,
    *,
    rng: random.Random | None = None,
) -> list[dict[str, str]]:
    """Globally distribute valid rows into balanced random rounds."""
    randomizer = rng or random.Random()
    real_buckets: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        sub_capability = row.get("sub_capability", "").strip()
        safety_class = row.get("predicted_safety_class", "").strip()
        if sub_capability and safety_class:
            real_buckets[(sub_capability, safety_class)].append(row)

    if not real_buckets:
        return []

    sub_capabilities = list({key[0] for key in real_buckets})
    safety_classes = list({key[1] for key in real_buckets})
    randomizer.shuffle(sub_capabilities)
    randomizer.shuffle(safety_classes)
    sub_index = {value: index for index, value in enumerate(sub_capabilities)}
    class_index = {value: index for index, value in enumerate(safety_classes)}

    vertex_count = max(len(sub_capabilities), len(safety_classes))
    edge_buckets: dict[tuple[int, int], list[dict[str, str] | None]] = defaultdict(list)
    left_degree = [0] * vertex_count
    right_degree = [0] * vertex_count
    for (sub_capability, safety_class), bucket in real_buckets.items():
        left = sub_index[sub_capability]
        right = class_index[safety_class]
        edge_buckets[(left, right)].extend(bucket)
        left_degree[left] += len(bucket)
        right_degree[right] += len(bucket)

    # Treat every row as an edge between the two sampling fields. Padding the
    # graph to a regular bipartite multigraph lets each perfect matching form
    # one round and spreads high-frequency values across all rounds.
    round_count = max(max(left_degree), max(right_degree))
    left_deficit = [round_count - degree for degree in left_degree]
    right_deficit = [round_count - degree for degree in right_degree]
    left = right = 0
    while left < vertex_count and right < vertex_count:
        if left_deficit[left] == 0:
            left += 1
            continue
        if right_deficit[right] == 0:
            right += 1
            continue
        amount = min(left_deficit[left], right_deficit[right])
        edge_buckets[(left, right)].extend([None] * amount)
        left_deficit[left] -= amount
        right_deficit[right] -= amount

    for bucket in edge_buckets.values():
        randomizer.shuffle(bucket)

    rounds: list[list[dict[str, str]]] = []
    for _ in range(round_count):
        adjacency: dict[int, list[int]] = defaultdict(list)
        for (left, right), bucket in edge_buckets.items():
            if bucket:
                adjacency[left].append(right)

        left_vertices = list(range(vertex_count))
        randomizer.shuffle(left_vertices)
        for right_vertices in adjacency.values():
            randomizer.shuffle(right_vertices)

        matched_by_right: dict[int, int] = {}

        def assign(left_vertex: int, seen_right: set[int]) -> bool:
            for right_vertex in adjacency[left_vertex]:
                if right_vertex in seen_right:
                    continue
                seen_right.add(right_vertex)
                previous_left = matched_by_right.get(right_vertex)
                if previous_left is None or assign(previous_left, seen_right):
                    matched_by_right[right_vertex] = left_vertex
                    return True
            return False

        for left_vertex in left_vertices:
            if not assign(left_vertex, set()):
                raise RuntimeError("failed to build a balanced random sampling round")

        sample_round: list[dict[str, str]] = []
        for right_vertex, left_vertex in matched_by_right.items():
            row = edge_buckets[(left_vertex, right_vertex)].pop()
            if row is not None:
                sample_round.append(row)
        rounds.append(sample_round)

    randomizer.shuffle(rounds)
    selected: list[dict[str, str]] = []
    for sample_round in rounds:
        randomizer.shuffle(sample_round)
        if selected:
            previous = selected[-1]
            compatible = [
                index
                for index, row in enumerate(sample_round)
                if row["sub_capability"].strip()
                != previous["sub_capability"].strip()
                and row["predicted_safety_class"].strip()
                != previous["predicted_safety_class"].strip()
            ]
            if compatible:
                first = randomizer.choice(compatible)
                sample_round[0], sample_round[first] = sample_round[first], sample_round[0]

        remaining_limit = limit - len(selected)
        selected.extend(sample_round[:remaining_limit])
        if len(selected) == limit:
            break

    return selected


def run(args: argparse.Namespace) -> int:
    if args.platform != "argilla":
        raise ValueError(f"unsupported platform: {args.platform}")
    if args.profile != cozie_safety.NAME:
        raise ValueError(f"unsupported profile: {args.profile}")
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
                else argilla.batch_usernames(args.user_prefix, args.delete_users)
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

        usernames = argilla.batch_usernames(args.user_prefix, args.create_users)
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

    rows = cozie_safety.load_rows(args.input)
    source_records = len(rows)
    if args.offset >= source_records:
        raise ValueError(
            f"--offset {args.offset} is outside the input containing {source_records} CSV records"
        )
    rows = rows[args.offset :]
    excluded_empty_sampling_fields = 0
    if args.random:
        excluded_empty_sampling_fields = sum(
            not row.get("sub_capability", "").strip()
            or not row.get("predicted_safety_class", "").strip()
            for row in rows
        )
        rows = _balanced_random_sample(rows, args.limit)
    elif args.limit is not None:
        rows = rows[: args.limit]
    dataset_name = args.dataset or (
        f"{cozie_safety.DEFAULT_DATASET_PREFIX}_v1"
        if args.mode == "review"
        else f"{cozie_safety.DEFAULT_DATASET_PREFIX}_{args.mode}_v1"
    )

    if args.dry_run:
        client = argilla.offline_client()
    else:
        if not api_key:
            raise ValueError(
                "ARGILLA_API_KEY is missing. Copy it from Argilla > My Settings into .env."
            )
        client = rg.Argilla(api_url=api_url, api_key=api_key)

    settings = argilla.build_settings(args.mode, args.min_submitted, client)
    records = argilla.build_records(rows, args.mode)
    summary = {
        "platform": args.platform,
        "profile": args.profile,
        "mode": args.mode,
        "dataset": dataset_name,
        "source_records": source_records,
        "offset": args.offset,
        "sampling": "balanced_random" if args.random else "ordered",
        "excluded_empty_sampling_fields": excluded_empty_sampling_fields,
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
