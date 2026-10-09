from typing import Literal
from pydantic import Field
from ai4math_agent.agent.schema import Strict


class Problem(Strict):
    title: str = Field(min_length=1, max_length=200)
    statement: str = Field(min_length=5, max_length=12000)
    assumptions: list[str] = []
    goal: str = "Research the question, test conjectures, attempt proofs, and report verified conclusions and remaining gaps."


class Decision(Strict):
    action_type: Literal["plan", "propose", "revise", "tool", "proof", "finish"]
    claim_id: str | None = None
    hypothesis: str | None = Field(default=None, max_length=4000)
    parent_id: str | None = None
    tool_name: str | None = None
    arguments_json: str = Field(default="{}", max_length=24000)
    evidence_ids: list[str]
    decision_summary: str = Field(min_length=5, max_length=3000)
    expected_information: str = Field(min_length=5, max_length=1600)


class Critique(Strict):
    summary: str = Field(min_length=5, max_length=3000)
    evidence_strength: Literal["symbolic_certificate", "induction_certificate", "finite_exhaustive", "counterexample", "empirical", "proof_candidate", "background", "insufficient"]
    formalization_matches_claim: bool
    flaw: str = Field(max_length=2000)
    next_question: str = Field(min_length=5, max_length=2000)
    recommended_action: Literal["continue", "revise", "prove", "counterexample", "finish"]
    clarity_score: int = Field(ge=0, le=5)
    significance_score: int = Field(ge=0, le=5)
    tractability_score: int = Field(ge=0, le=5)
