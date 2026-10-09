import pytest
from ai4math_agent.agent.schema import Action, output_schema
from ai4math_agent.backends.planner import BackendError, public_events
from ai4math_agent.storage import seal_manifest, validate_manifest, write_json


def test_public_events_reject_tools():
    with pytest.raises(BackendError):
        public_events('{"type":"item.completed","item":{"type":"command_execution","command":"python"}}')
    with pytest.raises(BackendError):
        public_events('{"type":"unknown"}')


def test_manifest_reject_tampering(tmp_path):
    write_json(tmp_path/"evidence.json", {"E":2})
    seal_manifest(tmp_path, {"mode":"dry_run"})
    validate_manifest(tmp_path)
    write_json(tmp_path/"evidence.json", {"E":1})
    with pytest.raises(ValueError):
        validate_manifest(tmp_path)


def test_strict_action_reject_unknown_fields():
    action = {"action_type":"lower_bound","claim_id":None,"hypothesis":None,"evidence_ids":[],"tool_arguments":{"n":6,"b":4},"decision_summary":"Check certificate.","expected_information":"Check finite class.","requested_evaluations":0,"policy":None}
    Action.model_validate(action)
    action["shell"] = "python"
    with pytest.raises(ValueError):
        Action.model_validate(action)
    assert set(output_schema(Action)["required"]) == set(output_schema(Action)["properties"])
