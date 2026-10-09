"""Evidence checks, with real small tools; PDF fixtures do not mimic research."""
import pytest

from ai4math_agent.math.bounds import lower_bound
from ai4math_agent.math.core import evaluate
from ai4math_agent.math.exact import exact_profile
from ai4math_agent.reporting.report import _verify_nested, load_report_evidence
from ai4math_agent.search.engine import run_search
from ai4math_agent.storage import seal_manifest, write_json
from ai4math_agent.verification.reference import check_bound, verify_exact_profile, verify_sequence


def _dataset(tmp_path):
    research, evaluation, exact = [tmp_path / name for name in ("research", "evaluation", "exact")]
    witness = evaluate([1, 1, 1, -1])
    verification = verify_sequence(witness)
    action = {"action_type": "evaluate_sequence", "evidence_ids": [], "decision_summary": "Test wiring only"}
    round_ = {"round_index": 1, "action": action, "evidence_id": "EV001", "budget_before": {}, "budget_after": {}}
    state = {"mode": "dry_run", "rounds": [round_], "hypotheses": {},
             "evidence": [{"id": "EV001", "tool": "evaluate_sequence", "args": {"sequence": witness["sequence"]}, "result": witness, "verification": verification}]}
    write_json(research / "state.json", state)
    write_json(research / "rounds" / "001.json", round_)
    write_json(research / "frozen_policy.json", {"skew_fraction": .5, "tabu_scale": .11, "restart_scale": 1., "perturb_bits": 1, "decision_summary": "Test wiring only"})
    seal_manifest(research, {"mode": "dry_run", "run_id": "report-integrity-test"})
    run = {"n": 4, "seed": 1, "method": "random", "result": {"best": witness, "evaluations": 1, "elapsed": .01, "curve": [{"evaluations": 1, "E": witness["E"]}]}, "verification": verification}
    write_json(evaluation / "runs.json", [run])
    seal_manifest(evaluation, {"mode": "evaluation", "config": {"lengths": [4], "seeds": [1], "budget": 1}})
    profile = exact_profile(4)
    profile["bounds"] = []
    for row in profile["strata"]:
        cert = lower_bound(4, row["b"])
        cert["verification"] = check_bound(cert)
        profile["bounds"].append(cert)
    profile["verification"] = verify_exact_profile(profile)
    write_json(exact / "profile_004.json", profile)
    seal_manifest(exact, {"mode": "exact"})
    return research, evaluation, exact, state, run, profile


def test_report_reads_verified_real_small_evidence(tmp_path):
    research, evaluation, exact, _, _, _ = _dataset(tmp_path)
    data = load_report_evidence(research, evaluation, exact)
    assert data["mode"] == "dry_run"
    assert data["profiles"][0]["optimum_E"] == 2
    assert data["bounds"][(4, 2)]["L"] == 2
    assert any(c["kind"] == "complete enumeration" for c in data["checks"])


def test_report_rejects_changed_sealed_artifact(tmp_path):
    research, evaluation, exact, state, _, _ = _dataset(tmp_path)
    state["evidence"][0]["result"]["E"] = 999
    write_json(research / "state.json", state)
    with pytest.raises(ValueError, match="changed evidence"):
        load_report_evidence(research, evaluation, exact)


def test_report_recomputes_witness_even_if_hashes_resealed(tmp_path):
    research, evaluation, exact, _, run, _ = _dataset(tmp_path)
    run["result"]["best"]["E"] += 4
    run["result"]["curve"][0]["E"] += 4
    write_json(evaluation / "runs.json", [run])
    seal_manifest(evaluation, {"mode": "evaluation"})
    with pytest.raises(ValueError, match="witness mismatch"):
        load_report_evidence(research, evaluation, exact)


def test_report_rejects_missing_round_or_invalid_mode(tmp_path):
    research, evaluation, exact, _, _, _ = _dataset(tmp_path)
    (research / "rounds" / "001.json").unlink()
    seal_manifest(research, {"mode": "replay"})
    with pytest.raises(ValueError, match="mode mismatch"):
        load_report_evidence(research, evaluation, exact)


def test_report_rejects_forged_exact_completeness(tmp_path):
    research, evaluation, exact, _, _, profile = _dataset(tmp_path)
    profile["visited"] -= 1
    profile["verification"] = {"valid": True, "recomputed_complete": True}
    write_json(exact / "profile_004.json", profile)
    seal_manifest(exact, {"mode": "exact"})
    with pytest.raises(ValueError, match="invalid profile"):
        load_report_evidence(research, evaluation, exact)


def test_report_rejects_tampered_lower_bound(tmp_path):
    research, evaluation, exact, _, _, profile = _dataset(tmp_path)
    profile["bounds"][0]["L"] += 4
    write_json(exact / "profile_004.json", profile)
    seal_manifest(exact, {"mode": "exact"})
    with pytest.raises(ValueError, match="lower-bound certificate mismatch"):
        load_report_evidence(research, evaluation, exact)


def test_report_validates_real_partial_search_checkpoints():
    result = run_search(n=31, method="fixed_tabu", evaluations=500, seed=11)
    checks = []
    _verify_nested(result, "TEST:actual-search", checks)
    assert any(row["kind"] == "witness" for row in checks)
    assert {row["path"][-1] for row in checks if row["kind"] == "checkpoint"} == {"current", "local_best", "run_best"}
    result["checkpoint"]["state"]["current"]["E"] += 4
    with pytest.raises(ValueError, match="checkpoint/stratum E mismatch"):
        _verify_nested(result, "TEST:actual-search", [])
