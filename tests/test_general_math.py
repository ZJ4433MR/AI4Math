import pytest

from ai4math_agent.general.math_tools import math_tool


def finite(lhs, rhs, relation="eq", quantifier="forall", **kwargs):
    return {"variables": {"n": {"kind": "integer_range", "min": 0, "max": 20}},
            "statement": {"lhs": lhs, "rhs": rhs, "relation": relation},
            "quantifier": quantifier, **kwargs}


def symbolic(lhs, rhs, **kwargs):
    return {"variables": {"x": "real"}, "lhs": lhs, "rhs": rhs,
            "domain": {"exclude_zero": []}, **kwargs}


def induction(summand, formula, **kwargs):
    return {"index": "n", "summation_index": "k", "start": 1,
            "summand": summand, "formula": formula,
            "domain": {"exclude_zero": []}, **kwargs}


def test_finite_exact_counterexample_and_complete_scope():
    result = math_tool("finite_check", finite("n*(n+1)", "2*Mod(n*(n+1)/2, 1000)"))
    assert result["status"] == "finite_domain_verified"
    assert result["operations_checked"] == 21 and result["evidence"]["complete"]
    assert not result["scope"]["general_theorem"]
    failed = math_tool("finite_check", finite("isprime(n**2+n+41)", "1"))
    assert failed["status"] == "finite_domain_verified"  # Explicit finite interval only.
    args = finite("isprime(n**2+n+41)", "1")
    args["variables"]["n"]["max"] = 50
    failed = math_tool("finite_check", args)
    assert failed["status"] == "refuted"
    assert failed["evidence"]["decisive_witness"]["assignment"] == {"n": 40}
    assert failed["evidence"]["decisive_witness"]["lhs"] == 0


def test_sampling_truncation_and_existential_absence():
    sample = math_tool("finite_check", finite("n*n", "0", "ge", mode="sample", samples=5, seed=31))
    assert sample["status"] == "empirical_supported" and not sample["evidence"]["complete"]
    truncated = math_tool("finite_check", finite("n*n", "0", "ge", max_assignments=3))
    assert truncated["status"] == "unresolved" and truncated["operations_checked"] == 3
    exists = math_tool("finite_check", finite("n*n", "9", quantifier="exists"))
    assert exists["status"] == "finite_domain_verified" and exists["evidence"]["decisive_witness"]["assignment"] == {"n": 3}
    absent = math_tool("finite_check", finite("n*n", "-1", quantifier="exists"))
    assert absent["status"] == "refuted" and absent["evidence"]["complete"]
    absent_sample = math_tool("finite_check", finite("n*n", "-1", quantifier="exists", mode="sample", samples=5))
    assert absent_sample["status"] == "unresolved"


def test_huge_ranges_are_lazy_and_symbolic_expansion_is_bounded():
    args = finite("n", "n", max_assignments=2)
    args["variables"]["n"] = {"kind": "integer_range", "min": -10**9, "max": 10**9}
    result = math_tool("finite_check", args)
    assert result["status"] == "unresolved" and result["operations"] == 2
    assert result["scope"]["total_assignments"] == 2000000001
    args["wall_seconds"] = 1
    assert math_tool("finite_check", args)["status"] == "invalid_input"
    for expression in ["(x**32)**32", "((((2**32)**32)**32)**32)**32", "((x+1)**32+1)**32"]:
        result = math_tool("symbolic_check", symbolic(expression, "0"))
        assert result["status"] == "invalid_input" and result["operations"] == 0


def test_rational_finite_sets_and_number_theory():
    args = {"variables": {"x": {"kind": "finite_set", "values": ["1/2", "2/3", 1]}},
            "statement": {"lhs": "x/x", "rhs": "1", "relation": "eq"}, "quantifier": "forall"}
    assert math_tool("finite_check", args)["status"] == "finite_domain_verified"
    assert math_tool("finite_check", finite("gcd(n,n+1)", "1"))["status"] == "finite_domain_verified"
    assert math_tool("finite_check", finite("Mod(n**2,2)", "Mod(n,2)"))["status"] == "finite_domain_verified"
    assert math_tool("finite_check", finite("1/n", "1/n"))["status"] == "invalid_input"


