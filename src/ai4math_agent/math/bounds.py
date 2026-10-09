"""Exact discrete convex relaxation bounds and explicit certificates."""

from __future__ import annotations

import heapq
import time
from numbers import Integral


def validate_stratum(n: int, b: int) -> tuple[int, int]:
    if any(isinstance(x, bool) or not isinstance(x, Integral) for x in (n, b)):
        raise ValueError("n and b must be integers")
    n, b = int(n), int(b)
    if n < 2 or b < 0 or b > n or (n - b) % 2:
        raise ValueError("invalid LABS stratum: require n>=2, 0<=b<=n, b=n mod 2")
    return n, b


def lower_bound(n: int, b: int) -> dict:
    n, b = validate_stratum(n, b)
    start = time.monotonic()
    A = (b * b - n) // 2
    ell = list(range(n - 1, 0, -1))
    M = n * (n - 1) // 2
    if (A + M) % 2:
        raise ValueError("invalid resource parity")
    T = (A + M) // 2
    if not 0 <= T <= M:
        raise ValueError("resource count outside capacities")
    c = [-v for v in ell]
    heap = [(4 * v + 4, k) for k, v in enumerate(c)]
    heapq.heapify(heap)
    for _ in range(T):
        _, k = heapq.heappop(heap)
        c[k] += 2
        if c[k] < ell[k]:
            heapq.heappush(heap, (4 * c[k] + 4, k))
    parity = n // 2
    cs_num, cs_den = (b * b - n) ** 2, 4 * (n - 1)
    cs_ceiling = (cs_num + cs_den - 1) // cs_den
    simple = max(parity, cs_ceiling)
    congruent_simple = simple + ((parity - simple) % 4)
    return {
        "n": n, "b": b, "A": A, "c": c, "L": sum(v * v for v in c),
        "increments": T,
        "simple": {"parity": parity, "cauchy_numerator": cs_num, "cauchy_denominator": cs_den,
                   "cauchy_ceiling": cs_ceiling, "combined": simple,
                   "energy_congruence_adjusted": congruent_simple},
        "method": "exact convex integer resource allocation by minimum marginal heap",
        "wall_seconds": time.monotonic() - start,
    }
