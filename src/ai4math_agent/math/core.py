"""Search arithmetic. Bit i is 1 exactly when sequence[i] is -1.

Energy and merit-factor numerators/denominators are Python integers. NumPy
int64 is used for correlations and correlation deltas, never int8 dot products.
The independent verifier does not import this module.
"""

from __future__ import annotations

import hashlib
import json
from numbers import Integral
from typing import Iterable

import numpy as np


def normalize(s: Iterable[int]) -> np.ndarray:
    values = list(s)
    if len(values) < 2:
        raise ValueError("sequence length must be at least 2")
    if any(isinstance(v, (bool, np.bool_)) or not isinstance(v, Integral) or int(v) not in (-1, 1) for v in values):
        raise ValueError("sequence symbols must be integer -1 or +1")
    return np.asarray(values, dtype=np.int64)


def encode(s: Iterable[int]) -> int:
    a = normalize(s)
    return sum(1 << i for i, v in enumerate(a) if int(v) == -1)


def decode(x: int, n: int) -> list[int]:
    if isinstance(n, bool) or not isinstance(n, Integral) or n < 2:
        raise ValueError("n must be an integer at least 2")
    if isinstance(x, bool) or not isinstance(x, Integral) or x < 0 or x >= 1 << int(n):
        raise ValueError("encoding must be an integer in [0, 2**n)")
    return [-1 if (int(x) >> i) & 1 else 1 for i in range(int(n))]


def correlations(s: Iterable[int]) -> np.ndarray:
    a = normalize(s)
    return np.asarray([np.dot(a[:-k], a[k:]) for k in range(1, len(a))], dtype=np.int64)


def batch_correlations(sequences: Iterable[Iterable[int]]) -> np.ndarray:
    """Common int64 evaluator for independent random candidates in a batch."""
    rows = list(sequences)
    if not rows:
        raise ValueError("batch must contain at least one sequence")
    a = np.vstack([normalize(row) for row in rows])
    n = a.shape[1]
    return np.stack([np.sum(a[:, :-k] * a[:, k:], axis=1, dtype=np.int64)
                     for k in range(1, n)], axis=1)


def evaluate(s: Iterable[int]) -> dict:
    a = normalize(s)
    values = a.tolist()
    n = len(a)
    C = correlations(a).tolist()
    E = sum(int(v) ** 2 for v in C)
    raw = json.dumps(values, separators=(",", ":")).encode("ascii")
    return {
        "sequence": values, "n": n, "C": C, "E": E,
        "F_numerator": n * n, "F_denominator": 2 * E,
        "F": n * n / (2 * E), "b": abs(sum(values)),
        "encoding": encode(a), "hash": hashlib.sha256(raw).hexdigest(),
    }


def _checked_C(C: Iterable[int], n: int) -> np.ndarray:
    a = np.asarray(list(C), dtype=np.int64)
    if a.shape != (n - 1,):
        raise ValueError("C must contain n-1 correlation values")
    return a


def all_flip_deltas(s: Iterable[int]) -> np.ndarray:
    """Return dC[j,k-1] for every single flip, evaluated at the old state."""
    a = normalize(s)
    n = len(a)
    deltas = np.zeros((n, n - 1), dtype=np.int64)
    for k in range(1, n):
        products = -2 * a[:-k] * a[k:]
        deltas[:-k, k - 1] += products
        deltas[k:, k - 1] += products
    return deltas


def flip_delta(s: Iterable[int], C: Iterable[int], j: int) -> np.ndarray:
    """Correlation delta; C is checked for shape, not recomputed for each move."""
    a = normalize(s)
    n = len(a)
    _checked_C(C, n)
    if isinstance(j, bool) or not isinstance(j, Integral) or not 0 <= j < n:
        raise ValueError("flip index outside sequence")
    j = int(j)
    d = np.zeros(n - 1, dtype=np.int64)
    if j:
        d[:j] -= 2 * a[j] * a[j - np.arange(1, j + 1)]
    if j + 1 < n:
        d[:n - j - 1] -= 2 * a[j] * a[j + np.arange(1, n - j)]
    return d


def pair_delta(s: Iterable[int], C: Iterable[int], i: int, j: int) -> np.ndarray:
    """Two simultaneous flips, including their shared-pair correction."""
    a = normalize(s)
    if i == j:
        raise ValueError("pair indices must be different")
    d = flip_delta(a, C, i) + flip_delta(a, C, j)
    d[abs(int(i) - int(j)) - 1] += 4 * a[int(i)] * a[int(j)]
    return d


def energy_delta(C: Iterable[int], dC: Iterable[int]) -> int:
    c, d = list(C), list(dC)
    if len(c) != len(d):
        raise ValueError("correlation and delta lengths differ")
    return sum(2 * int(x) * int(y) + int(y) ** 2 for x, y in zip(c, d))
