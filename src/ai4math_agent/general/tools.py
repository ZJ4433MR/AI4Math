"""Extensible host-controlled tool registry. New problems do not require new plans."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

TOOL_SPECS = {
    "literature_search": {"purpose": "Find primary publication metadata/abstracts; no theorem or novelty certification", "arguments": {"query": "English query; arxiv native syntax e.g. all:Faulhaber", "provider": "arxiv|crossref", "limit": "1..5"}},
    "literature_read": {"purpose": "Retrieve one arXiv abstract and metadata, not the full paper", "arguments": {"arxiv_id": "e.g. 2401.01234"}},
    "python_experiment": {"purpose": "Write and run NEW algorithms, enumerate mathematical objects, discover patterns or seek counterexamples; output is empirical/unverified", "arguments": {"code": "Python program assigning JSON-serializable result; imports math,itertools,fractions,collections only. Numeric/container public operations, functions, loops, comprehensions. No files/network/introspection/eval/exec.", "max_operations": "1000..200000", "timeout_seconds": "1..12"}},
    "finite_check": {"purpose": "Independent exact rational checking of a FORMAL statement over finite assignments; cannot prove an infinite domain. Expressions support arithmetic, integer powers <=32, modulo %, Mod(a,b), gcd(a,b), isprime(n) returning 0/1, abs(x). Exact rationals use p/q, no decimal floats.", "arguments": {"variables": {"n": {"kind": "integer_range", "min": 1, "max": 100}}, "statement": {"lhs": "n**2", "relation": "eq|ne|lt|le|gt|ge", "rhs": "n"}, "quantifier": "forall|exists", "mode": "exhaustive|sample", "max_assignments": "1..50000", "samples": 100, "seed": 0}},
    "symbolic_check": {"purpose": "Check arbitrary polynomial/rational identity, with exact certificate and denominator exclusions; inequalities may be unsupported", "arguments": {"variables": {"x": "integer|rational|real|complex"}, "lhs": "(x+1)**2", "rhs": "x**2+2*x+1", "relation": "eq", "domain": {"exclude_zero": []}}},
    "induction_check": {"purpose": "Check base and polynomial recurrence for a NEW sum formula; certificate proves the stated formal sum for integers n>=start", "arguments": {"index": "n", "summation_index": "k", "start": 1, "summand": "k**3", "formula": "n**2*(n+1)**2/4", "parameters": {}, "domain": {"exclude_zero": []}}},
    "labs_profile": {"purpose": "LABS plugin: fresh full finite enumeration and independent Gray verification", "arguments": {"n": "2..16"}},
    "labs_search": {"purpose": "LABS plugin: budgeted candidate optimization and independent witness verification", "arguments": {"n": "2..127", "method": "random|fixed_tabu|skew|fixed_b|static_mix", "evaluations": "1..50000", "seed": "nonnegative integer", "b": "optional stratum imbalance"}},
    "labs_bound": {"purpose": "LABS plugin: checked lower-bound certificate", "arguments": {"n": "2..127", "b": "0..n with correct parity"}},
}


def _integer(args, name, low, high, default=None):
    value = args.get(name, default)
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer {low}..{high}")
    return value


def reservation(name, args):
    if name not in TOOL_SPECS:
        raise ValueError(f"unknown tool {name}")
    if name == "python_experiment":
        return _integer(args, "max_operations", 1000, 200000, 100000)
    if name == "finite_check":
        return _integer(args, "max_assignments", 1, 50000, 10000)
    if name == "labs_search":
        return _integer(args, "evaluations", 1, 50000)
    if name == "labs_profile":
        return 2 ** (_integer(args, "n", 2, 16) - 1)
    if name == "induction_check":
        return 2
    return 1


def math_dispatch(name, args):
    if name in {"finite_check", "symbolic_check", "induction_check"}:
        from .math_tools import math_tool
        return math_tool(name, args)
    if name == "labs_profile":
        from ai4math_agent.math.exact import exact_profile
        from ai4math_agent.verification.reference import verify_exact_profile
        p = exact_profile(_integer(args, "n", 2, 16), wall_seconds=8)
        verification = verify_exact_profile(p, exhaustive=True)
        return {"status": "finite_domain_verified" if p["complete"] and verification["valid"] else "incomplete", "profile": p, "verification": verification, "operations": p["visited"], "scope": "Only the specified LABS length"}
    if name == "labs_search":
        from ai4math_agent.search.engine import run_search
        from ai4math_agent.verification.reference import verify_sequence
        n = _integer(args, "n", 2, 127)
        method = args.get("method")
        if method not in {"random", "fixed_tabu", "skew", "fixed_b", "static_mix"}:
            raise ValueError("invalid LABS search method")
        result = run_search(n, method, _integer(args, "evaluations", 1, 50000), _integer(args, "seed", 0, 2**31-1), b=args.get("b"), wall_seconds=8)
        return {"status": "empirical", "best": result["best"], "verification": verify_sequence(result["best"]), "operations": result["evaluations"], "scope": "Best candidate within budget, no global optimality"}
    if name == "labs_bound":
        from ai4math_agent.math.bounds import lower_bound
        from ai4math_agent.verification.reference import check_bound
        n = _integer(args, "n", 2, 127)
        result = lower_bound(n, _integer(args, "b", 0, n))
        return {"status": "bound_certificate", "certificate": result, "verification": check_bound(result), "operations": 1}
    raise ValueError("not a mathematical tool")


def execute(name, args, output_dir, wall_limit=60):
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    if name == "python_experiment":
        from .experiment import run_experiment
        if not isinstance(args.get("code"), str):
            raise ValueError("code required")
        return run_experiment(args["code"], directory, timeout_seconds=min(wall_limit, _integer(args, "timeout_seconds", 1, 12, 10)), max_operations=reservation(name, args))
    if name in {"literature_search", "literature_read"}:
        from . import literature
        return getattr(literature, name)(args, directory, timeout=min(18, wall_limit))
    # A malformed or expensive symbolic expression cannot hang the host loop.
    payload = json.dumps({"name": name, "arguments": args})
    process = subprocess.Popen([sys.executable, "-m", "ai4math_agent.general.worker"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        stdout, stderr = process.communicate(payload, timeout=min(15, wall_limit))
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        return {"status": "tool_error", "error": "Mathematical tool exceeded session/tool time limit", "operations": reservation(name, args), "budget_accounting": "full reservation charged after timeout"}
    (directory / "stdout.json").write_text(stdout, encoding="utf-8")
    (directory / "stderr.txt").write_text(stderr[-3000:], encoding="utf-8")
    if process.returncode:
        raise ValueError("Mathematical worker failed: " + stderr[-1000:])
    if len(stdout) > 3000000:
        raise ValueError("Mathematical worker output limit exceeded")
    return json.loads(stdout)
