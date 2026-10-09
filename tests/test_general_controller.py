"""Scripted offline tests verify control flow, never substitute for live demos."""
import json
from pathlib import Path
import pytest
from ai4math_agent.general.controller import solve, verify_general
from ai4math_agent.storage import read_json, write_json, validate_manifest


class Scripted:
    mode = "dry_run"
    name = "scripted_test"
    def __init__(self, decisions, alignment=True):
        self.decisions = iter(decisions)
        self.contexts = []
        self.alignment = alignment
    def decide(self, context, schema, call_dir):
        self.contexts.append(context)
        if context["role"] == "skeptic":
            answer = {"summary": "Offline test critic saw actual evidence.", "evidence_strength": "insufficient", "formalization_matches_claim": self.alignment, "flaw": "Test only.", "next_question": "Revise after the checked counterexample.", "recommended_action": "revise", "clarity_score": 3, "significance_score": 2, "tractability_score": 4}
        else:
            answer = next(self.decisions)
        write_json(Path(call_dir) / "answer.json", answer)
        return answer, {"mode": "dry_run"}


def decision(kind, **kw):
    return {"action_type": kind, "claim_id": None, "hypothesis": None, "parent_id": None, "tool_name": None,
            "arguments_json": "{}", "evidence_ids": [], "decision_summary": "Scripted offline control-flow decision.", "expected_information": "Validate host behavior.", **kw}


def test_feedback_counterexample_revision_and_recheck(tmp_path):
    args = {"variables": {"n": {"kind": "integer_range", "min": 1, "max": 3}}, "statement": {"lhs": "n**2", "relation": "eq", "rhs": "n"}, "mode": "exhaustive", "quantifier": "forall", "max_assignments": 3}
    backend = Scripted([decision("plan"), decision("tool", hypothesis="All integers n from 1 to 3 satisfy n squared equals n.", tool_name="finite_check", arguments_json=json.dumps(args)),
                        decision("revise", parent_id="H001", hypothesis="Only n=1 in the tested positive range satisfies this identity.", evidence_ids=["EV002"]), decision("finish")])
    directory = solve({"title": "Offline test", "statement": "Test a finite integer claim."}, "dry_run", max_rounds=4, output_root=tmp_path, backend=backend)
    state = read_json(directory / "state.json")
    assert state["hypotheses"][0]["status"] == "formal_counterexample_available"
    assert state["hypotheses"][0]["formal_status"] == "refuted"
    assert state["hypotheses"][1]["parent_id"] == "H001"
    assert backend.contexts[4]["last_review"]["next_question"].startswith("Revise")
    assert state["budget"]["backend_attempts"] == 8
    assert verify_general(directory)["valid"]
    assert validate_manifest(directory)["answers_preloaded"] is False


def test_unknown_tool_budget_and_no_false_proof(tmp_path):
    backend = Scripted([decision("tool", hypothesis="An untested claim about integers.", tool_name="unknown", arguments_json="{}"), decision("finish")])
    directory = solve({"title": "Offline test", "statement": "Test unknown tools are rejected."}, "dry_run", max_rounds=2, output_root=tmp_path, backend=backend)
    state = read_json(directory / "state.json")
    assert state["evidence"][0]["result"]["status"] == "action_rejected"
    assert state["hypotheses"][0]["status"] == "proposed"
    assert state["budget"]["tool_calls"] == 0


def test_reservation_failure_and_source_bound_resume(tmp_path):
    backend = Scripted([decision("tool", tool_name="python_experiment", arguments_json=json.dumps({"code": "result = 1", "max_operations": 200000}))])
    directory = solve({"title": "Offline test", "statement": "Test operation reservation budget."}, "dry_run", max_rounds=1, max_operations=10, output_root=tmp_path, backend=backend)
    state = read_json(directory / "state.json")
    assert state["termination_reason"] == "budget_exhausted"
    assert state["budget"]["operation_reservations"] == 0
    with pytest.raises(ValueError, match="configuration"):
        solve(None, "dry_run", max_rounds=2, max_operations=10, resume=directory, backend=backend)


def test_unrelated_identity_does_not_prove_natural_claim(tmp_path):
    args = {"variables": {"x": "integer"}, "lhs": "x", "rhs": "x", "domain": {"exclude_zero": []}}
    backend = Scripted([decision("tool", hypothesis="Every integer is prime.", tool_name="symbolic_check", arguments_json=json.dumps(args))], alignment=False)
    directory = solve({"title": "Semantic alignment test", "statement": "Research the distribution of primes."}, "dry_run", max_rounds=1, output_root=tmp_path, backend=backend)
    state = read_json(directory / "state.json")
    assert state["evidence"][0]["result"]["status"] == "symbolic_identity_verified"
    assert state["hypotheses"][0]["status"] == "formalization_mismatch"
    assert state["hypotheses"][0]["semantic_alignment"]["independent_proof_of_alignment"] is False
