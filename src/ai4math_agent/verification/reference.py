"""Independent Python-integer witness, relaxation and enumeration verification.

This module deliberately imports no ai4math_agent.math implementation.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from numbers import Integral


def _integer(v) -> bool:
    return isinstance(v, Integral) and not isinstance(v, bool)


def _sequence(s) -> list[int]:
    values = list(s)
    if len(values) < 2 or any(not _integer(v) or int(v) not in (-1, 1) for v in values):
        raise ValueError("sequence must contain at least two integer ±1 symbols")
    return [int(v) for v in values]


def evaluate_reference(s) -> dict:
    values = _sequence(s)
    n = len(values)
    C = []
    for k in range(1, n):
        acc = 0
        for i in range(n - k):
            acc += values[i] * values[i + k]
        C.append(acc)
    E = sum(v * v for v in C)
    encoding = sum(1 << i for i, v in enumerate(values) if v < 0)
    raw = json.dumps(values, separators=(",", ":")).encode("ascii")
    return {"sequence": values, "n": n, "C": C, "E": E,
            "F_numerator": n * n, "F_denominator": 2 * E,
            "F": n * n / (2 * E), "b": abs(sum(values)),
            "encoding": encoding, "hash": hashlib.sha256(raw).hexdigest()}


def verify_sequence(record: dict) -> dict:
    errors = []
    if not isinstance(record, dict):
        return {"valid": False, "errors": ["witness must be an object"], "reference": None}
    try:
        reference = evaluate_reference(record["sequence"])
    except (KeyError, TypeError, ValueError) as exc:
        return {"valid": False, "errors": [str(exc)], "reference": None}
    for name in ("n", "E", "F_numerator", "F_denominator", "b", "encoding"):
        if name not in record or not _integer(record[name]) or int(record[name]) != reference[name]:
            errors.append(f"{name} mismatch or missing integer")
    if record.get("C") != reference["C"] or any(not _integer(x) for x in record.get("C", [])):
        errors.append("C mismatch or noninteger correlation")
    if record.get("hash") != reference["hash"]:
        errors.append("sequence hash mismatch")
    F = record.get("F")
    if isinstance(F, bool) or not isinstance(F, (int, float)) or not math.isfinite(F) or not math.isclose(F, reference["F"], rel_tol=1e-12):
        errors.append("display merit factor mismatch")
    n, C, E, b = reference["n"], reference["C"], reference["E"], reference["b"]
    invariants = {
        "correlation_parity": all((v - (n - k)) % 2 == 0 for k, v in enumerate(C, 1)),
        "correlation_range": all(abs(v) <= n - k for k, v in enumerate(C, 1)),
        "correlation_sum": sum(C) == (b * b - n) // 2,
        "energy_parity_bound": E >= n // 2,
        "energy_mod_4": (E - n // 2) % 4 == 0,
    }
    errors.extend(name for name, valid in invariants.items() if not valid)
    return {"valid": not errors, "errors": errors, "reference": reference,
            "invariants": invariants, "implementation": "independent Python integer double summation"}


def _stratum(n, b) -> tuple[int, int]:
    if not _integer(n) or not _integer(b) or n < 2 or not 0 <= b <= n or (n - b) % 2:
        raise ValueError("invalid integer stratum")
    return int(n), int(b)


def check_bound(cert: dict) -> dict:
    errors = []
    if not isinstance(cert, dict):
        return {"valid": False, "errors": ["certificate must be an object"]}
    try:
        n, b = _stratum(cert["n"], cert["b"])
        c = cert["c"]
        if not isinstance(c, list) or len(c) != n - 1 or any(not _integer(v) for v in c):
            raise ValueError("certificate c must be n-1 integers")
        A = (b * b - n) // 2
        ell = [n - k for k in range(1, n)]
        if not _integer(cert.get("A")) or cert["A"] != A:
            errors.append("A mismatch")
        if sum(c) != A:
            errors.append("correlation sum constraint violated")
        if any(abs(v) > l or (v - l) % 2 for v, l in zip(c, ell)):
            errors.append("range or parity constraint violated")
        objective = sum(int(v) ** 2 for v in c)
        if not _integer(cert.get("L")) or cert["L"] != objective:
            errors.append("objective mismatch")
        selected = [4 * (v - 1) for v, l in zip(c, ell) if v > -l]
        next_cost = [4 * (v + 1) for v, l in zip(c, ell) if v < l]
        max_selected = max(selected) if selected else None
        min_next = min(next_cost) if next_cost else None
        exchange = max_selected is None or min_next is None or max_selected <= min_next
        if not exchange:
            errors.append("exchange optimality condition violated")
    except (KeyError, TypeError, ValueError) as exc:
        return {"valid": False, "errors": [str(exc)]}
    return {"valid": not errors, "errors": errors, "objective": objective,
            "exchange_condition": exchange, "max_selected_marginal": max_selected,
            "min_unselected_marginal": min_next,
            "certification": "integer relaxation optimum" if not errors else None}


def relaxation_dp(n: int, b: int) -> int:
    """Independent exact sum-index dynamic program, intended for small n."""
    n, b = _stratum(n, b)
    target = (b * b - n) // 2
    values = {0: 0}
    for k in range(1, n):
        ell = n - k
        nxt = {}
        for total, E in values.items():
            for c in range(-ell, ell + 1, 2):
                new_sum, new_E = total + c, E + c * c
                if new_sum not in nxt or new_E < nxt[new_sum]:
                    nxt[new_sum] = new_E
        values = nxt
    return values[target]


def profile_digest(profile: dict) -> str:
    """Bind a verifier annotation to the exact serialized profile it checked."""
    payload = {key: val for key, val in profile.items() if key != "verification"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()


def exact_profile_reference(n: int, wall_seconds: float = 600) -> dict:
    """Independent complete Gray-code pass with integer incremental updates.

    The update here is implemented separately from search deltas and XOR
    enumeration. Global sign orbits alone are reduced; |sum| is invariant.
    """
    if not _integer(n) or n < 2:
        raise ValueError("n must be an integer at least 2")
    if wall_seconds <= 0:
        raise ValueError("wall_seconds must be positive")
    n = int(n)
    total, visited = 1 << (n - 1), 0
    signs, C, signed_sum = [1] * n, list(range(n - 1, 0, -1)), n
    best = {}
    start = time.monotonic()
    for step in range(total):
        if step % 256 == 0 and time.monotonic() - start >= wall_seconds:
            break
        if step:
            j = (step & -step).bit_length()  # bit 0 is fixed; Gray bit t maps to position t+1.
            old = signs[j]
            for k in range(1, n):
                neighbor_sum = 0
                if j >= k:
                    neighbor_sum += signs[j - k]
                if j + k < n:
                    neighbor_sum += signs[j + k]
                C[k - 1] -= 2 * old * neighbor_sum
            signs[j] = -old
            signed_sum -= 2 * old
        b, E = abs(signed_sum), sum(v * v for v in C)
        if b not in best or E < best[b][0]:
            best[b] = [E, 1]
        elif E == best[b][0]:
            best[b][1] += 1
        visited += 1
    complete = visited == total
    return {"n": n, "complete": complete, "visited": visited, "total_states": total,
            "strata": {b: {"E": v[0], "optimum_count": 2 * v[1]} for b, v in best.items()},
            "wall_seconds": time.monotonic() - start}


def verify_exact_profile(profile: dict, exhaustive: bool = True, wall_seconds: float = 600) -> dict:
    """Return diagnostics, never exceptions for malformed evidence.

    exhaustive=False only checks witnesses and metadata; it cannot certify
    completeness. The independent pass's states and time are separate costs.
    """
    start, errors, reference = time.monotonic(), [], None
    try:
        n = profile["n"]
        if not _integer(n) or n < 2:
            raise ValueError("invalid profile length")
        total = 1 << (n - 1)
        complete = profile.get("complete") is True and profile.get("exact") is True
        if profile.get("total_states") != total:
            errors.append("total_states does not match sign-orbit enumeration")
        if not _integer(profile.get("visited")) or not 0 <= profile["visited"] <= total:
            errors.append("invalid visited count")
        elif complete and profile["visited"] != total:
            errors.append("exact profile did not visit all states")
        elif not complete and profile.get("exact"):
            errors.append("incomplete profile incorrectly marked exact")
        if profile.get("alternating_sign_reduction") is not False:
            errors.append("condition-profile symmetry reduction is not explicit or uses alternation")
        strata = profile["strata"]
        if not isinstance(strata, list):
            raise ValueError("strata must be a list")
        observed = {}
        for row in strata:
            if not isinstance(row, dict) or not _integer(row.get("b")) or not _integer(row.get("E")):
                raise ValueError("stratum b and E must be integers")
            if row["b"] in observed:
                errors.append("duplicate imbalance stratum")
            observed[row["b"]] = row
            witness = row.get("witness")
            if witness is None:
                witness = evaluate_reference(row["sequence"])
            check = verify_sequence(witness)
            if not check["valid"]:
                errors.append(f"invalid stratum witness b={row['b']}")
            elif witness["n"] != n or witness["b"] != row["b"] or witness["E"] != row["E"] or witness["sequence"] != row["sequence"]:
                errors.append("stratum/witness mismatch")
        if complete:
            if set(observed) != set(range(n % 2, n + 1, 2)):
                errors.append("completed profile lacks feasible strata")
            optimum = min(row["E"] for row in strata)
            optimal_b = sorted(row["b"] for row in strata if row["E"] == optimum)
            if profile.get("optimum_E") != optimum or profile.get("optimal_b") != optimal_b:
                errors.append("global optimum summary mismatch")
            if exhaustive:
                reference = exact_profile_reference(n, wall_seconds=wall_seconds)
                if not reference["complete"]:
                    errors.append("independent enumeration interrupted; completeness unverified")
                else:
                    for b, expected in reference["strata"].items():
                        row = observed.get(b, {})
                        if row.get("E") != expected["E"] or row.get("optimum_count") != expected["optimum_count"]:
                            errors.append(f"independent optimum/count mismatch b={b}")
                    expected_counts = {str(b): reference["strata"][b]["optimum_count"] for b in optimal_b}
                    if profile.get("optimal_counts_by_b") != expected_counts or profile.get("optimal_sequence_count") != sum(expected_counts.values()):
                        errors.append("global optimum set counts mismatch")
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        errors.append(str(exc))
    try:
        digest = profile_digest(profile)
    except (TypeError, ValueError):
        digest = None
    recomputed_complete = reference is not None and reference["complete"] and not errors
    return {"valid": not errors, "errors": errors, "recomputed_complete": recomputed_complete,
            "checked_states": reference["visited"] if reference else 0,
            "wall_seconds": time.monotonic() - start, "profile_hash": digest,
            "implementation": "independent Python integer Gray-code enumeration" if exhaustive else "witness and metadata checks only"}
