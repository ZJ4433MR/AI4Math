"""A common evaluation ledger and reproducible CPU search tools.

Every requested candidate energy is charged, including forbidden neighbors and
duplicate states. A short final neighborhood is scored in the same ordered prefix
as a full scan and then stops without applying a partial-scan move. This supplies a
precise, method-independent truncation protocol.

Tabu stages draw ``L`` uniformly from ``ceil(n/2)..floor(3n/2)`` (inclusive),
scale by ``restart_scale`` and round half up. Tenure is
``max(1, floor(tabu_scale * L + 0.5))``. Stage restarts are charged. A move may
increase energy; an improving run-best move overrides its tabu status. Ties are
broken with the seeded RNG. ``fixed_b`` preserves the signed sum +b.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import platform
import random
import time
import zlib
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ai4math_agent.math.core import (
    all_flip_deltas,
    batch_correlations,
    correlations,
    evaluate,
)

METHODS = {"random", "fixed_tabu", "skew", "fixed_b", "static_mix", "agent_policy"}
POLICY_KEYS = {"skew_fraction", "tabu_scale", "restart_scale", "perturb_bits", "decision_summary"}


def _encoding(s: np.ndarray | list[int]) -> int:
    return sum((1 << j) for j, value in enumerate(s) if int(value) == -1)


def _sequence(key: int, n: int) -> np.ndarray:
    return np.array([-1 if key & (1 << j) else 1 for j in range(n)], dtype=np.int64)


def _unpack_sequences(keys: list[int], n: int) -> np.ndarray:
    width = (n + 7) // 8
    raw = b"".join(key.to_bytes(width, "little") for key in keys)
    octets = np.frombuffer(raw, dtype=np.uint8).reshape(len(keys), width)
    bits = np.unpackbits(octets, axis=1, bitorder="little")[:, :n]
    return 1 - 2 * bits.astype(np.int64)


def _tuple_tree(value: Any) -> Any:
    return tuple(_tuple_tree(x) for x in value) if isinstance(value, (list, tuple)) else value


def _json_tree(value: Any) -> Any:
    if isinstance(value, (tuple, list)):
        return [_json_tree(x) for x in value]
    if isinstance(value, np.integer):
        return int(value)
    return value


def _validate_sequence(s: Any, n: int) -> np.ndarray:
    if not isinstance(s, (list, tuple, np.ndarray)) or len(s) != n:
        raise ValueError("initial sequence must have exactly n symbols")
    if any(isinstance(x, (bool, np.bool_)) or x not in (-1, 1) for x in s):
        raise ValueError("sequence symbols must be integers -1 or +1")
    return np.array(s, dtype=np.int64)


def is_skew(s: np.ndarray | list[int]) -> bool:
    n = len(s)
    if n % 2 == 0:
        return False
    m = n // 2
    return all(int(s[m + j]) == (-1 if j % 2 else 1) * int(s[m - j]) for j in range(1, m + 1))


def _fresh(n: int, restriction: str, rng: random.Random, b: int | None) -> np.ndarray:
    if restriction == "fixed_b":
        s = np.ones(n, dtype=np.int64)
        s[rng.sample(range(n), (n - int(b)) // 2)] = -1
        return s
    s = _sequence(rng.getrandbits(n), n)
    if restriction == "skew":
        m = n // 2
        for j in range(1, m + 1):
            s[m + j] = (-1 if j % 2 else 1) * s[m - j]
    return s


def _restriction(method: str, n: int, policy: dict[str, Any]) -> str:
    if method in {"skew", "fixed_b"}:
        return method
    if method in {"static_mix", "agent_policy"} and n % 2 and policy["skew_fraction"] > 0:
        return "skew"
    return "unrestricted"


def _policy(method: str, supplied: dict[str, Any] | None) -> dict[str, Any]:
    p: dict[str, Any] = {"skew_fraction": 0.5, "tabu_scale": 0.11, "restart_scale": 1.0, "perturb_bits": 0,
                         "decision_summary": "Frozen CPU defaults"}
    if method == "agent_policy" and supplied is None:
        raise ValueError("agent_policy requires an explicit frozen policy")
    if supplied is not None:
        if not isinstance(supplied, dict) or set(supplied) - POLICY_KEYS:
            raise ValueError("unsupported policy DSL fields")
        p.update(supplied)
    for key, lower, upper in (("skew_fraction", 0, 1), ("tabu_scale", 0.05, 0.3), ("restart_scale", 0.5, 2)):
        value = p[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lower <= value <= upper:
            raise ValueError(f"invalid {key}")
        p[key] = float(value)
    if type(p["perturb_bits"]) is not int or not 0 <= p["perturb_bits"] <= 8:
        raise ValueError("perturb_bits must be an integer in 0..8")
    if not isinstance(p["decision_summary"], str):
        raise ValueError("decision_summary must be a string")
    return p


@dataclass
class _Meter:
    n: int
    cap: int
    deadline: float
    count: int = 0
    seen: set[int] = field(default_factory=set)
    best_key: int | None = None
    best_energy: int | None = None
    curve: list[dict[str, int]] = field(default_factory=list)
    initialization_evaluations: int = 0
    neighborhood_evaluations: int = 0
    random_evaluations: int = 0
    forbidden_evaluations: int = 0
    perturbation_evaluations: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.cap - self.count)

    def timed_out(self) -> bool:
        return time.perf_counter() >= self.deadline

    def observe(self, keys: list[int], energies: np.ndarray | list[int], category: str) -> None:
        if len(keys) > self.remaining:
            raise RuntimeError("evaluation ledger overshoot")
        for key, energy in zip(keys, energies, strict=True):
            self.count += 1
            self.seen.add(key)
            energy = int(energy)
            if self.best_energy is None or energy < self.best_energy:
                self.best_energy, self.best_key = energy, key
                self.curve.append({"evaluations": self.count, "E": energy})
        if category == "initialization":
            self.initialization_evaluations += len(keys)
        elif category == "perturbation":
            self.perturbation_evaluations += len(keys)
        elif category == "random":
            self.random_evaluations += len(keys)
        else:
            self.neighborhood_evaluations += len(keys)

    def score_sequence(self, s: np.ndarray, category: str = "initialization") -> tuple[np.ndarray, int]:
        c = correlations(s)
        e = int(np.dot(c, c))
        self.observe([_encoding(s)], [e], category)
        return c, e

    def visited_blob(self) -> str:
        width = (self.n + 7) // 8
        raw = b"".join(x.to_bytes(width, "little") for x in sorted(self.seen))
        return base64.b64encode(zlib.compress(raw)).decode("ascii")

    def restore_seen(self, blob: str) -> None:
        width = (self.n + 7) // 8
        raw = zlib.decompress(base64.b64decode(blob))
        if len(raw) % width:
            raise ValueError("invalid checkpoint visited set")
        self.seen = {int.from_bytes(raw[i:i + width], "little") for i in range(0, len(raw), width)}


@dataclass
class _State:
    s: np.ndarray
    c: np.ndarray
    energy: int
    restriction: str
    local_best: np.ndarray
    local_best_energy: int
    iteration: int = 0
    stage_limit: int = 1
    tenure: int = 1
    tabu_until: np.ndarray | None = None
    restarts: int = 0
    stagnation_iterations: int = 0


def _new_stage(state: _State, rng: random.Random, n: int, p: dict[str, Any]) -> None:
    drawn = rng.randint((n + 1) // 2, (3 * n) // 2)
    state.stage_limit = max(1, math.floor(drawn * p["restart_scale"] + 0.5))
    state.tenure = max(1, math.floor(state.stage_limit * p["tabu_scale"] + 0.5))
    state.iteration = 0
    state.tabu_until = np.zeros(n, dtype=np.int64)
    state.local_best = state.s.copy()
    state.local_best_energy = state.energy


def _moves(state: _State, rng: random.Random, n: int) -> list[tuple[int, ...]]:
    if state.restriction == "unrestricted":
        return [(j,) for j in range(n)]
    if state.restriction == "skew":
        m = n // 2
        return [(j, n - 1 - j) for j in range(m)] + [(m,)]
    positives = np.flatnonzero(state.s == 1).tolist()
    negatives = np.flatnonzero(state.s == -1).tolist()
    pool = len(positives) * len(negatives)
    if pool == 0:
        return []
    # Uniformly sample distinct legal pairs, avoiding an O(n^2) scan.
    indexes = rng.sample(range(pool), min(n, pool))
    return [(positives[x // len(negatives)], negatives[x % len(negatives)]) for x in indexes]


def _neighbor_deltas(state: _State, moves: list[tuple[int, ...]]) -> np.ndarray:
    singles = all_flip_deltas(state.s)
    d = np.array([singles[move[0]].copy() for move in moves], dtype=np.int64)
    for row, move in enumerate(moves):
        if len(move) == 2:
            i, j = move
            d[row] += singles[j]
            d[row, abs(i - j) - 1] += 4 * int(state.s[i]) * int(state.s[j])
    return d


def _snapshot(state: _State, meter: _Meter) -> dict[str, Any]:
    return {
        "restriction": state.restriction,
        "current": {"sequence": state.s.tolist(), "C": state.c.tolist(), "E": state.energy},
        "local_best": {"sequence": state.local_best.tolist(), "E": state.local_best_energy},
        "run_best": None if meter.best_key is None else {"sequence": _sequence(meter.best_key, meter.n).tolist(), "E": meter.best_energy},
        "iteration": state.iteration, "stage_limit": state.stage_limit, "tenure": state.tenure,
        "tabu_until": state.tabu_until.tolist(), "restarts": state.restarts,
        "stagnation_iterations": state.stagnation_iterations,
    }


def _restore_state(data: dict[str, Any], n: int) -> _State:
    current, local = data["current"], data["local_best"]
    s = _validate_sequence(current["sequence"], n)
    c = correlations(s)
    energy = int(np.dot(c, c))
    if energy != current["E"] or c.tolist() != current["C"]:
        raise ValueError("checkpoint current state failed recomputation")
    local_s = _validate_sequence(local["sequence"], n)
    local_c = correlations(local_s)
    if int(np.dot(local_c, local_c)) != local["E"]:
        raise ValueError("checkpoint local best failed recomputation")
    state = _State(s, c, energy, data["restriction"], local_s, int(local["E"]))
    for name in ("iteration", "stage_limit", "tenure", "restarts", "stagnation_iterations"):
        setattr(state, name, int(data[name]))
    state.tabu_until = np.array(data["tabu_until"], dtype=np.int64)
    return state


def _perturb(state: _State, rng: random.Random, n: int, p: dict[str, Any], b: int | None) -> np.ndarray:
    if p["perturb_bits"] == 0:
        return _fresh(n, state.restriction, rng, b)
    s = state.local_best.copy()
    if state.restriction == "fixed_b":
        positives, negatives = np.flatnonzero(s == 1).tolist(), np.flatnonzero(s == -1).tolist()
        pairs = min(max(1, p["perturb_bits"] // 2), len(positives), len(negatives))
        for i, j in zip(rng.sample(positives, pairs), rng.sample(negatives, pairs), strict=True):
            s[i] *= -1
            s[j] *= -1
    elif state.restriction == "skew":
        m = n // 2
        for j in rng.sample(range(m + 1), min(p["perturb_bits"], m + 1)):
            s[j] *= -1
            if j != m:
                s[n - 1 - j] *= -1
    else:
        s[rng.sample(range(n), min(p["perturb_bits"], n))] *= -1
    return s


def run_search(
    n: int,
    method: str,
    evaluations: int,
    seed: int,
    initial: list[int] | dict[str, Any] | None = None,
    b: int | None = None,
    policy: dict[str, Any] | None = None,
    wall_seconds: float = 1200,
) -> dict[str, Any]:
    """Search without exceeding requested evaluations or wall time.

    ``initial=list`` is a new, charged initialization. ``initial=checkpoint``
    resumes the same method with its consumed ledger, RNG, visited set and tabu
    state; ``evaluations`` remains the TOTAL run cap. Restriction release starts a
    fresh charged run and is exposed separately, so controllers can debit its
    incremental cost from their shared session ledger.
    """
    started = time.perf_counter()
    if type(n) is not int or n < 2:
        raise ValueError("n must be an integer >= 2")
    if method not in METHODS:
        raise ValueError("unsupported search method")
    if type(evaluations) is not int or evaluations < 1:
        raise ValueError("evaluations must be a positive integer")
    if type(seed) is not int or not isinstance(wall_seconds, (int, float)) or isinstance(wall_seconds, bool) or not math.isfinite(wall_seconds) or wall_seconds <= 0:
        raise ValueError("seed and wall_seconds are invalid")
    if method == "skew" and n % 2 == 0:
        raise ValueError("skew search requires odd n")
    if method == "fixed_b":
        if type(b) is not int or not 0 <= b <= n or (n - b) % 2:
            raise ValueError("fixed_b requires a feasible nonnegative signed b")
    elif b is not None:
        raise ValueError("b is supported only by fixed_b")
    p = _policy(method, policy)
    rng = random.Random(seed)
    previous_elapsed = 0.0
    phase_end = math.floor(evaluations * p["skew_fraction"])
    release_snapshots: list[dict[str, Any]] = []
    meter = _Meter(n, evaluations, started + wall_seconds)
    if isinstance(initial, dict):
        cp = initial
        if cp.get("version") != 1 or cp["n"] != n or cp["method"] != method or cp["seed"] != seed or cp["b"] != b or cp["params"] != p:
            raise ValueError("checkpoint does not match search configuration")
        previous_elapsed = float(cp["elapsed"])
        meter.deadline = started + max(0, wall_seconds - previous_elapsed)
        meter.count = int(cp["evaluations"])
        if meter.count > evaluations:
            raise ValueError("checkpoint has already exceeded requested total cap")
        meter.restore_seen(cp["visited_zlib_base64"])
        meter.curve = [dict(row) for row in cp["curve"]]
        for key in ("initialization_evaluations", "neighborhood_evaluations", "random_evaluations", "forbidden_evaluations", "perturbation_evaluations"):
            setattr(meter, key, int(cp["accounting"][key]))
        best = cp["state"]["run_best"]
        if best is not None:
            best_s = _validate_sequence(best["sequence"], n)
            best_c = correlations(best_s)
            if int(np.dot(best_c, best_c)) != best["E"]:
                raise ValueError("checkpoint run best failed recomputation")
            meter.best_key, meter.best_energy = _encoding(best_s), int(best["E"])
        state = _restore_state(cp["state"], n)
        rng.setstate(_tuple_tree(cp["rng_state"]))
        phase_end = int(cp["phase_end"])
        release_snapshots = cp.get("release_checkpoints", [])
    else:
        restriction = _restriction(method, n, p)
        if restriction == "skew" and phase_end == 0 and method != "skew":
            restriction = "unrestricted"
        s = _fresh(n, restriction, rng, b) if initial is None else _validate_sequence(initial, n)
        if restriction == "skew" and not is_skew(s):
            raise ValueError("initial sequence violates skew symmetry")
        if restriction == "fixed_b" and int(np.sum(s)) != b:
            raise ValueError("initial sequence violates signed sum +b")
        # No candidate is scored after the wall cap, even during initialization.
        if meter.timed_out():
            return {"best": None, "curve": [], "evaluations": 0, "unique_evaluations": 0,
                    "elapsed": time.perf_counter() - started, "checkpoint": None,
                    "termination_reason": "wall_time", "method": method, "seed": seed,
                    "params": p, "restriction": restriction, "accounting": {}}
        c, energy = meter.score_sequence(s, "random" if method == "random" else "initialization")
        state = _State(s, c, energy, restriction, s.copy(), energy)
        _new_stage(state, rng, n, p)
    reason = "evaluation_budget"
    while meter.remaining:
        if meter.timed_out():
            reason = "wall_time"
            break
        if method == "random":
            # All methods use the same int64 correlation/energy core. Each random
            # state remains an independent draw; the optional initial is charged.
            size = min(128, meter.remaining)
            keys = [rng.getrandbits(n) for _ in range(size)]
            sequences = _unpack_sequences(keys, n)
            cs = batch_correlations(sequences)
            energies = np.sum(cs * cs, axis=1, dtype=np.int64)
            meter.observe(keys, energies, "random")
            state.s, state.c, state.energy = sequences[-1].copy(), cs[-1].copy(), int(energies[-1])
            state.local_best = _sequence(int(meter.best_key), n)
            state.local_best_energy = int(meter.best_energy)
            continue
        if method in {"static_mix", "agent_policy"} and state.restriction == "skew" and meter.count >= phase_end:
            before = _snapshot(state, meter)
            state.restriction = "unrestricted"
            # Releasing changes only the allowed moves. Preserve the current
            # sequence exactly, and charge its unrestricted initialization.
            state.c, state.energy = meter.score_sequence(state.s)
            _new_stage(state, rng, n, p)
            release_snapshots.append({"evaluations_before": meter.count - 1, "before": before, "after": _snapshot(state, meter)})
            continue
        if state.iteration >= state.stage_limit:
            state.s = _perturb(state, rng, n, p, b)
            state.c, state.energy = meter.score_sequence(state.s, "perturbation" if p["perturb_bits"] else "initialization")
            state.restarts += 1
            _new_stage(state, rng, n, p)
            continue
        moves = _moves(state, rng, n)
        if not moves:
            reason = "no_legal_neighbors"
            break
        phase_remaining = meter.remaining
        if state.restriction == "skew" and method in {"static_mix", "agent_policy"}:
            phase_remaining = min(phase_remaining, max(0, phase_end - meter.count))
        available = min(len(moves), phase_remaining)
        if available == 0:
            continue
        truncated = available < len(moves)
        scored = moves[:available]
        d = _neighbor_deltas(state, scored)
        energies = state.energy + np.sum((2 * state.c + d) * d, axis=1, dtype=np.int64)
        current_key = _encoding(state.s)
        keys = [current_key ^ sum(1 << j for j in move) for move in scored]
        forbidden = [any(int(state.tabu_until[j]) > state.iteration for j in move) for move in scored]
        run_best_before = int(meter.best_energy)
        meter.forbidden_evaluations += sum(forbidden)
        meter.observe(keys, energies, "neighborhood")
        if truncated:
            if meter.remaining == 0:
                reason = "budget_truncated_neighborhood"
                break
            # A phase boundary uses the same prefix protocol; release preserves
            # current rather than applying a move from an incomplete scan.
            continue
        allowed = [i for i, energy in enumerate(energies) if not forbidden[i] or int(energy) < run_best_before]
        state.iteration += 1
        state.stagnation_iterations += 1
        if not allowed:
            continue  # All scored moves remain tabu; time advances to expiry.
        minimum = min(int(energies[i]) for i in allowed)
        chosen = rng.choice([i for i in allowed if int(energies[i]) == minimum])
        state.c += d[chosen]
        state.s[list(scored[chosen])] *= -1
        state.energy = minimum
        for j in scored[chosen]:
            state.tabu_until[j] = state.iteration + state.tenure
        if minimum < state.local_best_energy:
            state.local_best, state.local_best_energy = state.s.copy(), minimum
            state.stagnation_iterations = 0
    if meter.curve and meter.curve[-1]["evaluations"] != meter.count:
        meter.curve.append({"evaluations": meter.count, "E": int(meter.best_energy)})
    accounting = {key: int(getattr(meter, key)) for key in (
        "initialization_evaluations", "neighborhood_evaluations", "random_evaluations", "forbidden_evaluations", "perturbation_evaluations")}
    elapsed = previous_elapsed + time.perf_counter() - started
    checkpoint = {"version": 1, "n": n, "method": method, "seed": seed, "b": b, "params": p,
                  "evaluations": meter.count, "unique_evaluations": len(meter.seen), "elapsed": elapsed,
                  "curve": meter.curve, "state": _snapshot(state, meter), "rng_state": _json_tree(rng.getstate()),
                  "phase_end": phase_end, "release_checkpoints": release_snapshots,
                  "accounting": accounting, "visited_zlib_base64": meter.visited_blob()}
    policy_hash = hashlib.sha256(json.dumps(p, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if method == "skew":
        actual_skew_fraction = 1.0
    elif method in {"static_mix", "agent_policy"} and n % 2 and p["skew_fraction"] > 0:
        skew_evaluations = release_snapshots[0]["evaluations_before"] if release_snapshots else meter.count
        actual_skew_fraction = skew_evaluations / meter.count if meter.count else 0.0
    else:
        actual_skew_fraction = 0.0
    return {"best": None if meter.best_key is None else evaluate(_sequence(meter.best_key, n)),
            "curve": meter.curve, "evaluations": meter.count, "unique_evaluations": len(meter.seen),
            "elapsed": elapsed, "checkpoint": checkpoint, "termination_reason": reason,
            "method": method, "seed": seed, "params": p, "policy_hash": policy_hash,
            "restriction": state.restriction, "accounting": accounting,
            "diagnostics": {"restarts": state.restarts, "stagnation_iterations": state.stagnation_iterations,
                            "current_E": state.energy, "local_best_E": state.local_best_energy,
                            "effective_skew_fraction": actual_skew_fraction}}


def release_restriction(checkpoint: dict[str, Any], evaluations: int, seed: int, wall_seconds: float = 1200,
                        policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Start a new counted unrestricted run at the exact checkpoint current state."""
    current = checkpoint["state"]["current"]["sequence"]
    result = run_search(checkpoint["n"], "fixed_tabu", evaluations, seed, initial=current,
                        policy=policy, wall_seconds=wall_seconds)
    result["release"] = {"from_restriction": checkpoint["state"]["restriction"],
                         "to_restriction": "unrestricted", "before": checkpoint["state"],
                         "preserved_initial_sequence": current,
                         "initialization_cost": 1 if result["evaluations"] else 0}
    return result


