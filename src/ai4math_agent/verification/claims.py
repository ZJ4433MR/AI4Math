"""Small, controlled mathematical predicates; never executes model code.

Supported flat predicate kinds: balanced_optimum_exists, all_optima_balanced,
profile_monotone, bound_attainable, profile_threshold. The only length
quantifiers are for_all_n and exists_n. All conclusions explicitly retain the
finite domain. Unknown/missing evidence cannot become a proof by absence.
"""

from __future__ import annotations

from .reference import check_bound, evaluate_reference, profile_digest, verify_sequence


KINDS = {"balanced_optimum_exists", "all_optima_balanced", "profile_monotone", "bound_attainable", "profile_threshold"}


def _profiles_map(profiles) -> dict:
    if profiles is None:
        return {}
    if isinstance(profiles, dict) and "n" in profiles:
        return {profiles["n"]: profiles}
    if isinstance(profiles, dict):
        return {int(k): v for k, v in profiles.items()}
    return {p["n"]: p for p in profiles}


def _trusted(profile: dict | None) -> bool:
    if not profile or profile.get("complete") is not True or profile.get("exact") is not True:
        return False
    verification = profile.get("verification", {})
    return (verification.get("valid") is True and verification.get("recomputed_complete") is True
            and verification.get("profile_hash") == profile_digest(profile))


