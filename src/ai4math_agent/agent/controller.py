"""Research facts are controlled by tool evidence, never by model assertions."""
from __future__ import annotations
import copy
import time
from pathlib import Path
from .schema import Action, Review, output_schema
from ai4math_agent.backends import make_backend
from ai4math_agent.storage import digest, now, read_json, write_json, seal_manifest, validate_manifest, source_metadata


def _require_valid(result):
    if result is False or isinstance(result, dict) and result.get("valid") is False:
        raise ValueError(f"independent verification failed: {result}")
    return result


def evidence_summary(evidence):
    result = evidence["result"]
    if "checkpoint" in result:
        checkpoint = result["checkpoint"]
        small = {k: result.get(k) for k in ["best", "evaluations", "unique_evaluations", "elapsed", "termination_reason", "diagnostics", "restriction", "method", "seed", "params"]}
        small["checkpoint"] = {"restriction": checkpoint.get("restriction"), "current": checkpoint.get("state", {}).get("current")}
    elif "strata" in result:
        small = {k: result.get(k) for k in ["n", "complete", "exact", "visited", "optimum_E", "optimal_b"]}
        small["strata"] = [{k:r.get(k) for k in ["b","E","sequence"]} for r in result["strata"]]
    else:
        small = result
    return {"id": evidence["id"], "tool": evidence["tool"], "args": evidence["args"], "result": small,
            "verification": {k:evidence["verification"].get(k) for k in ["valid","status","scope","errors"]}}


