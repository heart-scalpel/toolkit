"""Reusable record selection strategies."""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class SamplingResult:
    rows: list[dict[str, str]]
    excluded_missing_fields: int = 0


def ordered_sample(rows: list[dict[str, str]], limit: int | None) -> SamplingResult:
    return SamplingResult(rows=rows if limit is None else rows[:limit])


def _perfect_matching(
    adjacency: dict[int, list[int]],
    left_vertices: list[int],
) -> dict[int, int]:
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
    return matched_by_right


def balanced_random_sample(
    rows: list[dict[str, str]],
    limit: int,
    fields: tuple[str, str],
    *,
    rng: random.Random | None = None,
) -> SamplingResult:
    """Balance two profile-declared fields and exclude rows missing either value."""
    randomizer = rng or random.Random()
    left_field, right_field = fields
    real_buckets: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    excluded = 0
    for row in rows:
        left_value = row.get(left_field, "").strip()
        right_value = row.get(right_field, "").strip()
        if not left_value or not right_value:
            excluded += 1
            continue
        real_buckets[(left_value, right_value)].append(row)

    if not real_buckets:
        raise ValueError(
            "balanced sampling found no eligible records; "
            f"profile requires non-empty fields: {left_field}, {right_field}"
        )

    left_values = list({key[0] for key in real_buckets})
    right_values = list({key[1] for key in real_buckets})
    randomizer.shuffle(left_values)
    randomizer.shuffle(right_values)
    left_index = {value: index for index, value in enumerate(left_values)}
    right_index = {value: index for index, value in enumerate(right_values)}

    vertex_count = max(len(left_values), len(right_values))
    edge_buckets: dict[tuple[int, int], list[dict[str, str] | None]] = defaultdict(list)
    left_degree = [0] * vertex_count
    right_degree = [0] * vertex_count
    for (left_value, right_value), bucket in real_buckets.items():
        left = left_index[left_value]
        right = right_index[right_value]
        edge_buckets[(left, right)].extend(bucket)
        left_degree[left] += len(bucket)
        right_degree[right] += len(bucket)

    # Padding to a regular bipartite multigraph lets each perfect matching form
    # one round, spreading high-frequency values across the complete sample.
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

        matched_by_right = _perfect_matching(adjacency, left_vertices)

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
                if row[left_field].strip() != previous[left_field].strip()
                and row[right_field].strip() != previous[right_field].strip()
            ]
            if compatible:
                first = randomizer.choice(compatible)
                sample_round[0], sample_round[first] = sample_round[first], sample_round[0]

        remaining_limit = limit - len(selected)
        selected.extend(sample_round[:remaining_limit])
        if len(selected) == limit:
            break

    return SamplingResult(rows=selected, excluded_missing_fields=excluded)
