from ai4math_agent.math.bounds import lower_bound
from ai4math_agent.math.core import evaluate
from ai4math_agent.math.exact import exact_profile
from ai4math_agent.verification.claims import check_small_claim
from ai4math_agent.verification.reference import verify_exact_profile


def profile(n):
    p = exact_profile(n)
    p["verification"] = verify_exact_profile(p)
    return p


def claim(kind, n_min=4, n_max=4, quantifier="for_all_n", **params):
    return {"domain": {"n_min": n_min, "n_max": n_max}, "quantifier": quantifier,
            "predicate": {"kind": kind, **params}}


def test_balance_quantifier_distinction():
    p4, p6 = profile(4), profile(6)
    assert check_small_claim(claim("balanced_optimum_exists"), [p4])["status"] == "refuted"
    assert check_small_claim(claim("balanced_optimum_exists", 6, 6), [p6])["status"] == "finite_domain_verified"
    assert check_small_claim(claim("all_optima_balanced", 6, 6), [p6])["status"] == "refuted"
    assert check_small_claim(claim("balanced_optimum_exists", 4, 6, "exists_n"), [p4, p6])["status"] == "finite_domain_verified"
    assert check_small_claim(claim("balanced_optimum_exists", 4, 6, "for_all_n"), [p4, p6])["status"] == "refuted"
    assert check_small_claim(claim("all_optima_balanced", 4, 6, "exists_n"), [p4, p6])["status"] == "unresolved"


def test_missing_incomplete_or_tampered_profile_never_certifies_optima():
    p = exact_profile(6)
    assert check_small_claim(claim("balanced_optimum_exists", 6, 6), [p])["status"] == "unresolved"
    p["verification"] = verify_exact_profile(p)
    p["optimal_b"] = [0]
    assert check_small_claim(claim("all_optima_balanced", 6, 6), [p])["status"] == "unresolved"
    partial = exact_profile(6, max_states=2)
    partial["verification"] = verify_exact_profile(partial)
    assert check_small_claim(claim("all_optima_balanced", 6, 6), [partial])["status"] == "unresolved"


def test_threshold_asymmetry():
    w = evaluate([1, 1, 1, -1])
    assert check_small_claim(claim("profile_threshold", b=2, threshold=3, comparison="ge"), witnesses=[w])["status"] == "refuted"
    assert check_small_claim(claim("profile_threshold", b=2, threshold=3, comparison="le"), witnesses=[w])["status"] == "finite_domain_verified"
    # A failed heuristic search (only a poor witness) cannot disprove an upper bound.
    assert check_small_claim(claim("profile_threshold", b=0, threshold=2, comparison="le"), witnesses=[w])["status"] == "unresolved"
    assert check_small_claim(claim("profile_threshold", b=4, threshold=10, comparison="le"), certificates=[lower_bound(4, 4)])["status"] == "refuted"


def test_monotonicity_attainability_and_unsupported():
    p4, p6 = profile(4), profile(6)
    assert check_small_claim(claim("profile_monotone", comparison="le"), [p4])["status"] == "refuted"
    result = check_small_claim(claim("bound_attainable", 6, 6, b=4), [p6])
    assert result["status"] == "finite_domain_verified" and result["new_enumeration_states"] == 0
    assert check_small_claim(claim("bound_attainable", b=0), [p4])["status"] == "refuted"
    assert check_small_claim(claim("signed_sum_positive"), [p4])["status"] == "unsupported"
    assert check_small_claim(claim("profile_threshold", b=1, threshold=10, comparison="le"), [p4])["status"] == "unsupported"
    result = check_small_claim(claim("profile_monotone", 4, 6, quantifier="exists_n"), [p4])
    assert result["status"] == "unresolved" and not result["general_theorem"]