def restart(checkpoint: dict[str, Any], evaluations: int, seed: int, perturb_bits: int = 2,
            wall_seconds: float = 1200) -> dict[str, Any]:
    """Perturb a checkpoint under its original constraint, charging the new state."""
    n = checkpoint["n"]
    s = _validate_sequence(checkpoint["state"]["current"]["sequence"], n)
    c = correlations(s)
    state = _State(s, c, int(np.dot(c, c)), checkpoint["state"]["restriction"], s.copy(), int(np.dot(c, c)))
    p = _policy("fixed_tabu", {"perturb_bits": perturb_bits})
    initial = _perturb(state, random.Random(seed), n, p, checkpoint["b"]).tolist()
    method = state.restriction if state.restriction != "unrestricted" else "fixed_tabu"
    result = run_search(n, method, evaluations, seed, initial=initial, b=checkpoint["b"], policy=p,
                        wall_seconds=wall_seconds)
    result["restart"] = {"before": checkpoint["state"], "perturbed_initial_sequence": initial,
                         "initialization_cost": 1 if result["evaluations"] else 0}
    return result


def calibrate(n: int = 127, evaluations: int = 5000, seed: int = 20261009,
              wall_seconds: float = 10) -> dict[str, Any]:
    """Representative CPU throughput; caller freezes budgets before evaluation."""
    measured: dict[str, Any] = {}
    started = time.perf_counter()
    for method in ("random", "fixed_tabu", "static_mix", "agent_policy", "fixed_b"):
        remaining = wall_seconds - (time.perf_counter() - started)
        if remaining <= 0:
            break
        kwargs: dict[str, Any] = {"policy": _policy("fixed_tabu", None)} if method == "agent_policy" else {}
        if method == "fixed_b":
            kwargs["b"] = n % 2
        result = run_search(n, method, evaluations, seed, wall_seconds=remaining, **kwargs)
        measured[method] = {"evaluations": result["evaluations"], "elapsed": result["elapsed"],
                            "evaluations_per_second": result["evaluations"] / max(result["elapsed"], 1e-9),
                            "termination_reason": result["termination_reason"]}
    slowest = min((m["evaluations_per_second"] for m in measured.values()), default=0)
    recommended = min(50000, max(5000, math.floor(1800 * slowest / 60)))
    return {"n": n, "requested_evaluations": evaluations, "seed": seed, "methods": measured,
            "hardware": {"platform": platform.platform(), "processor": platform.processor(),
                         "python": platform.python_version(), "numpy": np.__version__},
            "recommended_evaluations_per_run": recommended,
            "minimum_scale_feasible": bool(slowest and 60 * 5000 / slowest <= 1800),
            "total_elapsed": time.perf_counter() - started, "jit_used": False}
