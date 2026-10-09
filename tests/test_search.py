"""Budget, checkpoint and constraint checks using independent integer sums."""

import base64
import json
import zlib

import pytest

from ai4math_agent.search.engine import is_skew, release_restriction, restart, run_search


def naive(s):
    c = [sum(s[i] * s[i + k] for i in range(len(s) - k)) for k in range(1, len(s))]
    return c, sum(x * x for x in c)


def visited(result):
    n = result["checkpoint"]["n"]
    width = (n + 7) // 8
    raw = zlib.decompress(base64.b64decode(result["checkpoint"]["visited_zlib_base64"]))
    return [[-1 if int.from_bytes(raw[i:i + width], "little") & (1 << j) else 1 for j in range(n)]
            for i in range(0, len(raw), width)]


@pytest.mark.parametrize("method", ["random", "fixed_tabu", "skew", "fixed_b", "static_mix", "agent_policy"])
def test_counted_search_and_independent_recomputation(method):
    kwargs = {"b": 3} if method == "fixed_b" else {}
    if method == "agent_policy":
        kwargs["policy"] = {"skew_fraction": 0.3, "tabu_scale": 0.12, "restart_scale": 1.2, "perturb_bits": 2}
    result = run_search(9, method, 321, 123, **kwargs)
    assert result["evaluations"] == 321
    assert 1 <= result["unique_evaluations"] <= result["evaluations"]
    best = result["best"]
    assert naive(best["sequence"]) == (best["C"], best["E"])
    state = result["checkpoint"]["state"]
    assert naive(state["current"]["sequence"]) == (state["current"]["C"], state["current"]["E"])
    accounting = result["accounting"]
    assert sum(accounting[k] for k in ["initialization_evaluations", "neighborhood_evaluations", "random_evaluations", "perturbation_evaluations"]) == 321
    assert result["curve"][-1] == {"evaluations": 321, "E": best["E"]}
    assert all(a["E"] >= b["E"] for a, b in zip(result["curve"], result["curve"][1:]))
    json.dumps(result)  # No NumPy scalars or arrays leak into evidence.


def test_forbidden_neighbors_are_charged_and_partial_scan_preserves_current():
    initial = [1, 1, 1, -1, 1, -1, -1, 1]
    result = run_search(8, "fixed_tabu", 17, 31, initial=initial)
    assert result["accounting"]["initialization_evaluations"] == 1
    assert result["accounting"]["neighborhood_evaluations"] == 16
    assert result["accounting"]["forbidden_evaluations"] >= 1
    short = run_search(8, "fixed_tabu", 6, 31, initial=initial)
    assert short["termination_reason"] == "budget_truncated_neighborhood"
    assert short["checkpoint"]["state"]["current"]["sequence"] == initial
    candidate_energies = [naive(initial)[1]]
    for j in range(5):
        s = initial.copy()
        s[j] *= -1
        candidate_energies.append(naive(s)[1])
    assert short["best"]["E"] == min(candidate_energies)


def test_skew_all_scored_candidates_and_odd_lags_are_valid():
    result = run_search(13, "skew", 1001, 11)
    for sequence in visited(result):
        assert is_skew(sequence)
        c, _ = naive(sequence)
        assert all(c[k - 1] == 0 for k in range(1, 13, 2))


def test_fixed_b_all_candidates_signed_sum_and_no_first_symbol_fix():
    result = run_search(10, "fixed_b", 1001, 11, b=2)
    samples = visited(result)
    assert all(sum(s) == 2 for s in samples)
    assert {s[0] for s in samples} == {-1, 1}
    degenerate = run_search(5, "fixed_b", 100, 11, b=5)
    assert degenerate["evaluations"] == 1
    assert degenerate["termination_reason"] == "no_legal_neighbors"


def test_resume_restores_rng_tabu_and_visited_ledger():
    first = run_search(7, "fixed_tabu", 22, 42)
    resumed = run_search(7, "fixed_tabu", 501, 42, initial=json.loads(json.dumps(first["checkpoint"])))
    uninterrupted = run_search(7, "fixed_tabu", 501, 42)
    assert resumed["best"] == uninterrupted["best"]
    assert resumed["checkpoint"]["state"] == uninterrupted["checkpoint"]["state"]
    assert resumed["unique_evaluations"] == uninterrupted["unique_evaluations"]
    assert resumed["accounting"] == uninterrupted["accounting"]
    assert resumed["evaluations"] == 501


def test_release_and_restart_preserve_explicit_constraints():
    skew = run_search(11, "skew", 301, 7)
    released = release_restriction(skew["checkpoint"], 1, 8)
    current = skew["checkpoint"]["state"]["current"]["sequence"]
    assert released["best"]["sequence"] == current
    assert released["restriction"] == "unrestricted"
    assert released["evaluations"] == 1
    assert released["release"]["initialization_cost"] == 1
    restarted = restart(skew["checkpoint"], 71, 9)
    assert all(is_skew(s) for s in visited(restarted))
    fixed = run_search(10, "fixed_b", 101, 7, b=2)
    restarted_b = restart(fixed["checkpoint"], 71, 9)
    assert all(sum(s) == 2 for s in visited(restarted_b))


def test_static_release_checkpoint_sequence_identity_and_seed_determinism():
    result = run_search(9, "static_mix", 401, 11)
    release = result["checkpoint"]["release_checkpoints"][0]
    assert release["before"]["current"] == release["after"]["current"]
    assert release["before"]["restriction"] == "skew"
    assert release["after"]["restriction"] == "unrestricted"
    other = run_search(9, "static_mix", 401, 11)
    assert result["best"] == other["best"]
    assert result["curve"] == other["curve"]


@pytest.mark.parametrize("kwargs", [
    {"method": "skew", "n": 8},
    {"method": "fixed_b", "b": 2},
    {"method": "fixed_b", "b": -1},
    {"method": "agent_policy"},
    {"policy": {"python_code": "forbidden"}},
    {"policy": {"tabu_scale": 0}},
    {"initial": [1] * 9, "method": "skew"},
])
def test_reject_unsupported_or_incompatible_arguments(kwargs):
    args = {"n": 9, "method": "fixed_tabu", "evaluations": 101, "seed": 11}
    args.update(kwargs)
    with pytest.raises(ValueError):
        run_search(**args)
