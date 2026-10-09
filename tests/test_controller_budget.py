"""Controller search budgets and checkpoint integration regressions."""

import json
from pathlib import Path

import pytest

from ai4math_agent.agent.controller import ToolRouter, research
from ai4math_agent.agent.schema import Action
from ai4math_agent.search.engine import run_search
from ai4math_agent.storage import read_json, validate_manifest


def configuration(tmp_path):
    return {"target_lengths": [9], "seeds": [11], "max_rounds": 1,
            "max_evaluations": 100, "per_round_evaluations": 50,
            "max_backend_call_attempts": 4, "exact_wall_seconds": 10,
            "search_wall_seconds": 10, "session_wall_seconds": 30,
            "backend_timeout_seconds": 180, "model": None,
            "exact_dir": str(tmp_path / "exact"), "output_root": str(tmp_path / "research")}


def state():
    return {"profiles": [], "evidence": [], "hypotheses": {},
            "budget": {"evaluations": 0, "search_seconds": 0, "exact_seconds": 0,
                       "enumeration_states": 0, "verification_seconds": 0, "session_seconds": 0}}


def action(kind="run_search", cost=20, **args):
    tool_args = {"n": 9, "seed": 11, "method": "fixed_tabu"} if kind == "run_search" else {}
    tool_args.update(args)
    return Action.model_validate({"action_type": kind, "claim_id": None, "hypothesis": None,
        "evidence_ids": [], "tool_arguments": tool_args, "decision_summary": "Test budget reservation.",
        "expected_information": "Check exact controller accounting.", "requested_evaluations": cost,
        "policy": None})


def test_per_round_and_total_search_caps_reject_before_work(tmp_path):
    facts = state()
    router = ToolRouter(facts, configuration(tmp_path))
    with pytest.raises(ValueError, match="budget"):
        router.call(action(cost=51))
    assert facts["budget"]["evaluations"] == 0
    facts["budget"]["evaluations"] = 90
    with pytest.raises(ValueError, match="budget"):
        router.call(action(cost=11))
    assert facts["budget"]["evaluations"] == 90


def test_exact_actual_search_cost_and_constraint_rejection(tmp_path):
    facts = state()
    router = ToolRouter(facts, configuration(tmp_path))
    result, verification = router.call(action(cost=21))
    assert facts["budget"]["evaluations"] == result["evaluations"] == 21
    assert verification["valid"]
    with pytest.raises(ValueError):
        router.call(action(cost=10, b=2))


def test_release_consumes_checkpoint_current_and_counts_initialization(tmp_path):
    facts = state()
    skew = run_search(9, "skew", 101, 11)
    facts["evidence"].append({"id": "EV001", "result": skew})
    router = ToolRouter(facts, configuration(tmp_path))
    result, verification = router.call(action("release_restriction", 1, n=9, seed=11,
                                               checkpoint_evidence_id="EV001"))
    assert result["best"]["sequence"] == skew["checkpoint"]["state"]["current"]["sequence"]
    assert facts["budget"]["evaluations"] == 1
    assert verification["valid"]


class _FakeBackend:
    mode = "dry_run"
    timeout = 180

    def __init__(self, advance=None):
        self.advance = advance
        self.timeouts = []

    def decide(self, context, schema, call_dir):
        self.timeouts.append(self.timeout)
        if self.advance:
            self.advance()
        if context["role"] == "proposer":
            return action().model_dump(), {"mode": self.mode}
        return {"summary": "Only independently checked tool evidence is accepted.",
                "evidence_strength": "empirical", "limitation": "Heuristic result is not optimality.",
                "next_question": "Compare a distinct strategy with equal budget."}, {"mode": self.mode}


def test_search_reservation_is_persisted_and_sealed_before_execution(tmp_path, monkeypatch):
    config = configuration(tmp_path)
    fake = _FakeBackend()
    monkeypatch.setattr("ai4math_agent.agent.controller.make_backend", lambda *args: fake)
    observed = []
    original = run_search

    def inspect_reserved_state(**kwargs):
        directory = next(Path(config["output_root"]).iterdir())
        saved = read_json(directory / "state.json")
        assert saved["budget"]["evaluations"] == kwargs["evaluations"]
        validate_manifest(directory)  # crash recovery must accept this reservation
        observed.append(kwargs["evaluations"])
        return original(**kwargs)

    monkeypatch.setattr("ai4math_agent.search.engine.run_search", inspect_reserved_state)
    directory = research(config, "dry_run")
    assert observed == [20]
    assert read_json(directory / "state.json")["budget"]["evaluations"] == 20


def test_backend_timeout_and_post_proposer_session_wall_guard(tmp_path, monkeypatch):
    config = configuration(tmp_path)
    config["session_wall_seconds"] = 2.0
    clock = [0.0]
    fake = _FakeBackend(advance=lambda: clock.__setitem__(0, clock[0] + 3))
    monkeypatch.setattr("ai4math_agent.agent.controller.make_backend", lambda *args: fake)
    monkeypatch.setattr("ai4math_agent.agent.controller.time.monotonic", lambda: clock[0])
    called = []
    monkeypatch.setattr("ai4math_agent.search.engine.run_search", lambda **kwargs: called.append(kwargs))
    directory = research(config, "dry_run")
    final_state = read_json(directory / "state.json")
    assert not called, "expired session must not start another mathematical tool"
    assert final_state["budget"]["backend_call_attempts"] == 1
    assert fake.timeouts[0] <= config["session_wall_seconds"]
