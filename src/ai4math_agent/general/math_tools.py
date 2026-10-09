"""Restricted exact mathematical certificates for a general research agent.

Expressions are parsed as Python ASTs, then interpreted using Fraction or
constructed from SymPy objects. This module never evaluates source, imports
user names, calls sympify, or accepts attributes/subscripts. Universal claims
outside the implemented certificates remain proof candidates.
"""

from __future__ import annotations

import ast
import math
import random
import re
from fractions import Fraction

import sympy as sp

STATUSES = {"finite_domain_verified", "refuted", "empirical_supported", "unresolved",
            "symbolic_identity_verified", "induction_verified", "invalid_certificate",
            "proof_candidate", "unsupported", "invalid_input"}
_DOMAINS = {"integer", "rational", "real", "complex"}
_FUNCTIONS = {"Mod", "gcd", "isprime", "abs", "Abs"}
_RELATIONS = {"eq", "ne", "lt", "le", "gt", "ge"}


class MathInputError(ValueError):
    pass


class UnsupportedMath(ValueError):
    pass


def _keys(data, allowed, required=()):
    if not isinstance(data, dict) or set(data) - set(allowed) or set(required) - set(data):
        raise MathInputError("unknown or missing input fields")


def _name(name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", name) or "__" in name or name in _FUNCTIONS:
        raise MathInputError("variable names must be simple identifiers without reserved names")
    return name


def _int(value, name, low=None, high=None):
    if type(value) is not int or (low is not None and value < low) or (high is not None and value > high):
        raise MathInputError(f"invalid integer {name}")
    return value


def _fraction(value):
    if type(value) is int:
        result = Fraction(value)
    elif isinstance(value, str) and re.fullmatch(r"[+-]?\d+(?:/[+-]?\d+)?", value):
        try:
            result = Fraction(value)
        except (ValueError, ZeroDivisionError) as exc:
            raise MathInputError("invalid rational value") from exc
    else:
        raise MathInputError("exact values must be integers or rational strings, not floats")
    if result.numerator.bit_length() > 128 or result.denominator.bit_length() > 128:
        raise MathInputError("rational input exceeds size limit")
    return result


def _render(value):
    if isinstance(value, Fraction):
        return value.numerator if value.denominator == 1 else f"{value.numerator}/{value.denominator}"
    return value


def _literal_integer(node):
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        result = _literal_integer(node.operand)
        return -result if isinstance(node.op, ast.USub) else result
    raise UnsupportedMath("powers require a literal integer exponent")


class _Expression:
    def __init__(self, source, names):
        if not isinstance(source, str) or not source or len(source) > 2000:
            raise MathInputError("expression must be a string with at most 2000 characters")
        self.source = source
        try:
            self.tree = ast.parse(source, mode="eval").body
        except (SyntaxError, RecursionError) as exc:
            raise MathInputError("invalid restricted expression syntax") from exc
        nodes = list(ast.walk(self.tree))
        if len(nodes) > 400:
            raise MathInputError("expression exceeds AST size limit")
        self.names = set(names)
        self._validate(self.tree)

    def _validate(self, node, depth=0):
        if depth > 40:
            raise MathInputError("expression exceeds depth limit")
        if isinstance(node, ast.Constant):
            if type(node.value) is not int or abs(node.value).bit_length() > 128:
                raise UnsupportedMath("only bounded integer literals are supported; write fractions as p/q")
        elif isinstance(node, ast.Name):
            if node.id not in self.names:
                raise MathInputError(f"undeclared variable {node.id}")
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            self._validate(node.operand, depth + 1)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod)):
            self._validate(node.left, depth + 1)
            self._validate(node.right, depth + 1)
            if isinstance(node.op, ast.Pow) and abs(_literal_integer(node.right)) > 32:
                raise MathInputError("absolute exponent must be at most 32")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCTIONS and not node.keywords:
            count = len(node.args)
            if ((node.func.id in ("isprime", "abs", "Abs") and count != 1)
                    or (node.func.id == "Mod" and count != 2) or (node.func.id == "gcd" and not 2 <= count <= 12)):
                raise MathInputError("invalid whitelisted function arity")
            for argument in node.args:
                self._validate(argument, depth + 1)
        else:
            raise UnsupportedMath("AST operation is not allowed")

    def numeric(self, assignment):
        def integer(v):
            if v.denominator != 1:
                raise MathInputError("number-theory function arguments must be integers")
            return v.numerator

        def visit(node):
            if isinstance(node, ast.Constant):
                out = Fraction(node.value)
            elif isinstance(node, ast.Name):
                out = assignment[node.id]
            elif isinstance(node, ast.UnaryOp):
                out = visit(node.operand)
                if isinstance(node.op, ast.USub):
                    out = -out
            elif isinstance(node, ast.BinOp):
                left, right = visit(node.left), visit(node.right)
                if isinstance(node.op, ast.Add):
                    out = left + right
                elif isinstance(node.op, ast.Sub):
                    out = left - right
                elif isinstance(node.op, ast.Mult):
                    out = left * right
                elif isinstance(node.op, ast.Div):
                    out = left / right
                elif isinstance(node.op, ast.Pow):
                    out = left ** _literal_integer(node.right)
                else:
                    out = Fraction(integer(left) % integer(right))
            else:
                values = [visit(v) for v in node.args]
                fn = node.func.id
                if fn in ("abs", "Abs"):
                    out = abs(values[0])
                elif fn == "gcd":
                    out = Fraction(math.gcd(*(integer(v) for v in values)))
                elif fn == "Mod":
                    out = Fraction(integer(values[0]) % integer(values[1]))
                else:
                    v = integer(values[0])
                    if abs(v) > 10**9:
                        raise MathInputError("isprime exact trial division supports |n|<=10**9")
                    prime = v >= 2 and (v == 2 or v % 2 != 0)
                    if prime and v > 2:
                        for d in range(3, math.isqrt(v) + 1, 2):
                            if v % d == 0:
                                prime = False
                                break
                    out = Fraction(int(prime))
            if out.numerator.bit_length() > 4096 or out.denominator.bit_length() > 4096:
                raise MathInputError("intermediate rational exceeds size limit")
            return out
        return visit(self.tree)

    def symbolic(self, symbols):
        self._symbolic_resource_check()
        denominators = []
        def visit(node):
            if isinstance(node, ast.Constant):
                return sp.Integer(node.value)
            if isinstance(node, ast.Name):
                return symbols[node.id]
            if isinstance(node, ast.UnaryOp):
                value = visit(node.operand)
                return -value if isinstance(node.op, ast.USub) else value
            if isinstance(node, ast.Call) or isinstance(node.op, ast.Mod):
                raise UnsupportedMath("symbolic certificate covers polynomial/rational expressions, not number-theory functions")
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                return sp.Add(left, right, evaluate=False)
            if isinstance(node.op, ast.Sub):
                return sp.Add(left, -right, evaluate=False)
            if isinstance(node.op, ast.Mult):
                return sp.Mul(left, right, evaluate=False)
            if isinstance(node.op, ast.Div):
                denominators.append(right)
                return sp.Mul(left, sp.Pow(right, -1, evaluate=False), evaluate=False)
            power = _literal_integer(node.right)
            if power < 0:
                denominators.append(left)
            return sp.Pow(left, power, evaluate=False)
        return visit(self.tree), denominators

    def _symbolic_resource_check(self):
        """Conservative rational polynomial bounds before constructing CAS data.

        Each tuple tracks degree, expanded term count and coefficient bit-size
        separately for numerator and denominator. Bounds can overestimate
        cancellation; rejecting such an input never establishes a theorem.
        """
        def check(data):
            if max(data[0], data[3]) > 256 or max(data[1], data[4]) > 10000 or max(data[2], data[5]) > 4096:
                raise MathInputError("symbolic expression exceeds degree/expanded-terms/coefficient-size limits")
            return data

        def visit(node):
            if isinstance(node, ast.Constant):
                return (0, 1, max(1, abs(node.value).bit_length()), 0, 1, 1)
            if isinstance(node, ast.Name):
                return (1, 1, 1, 0, 1, 1)
            if isinstance(node, ast.UnaryOp):
                return visit(node.operand)
            if isinstance(node, ast.Call) or isinstance(node.op, ast.Mod):
                raise UnsupportedMath("symbolic certificate covers polynomial/rational expressions, not number-theory functions")
            a = visit(node.left)
            if isinstance(node.op, ast.Pow):
                power = _literal_integer(node.right)
                if power == 0:
                    return (0, 1, 1, 0, 1, 1)
                if power < 0:
                    a, power = a[3:] + a[:3], -power
                num_terms = math.comb(a[1] + power - 1, power)
                den_terms = math.comb(a[4] + power - 1, power)
                return check((a[0] * power, num_terms, a[2] * power + num_terms.bit_length(),
                              a[3] * power, den_terms, a[5] * power + den_terms.bit_length()))
            b = visit(node.right)
            if isinstance(node.op, (ast.Add, ast.Sub)):
                return check((max(a[0] + b[3], b[0] + a[3]), a[1] * b[4] + b[1] * a[4],
                              max(a[2] + b[5], b[2] + a[5]) + 1,
                              a[3] + b[3], a[4] * b[4], a[5] + b[5]))
            if isinstance(node.op, ast.Div):
                b = b[3:] + b[:3]
            return check((a[0] + b[0], a[1] * b[1], a[2] + b[2],
                          a[3] + b[3], a[4] * b[4], a[5] + b[5]))
        visit(self.tree)


