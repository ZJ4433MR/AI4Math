from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Domain(Strict):
    n_min: int = Field(ge=2, le=22)
    n_max: int = Field(ge=2, le=22)

    @model_validator(mode="after")
    def ordered(self):
        if self.n_min > self.n_max:
            raise ValueError("empty domain")
        return self


class Predicate(Strict):
    kind: Literal["balanced_optimum_exists", "all_optima_balanced", "profile_monotone", "bound_attainable", "profile_threshold"]
    b: int | None = None
    threshold: int | None = None
    comparison: Literal["le", "ge"] | None = None


class Hypothesis(Strict):
    text: str = Field(min_length=5, max_length=1800)
    domain: Domain
    quantifier: Literal["for_all_n", "exists_n"]
    predicate: Predicate
    falsification_condition: str = Field(min_length=5, max_length=1200)


class FrozenPolicy(Strict):
    skew_fraction: float = Field(ge=0, le=1)
    tabu_scale: float = Field(ge=0.05, le=0.30)
    restart_scale: float = Field(ge=0.5, le=2)
    perturb_bits: int = Field(ge=0, le=8)
    decision_summary: str = Field(min_length=5, max_length=1600)


class ToolArguments(Strict):
    n: int | None = Field(default=None, ge=2, le=255)
    b: int | None = Field(default=None, ge=0, le=255)
    seed: int | None = Field(default=None, ge=0, le=2**31-1)
    method: Literal["random", "fixed_tabu", "skew", "fixed_b", "static_mix", "agent_policy"] | None = None
    sequence: list[int] | None = None
    checkpoint_evidence_id: str | None = None
    perturb_bits: int | None = Field(default=None, ge=0, le=8)


class Action(Strict):
    action_type: Literal["propose", "revise", "exact_profile", "lower_bound", "run_search", "check_small_claim", "evaluate_sequence", "analyze_structure", "release_restriction", "restart", "finish"]
    claim_id: str | None = None
    hypothesis: Hypothesis | None = None
    evidence_ids: list[str]
    tool_arguments: ToolArguments
    decision_summary: str = Field(min_length=5, max_length=2000)
    expected_information: str = Field(min_length=5, max_length=1200)
    requested_evaluations: int = Field(ge=0, le=100000)
    policy: FrozenPolicy | None = None


class Review(Strict):
    summary: str = Field(min_length=5, max_length=2400)
    evidence_strength: Literal["exact", "certificate", "counterexample", "empirical", "insufficient"]
    limitation: str = Field(min_length=5, max_length=1600)
    next_question: str = Field(min_length=5, max_length=1600)


def output_schema(model):
    """Strict output APIs require every property, including nullable fields."""
    schema = model.model_json_schema()
    def fix(node):
        if isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for value in node.values():
                fix(value)
        elif isinstance(node, list):
            for value in node:
                fix(value)
    fix(schema)
    return schema