class ToolRouter:
    def __init__(self, state, config, persist=None, remaining_session=None):
        self.state, self.config = state, config
        self.persist = persist or (lambda: None)
        self.remaining_session = remaining_session or (lambda: config["session_wall_seconds"])

    def _initial(self, args):
        reference = args.get("checkpoint_evidence_id")
        if reference:
            evidence = next((e for e in self.state["evidence"] if e["id"] == reference), None)
            if not evidence or "checkpoint" not in evidence["result"]:
                raise ValueError("checkpoint evidence not found")
            checkpoint = evidence["result"]["checkpoint"]
            current = checkpoint.get("state", checkpoint).get("current")
            return current.get("sequence") if isinstance(current, dict) else current
        return args.get("sequence")

    def call(self, action):
        if self.remaining_session() <= 0:
            raise RuntimeError("session time budget exhausted")
        from ai4math_agent.math.core import evaluate
        from ai4math_agent.math.bounds import lower_bound
        from ai4math_agent.math.exact import exact_profile
        from ai4math_agent.verification.reference import verify_sequence, check_bound
        from ai4math_agent.verification.claims import check_small_claim
        typ = action.action_type
        args = action.tool_arguments.model_dump(exclude_none=True)
        before = time.monotonic()
        cost = action.requested_evaluations
        active = {"run_search", "release_restriction", "restart"}
        allowed_fields = {
            "propose": set(), "revise": set(), "finish": set(),
            "exact_profile": {"n"}, "lower_bound": {"n", "b"},
            "evaluate_sequence": {"sequence"}, "analyze_structure": {"sequence", "checkpoint_evidence_id"},
            "check_small_claim": set(),
            "run_search": {"n", "b", "seed", "method", "sequence", "checkpoint_evidence_id"},
            "release_restriction": {"n", "seed", "checkpoint_evidence_id"},
            "restart": {"n", "b", "seed", "method", "checkpoint_evidence_id", "perturb_bits"}}
        if set(args) - allowed_fields[typ]:
            raise ValueError("unrelated or unknown tool parameters")
        if typ not in active | {"evaluate_sequence"} and cost:
            raise ValueError("non-search tool cannot request search evaluations")
        if typ == "evaluate_sequence" and cost != 1:
            raise ValueError("new sequence evaluation must request exactly one counted evaluation")
        if cost > self.config["per_round_evaluations"] or cost + self.state["budget"]["evaluations"] > self.config["max_evaluations"]:
            raise ValueError("search budget exceeded")
        if typ in {"propose", "revise"}:
            if not action.claim_id or not action.hypothesis:
                raise ValueError("a precise registered hypothesis is required")
            return {"hypothesis": action.hypothesis.model_dump(), "status": "proposed"}, {"valid": True, "scope": "proposal only"}
        if typ == "finish":
            return {"summary": action.decision_summary, "policy": action.policy.model_dump() if action.policy else None}, {"valid": True, "scope": "summary only"}
        if typ == "lower_bound":
            result = lower_bound(args["n"], args["b"])
            verification = _require_valid(check_bound(result))
        elif typ == "exact_profile":
            from ai4math_agent.verification.reference import verify_exact_profile
            n = args["n"]
            if n > 18:
                raise ValueError("online exact tool limited to n<=18")
            result = next((p for p in self.state["profiles"] if p["n"] == n), None)
            if result is None:
                remaining = min(self.remaining_session(), self.config["exact_wall_seconds"] - self.state["budget"]["exact_seconds"])
                if remaining <= 0:
                    raise ValueError("exact time budget exhausted")
                result = exact_profile(n, wall_seconds=remaining)
                self.state["budget"]["exact_seconds"] += time.monotonic() - before
                self.state["budget"]["enumeration_states"] += result["visited"]
                result["verification"] = _require_valid(verify_exact_profile(result, exhaustive=True))
                self.state["profiles"].append(result)
            verification = result["verification"]
        elif typ in active:
            from ai4math_agent.search.engine import run_search
            if cost < 1 or args.get("n") not in self.config["target_lengths"] or args.get("seed") not in self.config["seeds"]:
                raise ValueError("search needs positive budget and configured development length/seed")
            remaining_wall = min(self.remaining_session(), self.config["search_wall_seconds"] - self.state["budget"]["search_seconds"])
            if remaining_wall <= 0:
                raise ValueError("search time budget exhausted")
            initial = self._initial(args)
            if typ == "release_restriction" and initial is None:
                raise ValueError("release requires actual checkpoint")
            method = "fixed_tabu" if typ == "release_restriction" else args.get("method", "fixed_tabu")
            if typ == "restart" and initial is not None:
                # Perturbation is evaluated by run_search as counted initialization.
                import random
                bits = args.get("perturb_bits", 2)
                initial = list(initial)
                for j in random.Random(args["seed"]).sample(range(len(initial)), min(bits, len(initial))):
                    initial[j] *= -1
                if method in {"skew", "fixed_b"}:
                    raise ValueError("generic perturbation only supports unrestricted restart")
            # Reserve before execution so crashes and resumes cannot grant free attempts.
            self.state["budget"]["evaluations"] += cost
            self.state["pending_tool"] = {"tool": typ, "reserved_evaluations": cost, "start": now()}
            self.persist()
            result = run_search(n=args["n"], method=method, evaluations=cost, seed=args["seed"],
                                initial=initial, b=args.get("b"), policy=action.policy.model_dump() if action.policy else None,
                                wall_seconds=remaining_wall)
            self.state["budget"]["evaluations"] -= cost - result["evaluations"]
            self.state["budget"]["search_seconds"] += result["elapsed"]
            self.state.pop("pending_tool", None)
            verification = _require_valid(verify_sequence(result["best"]))
            if typ == "release_restriction":
                result["release_from_sequence"] = initial
                result["restriction_change"] = "checkpoint -> unrestricted"
        elif typ == "evaluate_sequence":
            self.state["budget"]["evaluations"] += 1
            self.persist()
            result = evaluate(args["sequence"])
            verification = _require_valid(verify_sequence(result))
        elif typ == "analyze_structure":
            sequence = self._initial(args)
            if sequence is None:
                raise ValueError("structure analysis requires an existing sequence")
            known = [e["result"].get("best", e["result"]).get("sequence") for e in self.state["evidence"]]
            if sequence not in known and not args.get("checkpoint_evidence_id"):
                raise ValueError("structure analysis is restricted to an already evaluated witness")
            record = evaluate(sequence)
            verification = _require_valid(verify_sequence(record))
            runs = []
            for symbol in sequence:
                if not runs or runs[-1][0] != symbol:
                    runs.append([symbol, 1])
                else:
                    runs[-1][1] += 1
            m = len(sequence)//2
            skew_distance = sum(sequence[m+j] != (-1)**j * sequence[m-j] for j in range(1, m+1)) if len(sequence)%2 else None
            result = {"witness": record, "run_lengths": [r[1] for r in runs], "skew_pair_violations": skew_distance}
        elif typ == "check_small_claim":
            if not action.claim_id or action.claim_id not in self.state["hypotheses"]:
                raise ValueError("checking requires a stored explicit hypothesis")
            claim = self.state["hypotheses"][action.claim_id]["hypothesis"]
            result = check_small_claim(claim, profiles=self.state["profiles"],
                witnesses=[e["result"].get("best", e["result"]) for e in self.state["evidence"]],
                certificates=[e["result"] for e in self.state["evidence"] if e["tool"] == "lower_bound"])
            verification = {"valid": True, "scope": "registered DSL + independently verified profiles", "status": result["status"]}
        else:
            raise ValueError(f"unsupported tool {typ}")
        self.state["budget"]["verification_seconds"] += max(0, time.monotonic() - before - (result.get("elapsed", 0) if isinstance(result, dict) else 0))
        return result, verification