def _statement(statement, names):
    _keys(statement, {"lhs", "rhs", "relation"}, {"lhs", "rhs", "relation"})
    if statement["relation"] not in _RELATIONS:
        raise MathInputError("unsupported finite relation")
    return _Expression(statement["lhs"], names), _Expression(statement["rhs"], names)


def _relation(left, right, relation):
    return {"eq": lambda: left == right, "ne": lambda: left != right,
            "lt": lambda: left < right, "le": lambda: left <= right,
            "gt": lambda: left > right, "ge": lambda: left >= right}[relation]()


def _result(name, status, scope, evidence=None, valid=True, method=None, **other):
    return {"tool": name, "status": status, "scope": scope,
            "verification": {"valid": valid, "method": method, "proves_claim": status in {"finite_domain_verified", "symbolic_identity_verified", "induction_verified"}},
            "evidence": evidence or {}, "operations": other.get("operations_checked", 0), **other}


def finite_check(args):
    _keys(args, {"variables", "statement", "quantifier", "mode", "max_assignments", "samples", "seed"}, {"variables", "statement", "quantifier"})
    variables = args["variables"]
    if not isinstance(variables, dict) or len(variables) > 12:
        raise MathInputError("variables must contain at most 12 finite domains")
    domains, normalized = [], {}
    for name, spec in variables.items():
        _name(name)
        if not isinstance(spec, dict):
            raise MathInputError("invalid finite variable domain")
        if spec.get("kind") == "integer_range":
            _keys(spec, {"kind", "min", "max"}, {"kind", "min", "max"})
            lo, hi = _int(spec["min"], "min", -10**9, 10**9), _int(spec["max"], "max", -10**9, 10**9)
            if lo > hi:
                raise MathInputError("empty finite domains are rejected")
            values = range(lo, hi + 1)
            normalized[name] = dict(spec)
        elif spec.get("kind") == "finite_set":
            _keys(spec, {"kind", "values"}, {"kind", "values"})
            if not isinstance(spec["values"], list) or not 1 <= len(spec["values"]) <= 10000:
                raise MathInputError("finite_set requires 1..10000 exact values")
            values = list(dict.fromkeys(_fraction(v) for v in spec["values"]))
            normalized[name] = {"kind": "finite_set", "values": [_render(v) for v in values]}
        else:
            raise MathInputError("finite domains require integer_range or finite_set")
        domains.append(values)
    left, right = _statement(args["statement"], variables)
    quantifier = args["quantifier"]
    mode = args.get("mode", "exhaustive")
    if quantifier not in ("forall", "exists") or mode not in ("exhaustive", "sample"):
        raise MathInputError("quantifier requires forall/exists; mode requires exhaustive/sample")
    cap = _int(args.get("max_assignments", 10000), "max_assignments", 1, 100000)
    samples = _int(args.get("samples", 100), "samples", 1, 100000)
    seed = _int(args.get("seed", 0), "seed", 0, 2**63 - 1)
    total = math.prod(len(v) for v in domains)
    scope = {"statement": args["statement"], "variables": normalized, "quantifier": quantifier,
             "mode": mode, "general_theorem": False, "total_assignments": total}
    names = list(variables)
    rng, checked, decisive = random.Random(seed), 0, None
    if mode == "exhaustive":
        def decode_assignment(rank):
            # itertools.product would first materialize every input range.
            # Mixed-radix decoding touches only requested assignments.
            values = [None] * len(domains)
            for i in range(len(domains) - 1, -1, -1):
                rank, digit = divmod(rank, len(domains[i]))
                values[i] = domains[i][digit]
            return tuple(values)
        assignments = (decode_assignment(rank) for rank in range(min(cap, total)))
    else:
        assignments = (tuple(v[rng.randrange(len(v))] for v in domains) for _ in range(min(cap, samples)))
    for values in assignments:
        assignment = {name: Fraction(v) for name, v in zip(names, values)}
        try:
            lhs, rhs = left.numeric(assignment), right.numeric(assignment)
        except (ZeroDivisionError, MathInputError) as exc:
            return _result("finite_check", "invalid_input", scope,
                           {"reason": str(exc), "undefined_assignment": {k: _render(v) for k, v in assignment.items()}},
                           valid=False, method="independent exact Fraction interpreter", operations_checked=checked)
        checked += 1
        truth = _relation(lhs, rhs, args["statement"]["relation"])
        if (quantifier == "forall" and not truth) or (quantifier == "exists" and truth):
            decisive = {"assignment": {k: _render(v) for k, v in assignment.items()},
                        "lhs": _render(lhs), "rhs": _render(rhs), "relation_holds": truth}
            break
    complete = mode == "exhaustive" and checked == total
    if decisive:
        status = "refuted" if quantifier == "forall" else "finite_domain_verified"
    elif complete:
        status = "finite_domain_verified" if quantifier == "forall" else "refuted"
    elif mode == "sample" and checked == min(cap, samples) and quantifier == "forall":
        status = "empirical_supported"
    else:
        status = "unresolved"
    return _result("finite_check", status, scope,
                   {"decisive_witness": decisive, "complete": complete,
                    "basis": "complete finite coverage" if complete else ("verified witness" if decisive else "partial tested assignments"),
                    "sampling_with_replacement": mode == "sample", "seed": seed},
                   method="independent exact Fraction interpreter", operations_checked=checked)


