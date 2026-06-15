"""Pure random task-to-PE assignment generation.

This module intentionally does not inspect task communication, compute time,
thermal data, energy, makespan, or any OMNeT++ result.
"""

from __future__ import annotations

import random


def generate_random_assignment(
    mappable_task_ids: list[int],
    num_pes: int,
    sample_seed: int,
) -> dict[int, int]:
    """Generate one random mapping for all mappable tasks.

    Each task independently draws one PE from range(num_pes). Multiple tasks
    may map to the same PE, matching the B-2 GA chromosome representation.
    """
    if num_pes <= 0:
        raise ValueError(f"num_pes must be positive, got {num_pes}")

    rng = random.Random(sample_seed)
    assignment = {
        int(tid): rng.randrange(num_pes)
        for tid in mappable_task_ids
    }
    validate_random_assignment(assignment, mappable_task_ids, num_pes)
    return assignment


def validate_random_assignment(
    assignment: dict[int, int],
    mappable_task_ids: list[int],
    num_pes: int,
) -> None:
    """Validate key coverage and PE range for a random assignment."""
    expected = set(mappable_task_ids)
    actual = set(assignment)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        raise ValueError(f"missing assignments for tasks: {missing}")
    if extra:
        raise ValueError(f"assignment contains non-mappable tasks: {extra}")

    bad_pes = {
        tid: pe for tid, pe in assignment.items()
        if not isinstance(pe, int) or pe < 0 or pe >= num_pes
    }
    if bad_pes:
        raise ValueError(f"assignment contains PE ids outside 0..{num_pes - 1}: {bad_pes}")