def research(config, backend_name, resume=None, replay_source=None):
    backend = make_backend(backend_name, config.get("model"), config.get("backend_timeout_seconds", 180), replay_source)
    if resume:
        directory = Path(resume)
        manifest = validate_manifest(directory)
        if manifest["mode"] != backend.mode or manifest["config_hash"] != digest(config):
            raise ValueError("resume mode/config mismatch")
        if manifest["source_tree_hash"] != source_metadata()["source_tree_hash"]:
            raise ValueError("source changed; create a new research version instead of resuming")
        state = read_json(directory / "state.json")
    else:
        run_id = now().replace(":", "").replace("+", "_")
        directory = Path(config["output_root"]) / run_id
        directory.mkdir(parents=True)
        profiles = [read_json(p) for p in sorted(Path(config["exact_dir"]).glob("profile_*.json"))]
        if profiles:
            validate_manifest(config["exact_dir"])
        imported = sum(p.get("wall_seconds", 0) for p in profiles)
        state = {"profiles": profiles, "evidence": [], "hypotheses": {}, "rounds": [], "errors": [],
                 "budget": {"evaluations": 0, "search_seconds": 0, "exact_seconds": 0, "enumeration_states": 0,
                            "imported_exact_seconds": imported, "imported_enumeration_states": sum(p["visited"] for p in profiles),
                            "backend_call_attempts": 0, "verification_seconds": 0, "session_seconds": 0},
                 "feedback": "No experiment feedback yet. Preverified n=4,6,13 are known teaching examples, not new discoveries."}
        if Path("results/doctor/doctor.json").exists() and backend.mode == "live":
            doctor = read_json("results/doctor/doctor.json")
            state["budget"]["backend_call_attempts"] = doctor.get("backend_call_attempts", 0)
        manifest = {"run_id": run_id, "mode": backend.mode, "start": now(), "backend": backend_name,
                    "requested_model": config.get("model"), "effective_model": None, "auth_method": "CLI login" if backend_name=="codex_cli" else backend_name,
                    "config": config, "config_hash": digest(config), **source_metadata(),
                    "provider_request_count": "unknown" if backend_name=="codex_cli" else 0}
        write_json(directory / "state.json", state)
        seal_manifest(directory, manifest)
    start_clock = time.monotonic()
    prior_seconds = state["budget"]["session_seconds"]
    def persist():
        state["budget"]["session_seconds"] = prior_seconds + time.monotonic() - start_clock
        write_json(directory / "state.json", state)
        manifest.update(budget=state["budget"], rounds=len(state["rounds"]), end=now(), termination_reason="running")
        seal_manifest(directory, manifest)
    def remaining_session():
        return max(0, config["session_wall_seconds"] - prior_seconds - (time.monotonic() - start_clock))
    router = ToolRouter(state, config, persist, remaining_session)
    termination = "max_rounds"

    def call(role, context, model):
        remaining = remaining_session()
        if remaining <= 0:
            raise RuntimeError("session time budget exhausted")
        if state["budget"]["backend_call_attempts"] >= config["max_backend_call_attempts"]:
            raise RuntimeError("backend call budget exhausted")
        state["budget"]["backend_call_attempts"] += 1
        persist()
        if hasattr(backend, "timeout"):
            backend.timeout = min(config.get("backend_timeout_seconds", 180), remaining)
        number = state["budget"]["backend_call_attempts"]
        answer, metadata = backend.decide({"role": role, **context}, output_schema(model), directory / "calls" / f"{number:03d}_{role}")
        return model.model_validate(answer), metadata

    while len(state["rounds"]) < config["max_rounds"]:
        state["budget"]["session_seconds"] = prior_seconds + time.monotonic() - start_clock
        if state["budget"]["session_seconds"] >= config["session_wall_seconds"]:
            termination = "session_time_limit"
            break
        if state["budget"]["backend_call_attempts"] + 2 > config["max_backend_call_attempts"]:
            termination = "backend_call_limit"
            break
        context = {"problem": "LABS: C_k=sum s_i*s_(i+k), E=sum C_k^2, F=n^2/(2E), b=abs(sum s), g_n(b)=minimum E at b.",
            "objective": "Propose >=2 precise mathematical claims, actually check >=1, and make a decision change based on real tool feedback. Explore development lengths within budget; finish with a frozen search policy only after evidence. Balance existence and ALL optimal balance are different claims. No record or general theorem claims.",
            "constraints": {"development_lengths": config["target_lengths"], "seeds": config["seeds"], "rounds_remaining": config["max_rounds"]-len(state["rounds"]), "config": config, "budget_used": state["budget"]},
            "tools": "propose/revise store hypothesis; check_small_claim uses registered DSL against all trusted profiles. lower_bound needs n,b. run_search needs n,method,seed, requested_evaluations. Methods random,fixed_tabu,skew,fixed_b,static_mix,agent_policy. release_restriction needs n,seed,checkpoint_evidence_id; preserves current sequence. exact_profile n<=18. finish must include policy. Non-applicable args null. No arbitrary code. Policy fields skew_fraction,tabu_scale,restart_scale,perturb_bits,decision_summary.",
            "predicates": "balanced_optimum_exists: global optimum has b=n%2; all_optima_balanced: ALL optima minimal b; profile_monotone: g nondecreasing with b; bound_attainable: g_n(b)=L_n(b), b optional all classes; profile_threshold needs b,threshold,comparison le/ge. domain <=18 covered profiles; quantifier for_all_n or exists_n.",
            "exact_profiles": [{"n": p["n"], "strata": p["strata"], "optimum_E": p.get("optimum_E"), "optimal_b": p.get("optimal_b"), "complete": p["complete"]} for p in state["profiles"]],
            "hypotheses": state["hypotheses"], "evidence": [evidence_summary(e) for e in state["evidence"]], "recent_rounds": state["rounds"][-3:], "previous_feedback": state["feedback"]}
        parent_hash = digest(state)
        budget_before = copy.deepcopy(state["budget"])
        try:
            action, meta = call("proposer", context, Action)
            if any(eid not in {e["id"] for e in state["evidence"]} for eid in action.evidence_ids):
                raise ValueError("unknown referenced evidence")
            if action.action_type == "revise" and action.claim_id not in state["hypotheses"]:
                raise ValueError("revise requires existing claim")
            result, verification = router.call(action)
            eid = f"EV{len(state['evidence'])+1:03d}"
            evidence = {"id": eid, "tool": action.action_type, "args": action.tool_arguments.model_dump(), "result": result, "verification": verification}
            state["evidence"].append(evidence)
            if action.action_type in {"propose", "revise"}:
                previous = state["hypotheses"].get(action.claim_id, {"history": []})
                state["hypotheses"][action.claim_id] = {"hypothesis": action.hypothesis.model_dump(), "status": "proposed",
                    "history": previous["history"] + [{"evidence_id": eid, "action": action.action_type, "hypothesis": action.hypothesis.model_dump()}]}
            elif action.action_type == "check_small_claim":
                state["hypotheses"][action.claim_id]["status"] = result["status"]
                state["hypotheses"][action.claim_id]["history"].append({"evidence_id": eid, "result": result})
            review, review_meta = call("skeptic", {"instruction": "Review ONLY evidence strength, scope, and next question; do not assert proof from model opinion.", "action": action.model_dump(), "evidence": evidence_summary(evidence), "previous_feedback": state["feedback"]}, Review)
            state["feedback"] = review.summary + " Limitation: " + review.limitation + " Next: " + review.next_question
            row = {"round_index": len(state["rounds"])+1, "parent_state_hash": parent_hash, "action": action.model_dump(),
                   "evidence_id": eid, "skeptic": review.model_dump(), "proposer_metadata": meta, "skeptic_metadata": review_meta,
                   "budget_before": budget_before, "budget_after": copy.deepcopy(state["budget"]), "feedback": state["feedback"]}
            state["rounds"].append(row)
            write_json(directory / "rounds" / f"{row['round_index']:03d}.json", row)
            print(f"round {row['round_index']}: {action.action_type}, {eid}, evaluations={state['budget']['evaluations']}", flush=True)
            if action.action_type == "finish":
                checked = any(e["tool"] == "check_small_claim" for e in state["evidence"])
                if len(state["hypotheses"]) < 2 or not checked or len(state["rounds"]) < 3 or action.policy is None:
                    state["feedback"] += " Host: finish incomplete; need two claims, actual check, feedback change, frozen policy."
                else:
                    write_json(directory / "frozen_policy.json", action.policy.model_dump())
                    manifest["policy_hash"] = digest(action.policy.model_dump())
                    termination = "model_finished"
                    break
        except Exception as exc:
            state["errors"].append({"time": now(), "error": str(exc), "attempt": state["budget"]["backend_call_attempts"]})
            state["feedback"] = f"Host rejected action/call: {exc}. Correct schema/parameters. No conclusion established by rejected round."
            print(state["feedback"], flush=True)
            if "session time budget exhausted" in str(exc):
                termination = "session_time_limit"
                break
            # An unavailable backend is a concrete blocker, not a reason to use mock actions.
            if len(state["errors"]) >= 3 and all("codex failed" in e["error"] or "backend timeout" in e["error"] for e in state["errors"][-3:]):
                termination = "backend_unavailable"
                break
        finally:
            state["budget"]["session_seconds"] = prior_seconds + time.monotonic() - start_clock
            write_json(directory / "state.json", state)
            manifest.update(budget=state["budget"], rounds=len(state["rounds"]), end=now(), termination_reason="running")
            seal_manifest(directory, manifest)
    if not (directory / "frozen_policy.json").exists():
        # Preserve only a real model-proposed policy; never invent an agent policy.
        policy = next((r["action"]["policy"] for r in reversed(state["rounds"]) if r["action"].get("policy")), None)
        if policy:
            write_json(directory / "frozen_policy.json", policy)
            manifest["policy_hash"] = digest(policy)
    manifest.update(end=now(), termination_reason=termination, budget=state["budget"], rounds=len(state["rounds"]),
        course_objectives={"two_claims": len(state["hypotheses"])>=2, "claim_checked": any(e["tool"]=="check_small_claim" for e in state["evidence"]),
                           "feedback_followed": any(r["action"]["evidence_ids"] for r in state["rounds"][1:])})
    seal_manifest(directory, manifest)
    return directory