def _symbols(variables):
    if not isinstance(variables, dict) or len(variables) > 12:
        raise MathInputError("symbolic variables must be an explicit dictionary with at most 12 names")
    result = {}
    for name, domain in variables.items():
        _name(name)
        if domain not in _DOMAINS:
            raise MathInputError("symbol domains require integer/rational/real/complex")
        result[name] = sp.Symbol(name, **{domain: True})
    return result


def _factors(expression, symbols):
    expression = sp.cancel(expression)
    numerator, denominator = sp.fraction(expression)
    if denominator.free_symbols:
        raise MathInputError("domain exclusions must be polynomial expressions")
    if numerator == 0:
        raise MathInputError("zero denominator or exclusion creates an undefined or empty domain")
    if not numerator.free_symbols:
        return set()
    variables = list(symbols.values())
    try:
        _, factors = sp.factor_list(numerator, *variables)
        return {sp.sstr(sp.Poly(factor, *variables).monic().as_expr()) for factor, _ in factors}
    except sp.PolynomialError as exc:
        raise UnsupportedMath("nonpolynomial denominator or domain exclusion") from exc


def _denominator_scope(domain, denominators, symbols):
    _keys(domain, {"exclude_zero"}, {"exclude_zero"})
    exclusions = domain["exclude_zero"]
    if not isinstance(exclusions, list) or len(exclusions) > 32:
        raise MathInputError("domain.exclude_zero must be a list of at most 32 polynomial expressions")
    declared = set()
    for expr in exclusions:
        value, hidden = _Expression(expr, symbols).symbolic(symbols)
        if any(sp.cancel(v).free_symbols for v in hidden):
            raise MathInputError("domain exclusions cannot contain variable denominators")
        declared.update(_factors(value, symbols))
    required = set()
    for denom in denominators:
        numerator, _ = sp.fraction(sp.cancel(denom))
        required.update(_factors(numerator, symbols))
    return {"exclude_zero": exclusions, "required_nonzero_factors": sorted(required),
            "missing_nonzero_factors": sorted(required - declared)}