def check_small_claim(claim: dict, profiles=None, witnesses=None, certificates=None, max_n: int = 22) -> dict:
    """Check finite claims from already-produced evidence without enumeration.

    An annotated exact profile is accepted only if its independent verifier's
    hash still binds it. New heap bounds may be computed and independently
    checked for bound-attainability predicates; that cost is reported. No new
    sequence is sampled or evaluated except supplied-witness verification.
    """
    unsupported = lambda reason: {"status": "unsupported", "reason": reason, "checks": [], "general_theorem": False}
    try:
        domain = claim["domain"]
        n_min, n_max = domain["n_min"], domain["n_max"]
        if any(isinstance(x, bool) or not isinstance(x, int) for x in (n_min, n_max)) or not 2 <= n_min <= n_max <= max_n:
            return unsupported(f"require explicit 2 <= n_min <= n_max <= {max_n}")
        quantifier = claim.get("quantifier", "for_all_n")
        quantifier = {"for_all_lengths": "for_all_n", "exists_length": "exists_n"}.get(quantifier, quantifier)
        if quantifier not in ("for_all_n", "exists_n"):
            return unsupported("unsupported quantifier")
        predicate = claim["predicate"]
        kind = predicate["kind"]
        params = dict(predicate.get("parameters", {}))
        params.update({k: v for k, v in predicate.items() if k not in ("kind", "parameters")})
        if kind == "balanced_optimum":
            kind = "all_optima_balanced" if params.get("mode") == "all" else "balanced_optimum_exists"
        kind = {"energy_threshold": "profile_threshold"}.get(kind, kind)
        if kind not in KINDS:
            return unsupported("unregistered predicate")
        allowed = {
            "balanced_optimum_exists": {"b", "threshold", "comparison", "max_b", "mode"},
            "all_optima_balanced": {"b", "threshold", "comparison", "max_b", "mode"},
            "profile_monotone": {"b", "threshold", "comparison", "direction"},
            "bound_attainable": {"b", "threshold", "comparison"},
            "profile_threshold": {"b", "threshold", "comparison", "operator"},
        }[kind]
        if set(params) - allowed:
            return unsupported("unknown predicate parameter")
        irrelevant = {
            "balanced_optimum_exists": {"threshold", "comparison"},
            "all_optima_balanced": {"threshold", "comparison"},
            "profile_monotone": {"b", "threshold"},
            "bound_attainable": {"threshold", "comparison"},
            "profile_threshold": set(),
        }[kind]
        if any(params.get(key) is not None for key in irrelevant):
            return unsupported("unrelated predicate parameter must be null")
        b_arg = params.get("b")
        if b_arg is not None and (isinstance(b_arg, bool) or not isinstance(b_arg, int) or b_arg < 0):
            return unsupported("b must be nonnegative integer or null")
        profile_map = _profiles_map(profiles)
        cert_map = {}
        for cert in certificates or []:
            if check_bound(cert)["valid"]:
                cert_map[(cert["n"], cert["b"])] = cert
        valid_witnesses = []
        for witness in witnesses or []:
            if verify_sequence(witness)["valid"]:
                valid_witnesses.append(witness)
    except (KeyError, TypeError, ValueError) as exc:
        return unsupported(str(exc))
    checks, bound_count = [], 0
    for n in range(n_min, n_max + 1):
        profile = profile_map.get(n)
        trusted = _trusted(profile)
        rows = {row["b"]: row for row in (profile or {}).get("strata", [])}
        for row in rows.values():
            witness = row.get("witness")
            if witness is None and "sequence" in row:
                witness = evaluate_reference(row["sequence"])
            if witness and verify_sequence(witness)["valid"] and witness["n"] == n:
                valid_witnesses.append(witness)
        instance = {"n": n, "truth": None, "evidence": None, "trusted_complete_profile": trusted}
        if kind in ("balanced_optimum_exists", "all_optima_balanced"):
            limit = params.get("max_b", b_arg if b_arg is not None else n % 2)
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
                return unsupported("max_b must be a nonnegative integer")
            if trusted:
                opt_b = profile["optimal_b"]
                passing = [b for b in opt_b if b <= limit]
                instance["truth"] = bool(passing) if kind == "balanced_optimum_exists" else len(passing) == len(opt_b)
                instance["evidence"] = {"optimum_E": profile["optimum_E"], "optimal_b": opt_b,
                                        "optimal_counts_by_b": profile["optimal_counts_by_b"], "max_b": limit}
                if instance["truth"] is False:
                    violating = next((rows[b]["witness"] for b in opt_b if b > limit), None)
                    instance["counterexample"] = violating
                    if kind == "balanced_optimum_exists":
                        instance["counterexample_reason"] = "complete optimum set has no b within balanced threshold"
        elif kind == "profile_monotone":
            direction = params.get("direction")
            comparison = params.get("comparison") or ("ge" if direction == "nonincreasing" else "le")
            if comparison not in ("le", "ge") or direction not in (None, "nondecreasing", "nonincreasing"):
                return unsupported("profile monotonicity requires le/ge")
            if trusted:
                pairs = list(zip(sorted(rows), sorted(rows)[1:]))
                violations = [(a, b) for a, b in pairs if not (rows[a]["E"] <= rows[b]["E"] if comparison == "le" else rows[a]["E"] >= rows[b]["E"])]
                instance["truth"] = not violations
                instance["evidence"] = {"comparison": comparison, "adjacent_pairs_checked": len(pairs)}
                if violations:
                    a, b = violations[0]
                    instance["counterexample"] = {"b_left": a, "E_left": rows[a]["E"],
                                                  "b_right": b, "E_right": rows[b]["E"],
                                                  "left_witness": rows[a]["witness"], "right_witness": rows[b]["witness"]}
        elif kind == "bound_attainable":
            bs = list(range(n % 2, n + 1, 2)) if b_arg is None else [b_arg]
            if any(b > n or (n - b) % 2 for b in bs):
                return unsupported("requested b is not feasible at every domain length")
            classes = []
            for b in bs:
                cert = cert_map.get((n, b))
                if cert is None:
                    from ..math.bounds import lower_bound
                    cert = lower_bound(n, b)
                    if not check_bound(cert)["valid"]:
                        raise RuntimeError("generated bound failed independent checker")
                    bound_count += 1
                actual = [w for w in valid_witnesses if w["n"] == n and w["b"] == b and w["E"] == cert["L"]]
                truth = (rows[b]["E"] == cert["L"]) if trusted else (True if actual else None)
                classes.append({"b": b, "L": cert["L"], "g": rows[b]["E"] if trusted else None, "truth": truth})
            if any(row["truth"] is False for row in classes):
                instance["truth"] = False
            elif all(row["truth"] is True for row in classes):
                instance["truth"] = True
            instance["evidence"] = {"classes": classes, "class_quantifier": "all requested b"}
            if instance["truth"] is False:
                instance["counterexample"] = next(row for row in classes if row["truth"] is False)
        elif kind == "profile_threshold":
            b = n % 2 if b_arg is None else b_arg
            if b > n or (n - b) % 2:
                return unsupported("requested b is not feasible at every domain length")
            T = params.get("threshold")
            comparison = params.get("comparison") or {"<=": "le", ">=": "ge"}.get(params.get("operator"))
            if isinstance(T, bool) or not isinstance(T, int) or comparison not in ("le", "ge"):
                return unsupported("threshold requires an integer and comparison le/ge")
            if trusted:
                g = rows[b]["E"]
                instance["truth"] = g <= T if comparison == "le" else g >= T
                instance["evidence"] = {"b": b, "g": g, "threshold": T, "comparison": comparison, "basis": "independent complete profile"}
            else:
                w = min((w for w in valid_witnesses if w["n"] == n and w["b"] == b), key=lambda w: w["E"], default=None)
                cert = cert_map.get((n, b))
                if comparison == "le":
                    if w and w["E"] <= T:
                        instance.update(truth=True, evidence={"witness": w, "basis": "feasible upper bound"})
                    elif cert and cert["L"] > T:
                        instance.update(truth=False, evidence={"certificate": cert, "basis": "certified lower bound"})
                else:
                    if w and w["E"] < T:
                        instance.update(truth=False, evidence={"witness": w, "basis": "feasible counterexample"}, counterexample=w)
                    elif cert and cert["L"] >= T:
                        instance.update(truth=True, evidence={"certificate": cert, "basis": "certified lower bound"})
        if instance["truth"] is None:
            instance["reason"] = "insufficient certified evidence; no search absence inference"
        checks.append(instance)
    if quantifier == "for_all_n":
        decision = False if any(c["truth"] is False for c in checks) else (True if all(c["truth"] is True for c in checks) else None)
    else:
        decision = True if any(c["truth"] is True for c in checks) else (False if all(c["truth"] is False for c in checks) else None)
    status = {True: "finite_domain_verified", False: "refuted", None: "unresolved"}[decision]
    return {"status": status, "truth": decision, "domain": {"n_min": n_min, "n_max": n_max},
            "quantifier": quantifier, "predicate_kind": kind, "checks": checks,
            "counterexample": next((c for c in checks if c["truth"] is False), None) if decision is False else None,
            "general_theorem": False, "new_enumeration_states": 0, "new_bound_computations": bound_count}
