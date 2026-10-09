"""One final feedback round correcting an audited diagnostic before holdout.

Raw experiment records are preserved. No new mathematical experiment occurs.
This consumes the remaining allowed round and two actual backend attempts.
"""
from pathlib import Path
import copy
import sys
import time
from ai4math_agent.agent.schema import Action, Review, output_schema
from ai4math_agent.agent.controller import evidence_summary
from ai4math_agent.backends import make_backend
from ai4math_agent.storage import digest, read_json, write_json, seal_manifest, validate_manifest, now


def main(directory):
    directory = Path(directory)
    manifest = validate_manifest(directory)
    state = read_json(directory/"state.json")
    config = manifest["config"]
    if manifest["mode"] != "live" or len(state["rounds"]) >= config["max_rounds"]:
        raise ValueError("no remaining live round for final feedback")
    if state["budget"]["backend_call_attempts"] + 2 > config["max_backend_call_attempts"]:
        raise ValueError("no remaining backend budget")
    started = time.monotonic()
    before = copy.deepcopy(state["budget"])
    parent = digest(state)
    correction = ("Independent implementation audit found that diagnostics.effective_skew_fraction in the research version "
        "was a configured default rather than the actual fraction for non-mix methods. EV004, EV006, EV008 fixed_tabu "
        "were entirely unrestricted (actual fraction 0); EV005, EV007, EV009 skew were entirely skew (actual fraction 1). "
        "The numerical witnesses, energy, method, restriction, budgets and comparisons remain independently valid. "
        "Do not call fixed_tabu a mixed baseline. Raw logs will be preserved with this correction. No holdout result exists.")
    backend = make_backend(manifest["backend"], config["model"], config["backend_timeout_seconds"])

    def call(role, context, model):
        remaining = config["session_wall_seconds"] - before["session_seconds"] - (time.monotonic()-started)
        if remaining <= 0:
            raise ValueError("session wall exhausted")
        backend.timeout = min(config["backend_timeout_seconds"], remaining)
        state["budget"]["backend_call_attempts"] += 1
        write_json(directory/"state.json", state)
        manifest["budget"] = state["budget"]
        seal_manifest(directory, manifest)
        number = state["budget"]["backend_call_attempts"]
        answer, metadata = backend.decide(context, output_schema(model), directory/"calls"/f"{number:03d}_{role}")
        return model.model_validate(answer), metadata

    action, metadata = call("proposer", {"role":"proposer", "instruction": "Use the final remaining research round to acknowledge audited feedback and freeze the final policy. action_type must be finish, requested_evaluations=0; no experiments or general proofs. Retain or revise the existing policy based ONLY on supplied corrected development evidence. Explain the actual restrictions accurately. All unrelated nullable fields null.",
        "audited_feedback":correction,"existing_policy":read_json(directory/"frozen_policy.json"),
        "evidence":[evidence_summary(e) for e in state["evidence"]],"hypotheses":state["hypotheses"],"budget":state["budget"]}, Action)
    if action.action_type != "finish" or action.requested_evaluations != 0 or action.policy is None:
        raise ValueError("final round must freeze policy without new search")
    known = {e["id"] for e in state["evidence"]}
    if any(e not in known for e in action.evidence_ids):
        raise ValueError("unknown final evidence reference")
    eid = f"EV{len(state['evidence'])+1:03d}"
    result = {"summary":action.decision_summary,"policy":action.policy.model_dump(),"diagnostic_correction":correction}
    evidence = {"id":eid,"tool":"finish","args":action.tool_arguments.model_dump(),"result":result,
                "verification":{"valid":True,"scope":"metadata correction from actual method/restriction; no new mathematics"}}
    review, review_metadata = call("skeptic", {"role":"skeptic","instruction":"Audit the final policy and interpretation using actual results. No general theorem or superiority claim. Recognize metadata correction and tiny development sample.","evidence":evidence,"development_evidence":[evidence_summary(e) for e in state["evidence"] if e["tool"]=="run_search"]}, Review)
    write_json(directory/"initial_frozen_policy.json", read_json(directory/"frozen_policy.json"))
    write_json(directory/"frozen_policy.json", action.policy.model_dump())
    state["evidence"].append(evidence)
    state["budget"]["session_seconds"] += time.monotonic()-started
    state["feedback"] = review.summary+" Limitation: "+review.limitation+" Next: "+review.next_question
    row = {"round_index":len(state["rounds"])+1,"parent_state_hash":parent,"action":action.model_dump(),"evidence_id":eid,
           "skeptic":review.model_dump(),"proposer_metadata":metadata,"skeptic_metadata":review_metadata,
           "budget_before":before,"budget_after":copy.deepcopy(state["budget"]),"feedback":state["feedback"],"phase":"pre_holdout_diagnostic_audit"}
    state["rounds"].append(row)
    write_json(directory/"rounds"/f"{row['round_index']:03d}.json",row)
    write_json(directory/"state.json",state)
    manifest.update(rounds=len(state["rounds"]),budget=state["budget"],end=now(),policy_hash=digest(action.policy.model_dump()),
                    diagnostic_audit_evidence_id=eid,termination_reason="model_finished")
    seal_manifest(directory,manifest)
    print({"rounds":len(state["rounds"]),"calls":state["budget"]["backend_call_attempts"],"policy":action.policy.model_dump()},flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