def symbolic_check(args):
    _keys(args, {"variables", "lhs", "rhs", "relation", "domain"}, {"variables", "lhs", "rhs", "domain"})
    symbols = _symbols(args["variables"])
    scope = {"variables": args["variables"], "lhs": args["lhs"], "rhs": args["rhs"],
             "relation": args.get("relation", "eq"), "domain": args["domain"], "general_theorem": False}
    if scope["relation"] != "eq":
        return _result("symbolic_check", "proof_candidate", scope,
                       {"reason": "universal inequality and nonidentity certificates are unsupported"}, valid=False,
                       method="restricted rational-function identity checker", operations_checked=0)
    lhs, d1 = _Expression(args["lhs"], symbols).symbolic(symbols)
    rhs, d2 = _Expression(args["rhs"], symbols).symbolic(symbols)
    domain = _denominator_scope(args["domain"], d1 + d2, symbols)
    difference = sp.cancel(lhs - rhs)
    numerator, denominator = sp.fraction(difference)
    evidence = {"normalized_difference_numerator": sp.sstr(numerator),
                "normalized_difference_denominator": sp.sstr(denominator), "domain_check": domain}
    if domain["missing_nonzero_factors"]:
        evidence["reason"] = "declared domain does not guarantee all original denominators are nonzero"
        return _result("symbolic_check", "invalid_certificate", scope, evidence, valid=False,
                       method="exact SymPy rational-function normalization", operations_checked=1)
    if numerator != 0:
        evidence["reason"] = "rational-function residual is nonzero; no identity certified"
        return _result("symbolic_check", "invalid_certificate", scope, evidence, valid=False,
                       method="exact SymPy rational-function normalization", operations_checked=1)
    scope["general_theorem"] = True
    scope["theorem_scope"] = "expression identity on the declared scalar domains where all exclusions are nonzero"
    return _result("symbolic_check", "symbolic_identity_verified", scope, evidence,
                   method="exact SymPy rational-function normalization", operations_checked=1)


