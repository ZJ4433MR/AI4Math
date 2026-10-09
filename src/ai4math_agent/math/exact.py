"""Complete profiles using integer XOR/popcount and only global inversion."""

from __future__ import annotations

import hashlib
import time
from numbers import Integral
from pathlib import Path

from .core import decode, evaluate


def exact_profile(n: int, max_states: int | None = None, wall_seconds: float = 600) -> dict:
    if isinstance(n, bool) or not isinstance(n, Integral) or n < 2:
        raise ValueError("n must be an integer at least 2")
    n = int(n)
    if max_states is not None and (isinstance(max_states, bool) or not isinstance(max_states, Integral) or max_states < 0):
        raise ValueError("max_states must be a nonnegative integer or null")
    if wall_seconds <= 0:
        raise ValueError("wall_seconds must be positive")
    start = time.monotonic()
    total = 1 << (n - 1)
    limit = total if max_states is None else min(total, int(max_states))
    masks = [(1 << (n - k)) - 1 for k in range(1, n)]
    best: dict[int, tuple[int, int, int]] = {}
    visited = 0
    reason = "completed"
    for representative in range(limit):
        if representative % 256 == 0 and time.monotonic() - start >= wall_seconds:
            reason = "wall_time"
            break
        x = representative << 1  # s[0]=+1; exactly one member of every +/- orbit.
        b = abs(n - 2 * x.bit_count())
        E = sum(((n - k) - 2 * ((x ^ (x >> k)) & masks[k - 1]).bit_count()) ** 2 for k in range(1, n))
        old = best.get(b)
        if old is None or E < old[0]:
            best[b] = (E, x, 1)
        elif E == old[0]:
            best[b] = (old[0], old[1], old[2] + 1)
        visited += 1
    complete = visited == total
    if not complete and reason == "completed":
        reason = "max_states"
    strata = []
    for b, (E, x, count) in sorted(best.items()):
        witness = evaluate(decode(x, n))
        strata.append({"b": b, "E": E, "sequence": witness["sequence"], "witness": witness,
                       "exact": complete, "representative_optimum_count": count,
                       "optimum_count": 2 * count if complete else None})
    optimum = min((v[0] for v in best.values()), default=None)
    optimal_b = [b for b, v in sorted(best.items()) if v[0] == optimum] if complete else []
    return {
        "n": n, "complete": complete, "exact": complete, "visited": visited,
        "total_states": total, "strata": strata, "optimal_b": optimal_b,
        "optimum_E": optimum if complete else None, "best_seen_E": optimum,
        "optimal_counts_by_b": {str(b): 2 * best[b][2] for b in optimal_b} if complete else {},
        "optimal_sequence_count": sum(2 * best[b][2] for b in optimal_b) if complete else None,
        "symmetry": "global inversion only; s[0]=+1; full orbit counts multiply representatives by 2",
        "encoding_convention": "bit i=1 iff s[i]=-1; bit 0 is s[0]",
        "alternating_sign_reduction": False, "termination_reason": reason,
        "wall_seconds": time.monotonic() - start,
        "source_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
