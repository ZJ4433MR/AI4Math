import copy
import itertools

import numpy as np
import pytest

from ai4math_agent.math.bounds import lower_bound
from ai4math_agent.math.core import all_flip_deltas, batch_correlations, correlations, decode, encode, energy_delta, evaluate, flip_delta, pair_delta
from ai4math_agent.math.exact import exact_profile
from ai4math_agent.verification.reference import check_bound, evaluate_reference, relaxation_dp, verify_exact_profile, verify_sequence


def test_core_reference_and_all_single_flips():
    rng = np.random.default_rng(513)
    for n in [2, 3, 4, 13, 31, 127, 257]:
        for s in [np.ones(n, dtype=np.int64), (-1) ** np.arange(n), rng.choice([-1, 1], n)]:
            rec = evaluate(s)
            assert rec == evaluate_reference(s)
            assert verify_sequence(rec)["valid"]
            assert decode(encode(s), n) == list(s)
            C = correlations(s)
            all_d = all_flip_deltas(s)
            for j in range(n):
                t = s.copy()
                t[j] *= -1
                d = flip_delta(s, C, j)
                assert np.array_equal(d, all_d[j])
                new = evaluate_reference(t)
                assert new["C"] == (C + d).tolist()
                assert new["E"] - rec["E"] == energy_delta(C, d)


def test_pair_flips_and_signed_sum():
    rng = np.random.default_rng(31)
    for n in [2, 6, 13, 31]:
        s = rng.choice([-1, 1], n)
        C, old = correlations(s), evaluate_reference(s)
        for _ in range(50):
            i, j = rng.choice(n, 2, replace=False).tolist()
            d = pair_delta(s, C, i, j)
            t = s.copy()
            t[i] *= -1
            first = flip_delta(s, C, i)
            second = flip_delta(t, C + first, j)
            t[j] *= -1
            assert np.array_equal(d, first + second)
            new = evaluate_reference(t)
            assert new["C"] == (C + d).tolist()
            assert new["E"] - old["E"] == energy_delta(C, d)
            if s[i] != s[j]:
                assert sum(s) == sum(t)


def test_batch_and_no_int8_overflow():
    rows = [np.ones(300, dtype=np.int64), (-1) ** np.arange(300)]
    assert batch_correlations(rows).tolist() == [evaluate_reference(s)["C"] for s in rows]
    assert evaluate(rows[0])["C"][0] == 299


def test_invalid_symbols_and_tampered_evidence():
    for s in [[1], [0, 1], [True, 1], [1.0, -1.0]]:
        with pytest.raises(ValueError):
            evaluate(s)
        with pytest.raises(ValueError):
            evaluate_reference(s)
    witness = evaluate([1, 1, 1, -1])
    assert witness["C"] == [1, 0, -1]
    assert witness["E"] == 2 and witness["F"] == 4
    for field in ["hash", "E", "b", "encoding", "F_denominator"]:
        bad = copy.deepcopy(witness)
        bad[field] = "tampered"
        assert not verify_sequence(bad)["valid"]


def test_profiles_and_symmetry_counts():
    for n in [2, 4, 6, 13]:
        p = exact_profile(n)
        assert p["visited"] == 2 ** (n - 1)
        assert p["complete"] and p["exact"]
        assert verify_exact_profile(p)["valid"]
        g = {r["b"]: r["E"] for r in p["strata"]}
        if n == 4:
            assert g == {0: 6, 2: 2, 4: 14}
        if n == 6:
            assert g[0] == g[2] == g[4] == 7
        if n == 13:
            assert (g[1], g[3], g[5]) == (18, 14, 6)
    p = exact_profile(6)
    full = [evaluate_reference(s) for s in itertools.product([-1, 1], repeat=6)]
    counts = {str(b): sum(r["E"] == p["optimum_E"] and r["b"] == b for r in full) for b in p["optimal_b"]}
    assert p["optimal_counts_by_b"] == counts
    s = [1, 1, 1, 1]
    alternate = [((-1) ** i) * v for i, v in enumerate(s)]
    assert evaluate(s)["E"] == evaluate(alternate)["E"]
    assert evaluate(s)["b"] != evaluate(alternate)["b"]


def test_incomplete_profile_never_exact():
    p = exact_profile(10, max_states=40)
    assert not p["complete"] and not p["exact"]
    assert p["optimum_E"] is None and p["optimal_b"] == []
    assert verify_exact_profile(p)["valid"]
    assert not verify_exact_profile(p)["recomputed_complete"]
    p["complete"] = p["exact"] = True
    assert not verify_exact_profile(p)["valid"]


def test_heap_independent_dp_and_certificates():
    for n in range(2, 12):
        for b in range(n % 2, n + 1, 2):
            cert = lower_bound(n, b)
            assert check_bound(cert)["valid"]
            assert cert["L"] == relaxation_dp(n, b)
            assert cert["L"] >= cert["simple"]["energy_congruence_adjusted"]
    assert lower_bound(6, 4)["L"] == 7
    good = lower_bound(6, 4)
    bad = copy.deepcopy(good)
    bad["L"] += 4
    assert not check_bound(bad)["valid"]
    bad = copy.deepcopy(good)
    bad["c"][0] += 2
    assert not check_bound(bad)["valid"]
    # A feasible but suboptimal relaxation vector must fail exchange checking.
    bad = {"n": 4, "b": 2, "A": 0, "c": [3, -2, -1], "L": 14}
    assert not check_bound(bad)["valid"]