def induction_check(args):
    _keys(args, {"index", "summation_index", "start", "summand", "formula", "parameters", "domain"},
          {"index", "summation_index", "start", "summand", "formula", "domain"})
    index, summation = _name(args["index"]), _name(args["summation_index"])
    if index == summation:
        raise MathInputError("index and summation_index must be distinct")
    start = _int(args["start"], "start", -10**9, 10**9)
    parameters = args.get("parameters", {})
    if index in parameters or summation in parameters:
        raise MathInputError("parameters must not shadow induction or summation indices")
    symbols = _symbols({**parameters, index: "integer", summation: "integer"})
    summand_parser = _Expression(args["summand"], {**parameters, summation: "integer"})
    formula_parser = _Expression(args["formula"], {**parameters, index: "integer"})
    summand, ds = summand_parser.symbolic(symbols)
    formula, df = formula_parser.symbolic(symbols)
    n, k = symbols[index], symbols[summation]
    scope = {"statement": f"sum({args['summand']}, {summation}={start}..{index}) = {args['formula']}",
             "index": index, "index_domain": {"kind": "integer", "min": start},
             "parameters": parameters, "domain": args["domain"], "general_theorem": False}
    # A polynomial in the induction index permits every successive induction
    # step. Conditional exclusions depending on n could leave holes, so this
    # certificate intentionally rejects such rational-index formulations.
    normalized_summand, normalized_formula = sp.cancel(summand), sp.cancel(formula)
    if (sp.denom(normalized_summand).has(k) or sp.denom(normalized_formula).has(n)
            or any(value.has(k, n) for value in ds + df)):
        return _result("induction_check", "proof_candidate", scope,
                       {"reason": "certificate requires polynomial summand and formula in the indices; rational index denominators need a separate domain proof"},
                       valid=False, method="polynomial-sum induction certificate", operations_checked=0)
    try:
        sp.Poly(normalized_summand, k)
        sp.Poly(normalized_formula, n)
    except sp.PolynomialError as exc:
        raise UnsupportedMath("summand and formula must be polynomials in their respective integer indices") from exc
    domain = _denominator_scope(args["domain"], ds + df, symbols)
    for exclusion in args["domain"]["exclude_zero"]:
        value, _ = _Expression(exclusion, symbols).symbolic(symbols)
        if value.has(n, k):
            return _result("induction_check", "proof_candidate", scope,
                           {"reason": "index-dependent exclusions do not establish a consecutive induction domain"},
                           valid=False, method="polynomial-sum induction certificate", operations_checked=0)
    base = sp.cancel(formula.subs(n, start) - summand.subs(k, start))
    step = sp.cancel(formula.subs(n, n + 1) - formula - summand.subs(k, n + 1))
    base_num, base_den = sp.fraction(base)
    step_num, step_den = sp.fraction(step)
    evidence = {"base_index": start, "base_residual_numerator": sp.sstr(base_num),
                "base_residual_denominator": sp.sstr(base_den),
                "step_residual_numerator": sp.sstr(step_num), "step_residual_denominator": sp.sstr(step_den),
                "domain_check": domain,
                "proof_rule": "base at start plus S(n+1)-S(n)=summand(n+1) proves every integer n>=start by induction"}
    if domain["missing_nonzero_factors"] or base_num != 0 or step_num != 0:
        evidence["reason"] = "base, recurrence, or denominator-domain condition failed"
        return _result("induction_check", "invalid_certificate", scope, evidence, valid=False,
                       method="exact polynomial base and induction-step normalization", operations_checked=2)
    scope["general_theorem"] = True
    return _result("induction_check", "induction_verified", scope, evidence,
                   method="exact polynomial base and induction-step normalization", operations_checked=2)


def math_tool(name, args):
    """Dispatch only registered mathematical operations; return honest failures."""
    functions = {"finite_check": finite_check, "symbolic_check": symbolic_check, "induction_check": induction_check}
    if name not in functions:
        return _result(name, "unsupported", {"general_theorem": False}, {"reason": "unregistered mathematical tool"}, valid=False, operations_checked=0)
    try:
        return functions[name](args)
    except UnsupportedMath as exc:
        status = "proof_candidate" if name in {"symbolic_check", "induction_check"} else "unsupported"
        return _result(name, status, {"input": args, "general_theorem": False}, {"reason": str(exc)}, valid=False, operations_checked=0)
    except (MathInputError, ZeroDivisionError, TypeError, KeyError, RecursionError, sp.PolynomialError) as exc:
        return _result(name, "invalid_input", {"input": args, "general_theorem": False}, {"reason": str(exc)}, valid=False, operations_checked=0)