@pytest.mark.parametrize("source", ["__import__('os').system('echo unsafe')", "x.__class__", "[x for x in range(3)]", "lambda: 1", "open('secret')", "x[0]", "2**99999"])
def test_restricted_ast_rejects_arbitrary_code(source):
    result = math_tool("symbolic_check", symbolic(source, "1"))
    assert result["status"] in {"invalid_input", "proof_candidate"}
    assert not result["verification"]["valid"]


def test_symbolic_identity_requires_original_denominator_domain():
    result = math_tool("symbolic_check", symbolic("(x+1)**2", "x**2+2*x+1"))
    assert result["status"] == "symbolic_identity_verified" and result["scope"]["general_theorem"]
    removable = math_tool("symbolic_check", symbolic("x/x", "1"))
    assert removable["status"] == "invalid_certificate"
    assert removable["evidence"]["domain_check"]["missing_nonzero_factors"] == ["x"]
    valid = math_tool("symbolic_check", symbolic("(x**2-1)/(x-1)", "x+1", domain={"exclude_zero": ["x-1"]}))
    assert valid["status"] == "symbolic_identity_verified"
    false = math_tool("symbolic_check", symbolic("(x+1)**2", "x**2+1"))
    assert false["status"] == "invalid_certificate" and not false["verification"]["valid"]
    inequality = math_tool("symbolic_check", symbolic("x**2", "0", relation="ge"))
    assert inequality["status"] == "proof_candidate" and not inequality["verification"]["proves_claim"]


def test_multivariable_denominator_factors_and_empty_domains():
    args = {"variables": {"x": "rational", "y": "integer"}, "lhs": "x*y/(x*y)", "rhs": "1", "domain": {"exclude_zero": ["x", "y"]}}
    assert math_tool("symbolic_check", args)["status"] == "symbolic_identity_verified"
    args["domain"] = {"exclude_zero": ["0"]}
    assert math_tool("symbolic_check", args)["status"] == "invalid_input"


def test_induction_proves_base_and_step_for_general_polynomial_sums():
    for summand, formula in [("k", "n*(n+1)/2"), ("k**2", "n*(n+1)*(2*n+1)/6"), ("k**3", "n**2*(n+1)**2/4")]:
        result = math_tool("induction_check", induction(summand, formula))
        assert result["status"] == "induction_verified"
        assert result["evidence"]["base_residual_numerator"] == "0"
        assert result["evidence"]["step_residual_numerator"] == "0"
    param = math_tool("induction_check", induction("a*k+b", "a*n*(n+1)/2+b*n", parameters={"a": "real", "b": "rational"}))
    assert param["status"] == "induction_verified"
    shifted = math_tool("induction_check", induction("k", "n*(n+1)/2-3", start=3))
    assert shifted["status"] == "induction_verified"


def test_induction_rejects_wrong_base_wrong_step_and_domain_holes():
    wrong_base = math_tool("induction_check", induction("k", "n*(n+1)/2+1"))
    assert wrong_base["status"] == "invalid_certificate"
    assert wrong_base["evidence"]["base_residual_numerator"] != "0"
    assert wrong_base["evidence"]["step_residual_numerator"] == "0"
    wrong_step = math_tool("induction_check", induction("k", "n**2"))
    assert wrong_step["status"] == "invalid_certificate"
    assert wrong_step["evidence"]["base_residual_numerator"] == "0"
    assert wrong_step["evidence"]["step_residual_numerator"] != "0"
    telescope = math_tool("induction_check", induction("1/(k*(k+1))", "n/(n+1)"))
    assert telescope["status"] == "proof_candidate"
    hole = math_tool("induction_check", induction("k", "n*(n+1)/2", domain={"exclude_zero": ["n-2"]}))
    assert hole["status"] == "proof_candidate"
    rational_param = math_tool("induction_check", induction("k/a", "n*(n+1)/(2*a)", parameters={"a": "real"}, domain={"exclude_zero": ["a"]}))
    assert rational_param["status"] == "induction_verified"
