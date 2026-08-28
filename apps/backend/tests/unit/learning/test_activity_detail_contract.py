from tamforge_backend.learning.service import _task_contract_response
from tamforge_backend.roadmaps.models import TaskDefinition


def test_activity_detail_contract_preserves_governed_task_fields() -> None:
    definition = TaskDefinition(
        owner_id=1,
        roadmap_version_id=2,
        curriculum_node_id=3,
        stable_id="m1-w1-d1-technical-learning",
        exercise_type="technical_reading",
        mapping_version="month-1-v1",
        objective="Explain HTTP request and response boundaries.",
        timebox_minutes=45,
        block="technical_learning",
        required=True,
        output_contract={
            "schema_version": 1,
            "items": ["Closed-source recall note", "Teach-back"],
            "procedure": [
                {"phase": "Preview", "minutes": 2, "requirement": "Read the objective."}
            ],
            "constraints": ["Commit recall with the source hidden."],
            "correction_selection": None,
        },
        pass_contract={"schema_version": 1, "items": ["Names one failure boundary."]},
        evidence_contract={"schema_version": 1, "items": ["Independent recall note"]},
        source_references=[{"path": "Week 1.md", "heading": "HTTP"}],
        allowed_ai_role="tutor",
        source_path="Week 1.md",
        source_anchor="HTTP",
    )

    contract = _task_contract_response(definition)

    assert contract.model_dump() == {
        "stable_id": "m1-w1-d1-technical-learning",
        "block": "technical_learning",
        "objective": "Explain HTTP request and response boundaries.",
        "timebox_minutes": 45,
        "required": True,
        "source_references": ({"path": "Week 1.md", "anchor": "HTTP"},),
        "required_output": ("Closed-source recall note", "Teach-back"),
        "pass_criteria": ("Names one failure boundary.",),
        "evidence_requirements": ("Independent recall note",),
        "allowed_ai_role": "tutor",
        "procedure": (
            {"phase": "Preview", "minutes": 2, "requirement": "Read the objective."},
        ),
        "constraints": ("Commit recall with the source hidden.",),
        "exercise_type": "technical_reading",
        "mapping_version": "month-1-v1",
    }
