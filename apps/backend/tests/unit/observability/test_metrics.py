import pytest
from tamforge_backend.observability.metrics import Metrics, record_composite


def test_metrics_aggregate_without_retaining_samples_or_unbounded_labels() -> None:
    metrics = Metrics()
    for _ in range(1000):
        metrics.observe("job_duration_seconds", 2, category="speech", status="succeeded")
    rendered = metrics.render()
    assert 'job_duration_seconds_count{category="speech",status="succeeded"} 1000' in rendered
    assert 'job_duration_seconds_sum{category="speech",status="succeeded"} 2000' in rendered
    for labels in ({"company": "private"}, {"category": "private"}, {"job_id": "123"}):
        with pytest.raises(ValueError, match="metric"):
            metrics.observe("job_duration_seconds", 1, **labels)
    with pytest.raises(ValueError, match="metric"):
        metrics.observe("private_metric", 1)
    assert "private" not in metrics.render()


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True])
def test_metrics_reject_invalid_values(value: float) -> None:
    with pytest.raises(ValueError, match="metric"):
        Metrics().observe("job_duration_seconds", value)


@pytest.mark.parametrize("window", [15, 60])
@pytest.mark.parametrize("reason", ["quota", "auth", "service", "memory_pressure"])
def test_suspension_never_counts_as_success(window: int, reason: str) -> None:
    metrics = Metrics()
    outcome = record_composite(
        metrics,
        window_minutes=window,
        wall_seconds=120,
        active_seconds=60,
        suspension_seconds=60,
        suspension_reason=reason,
        completed=True,
        speech_deadline_met=True,
        deadline_seconds=180,
    )
    assert outcome == "needs_attention"
    assert 'status="succeeded"' not in metrics.render()
    assert 'status="needs_attention"' in metrics.render()


@pytest.mark.parametrize(
    "completed,speech,active,expected",
    [
        (True, True, 60, "succeeded"),
        (True, False, 60, "failed"),
        (False, True, 60, "pending"),
        (False, True, 181, "overdue"),
        (True, True, 181, "failed"),
    ],
)
def test_composite_preserves_incomplete_and_stage_failure_signals(
    completed: bool,
    speech: bool,
    active: float,
    expected: str,
) -> None:
    metrics = Metrics()
    assert (
        record_composite(
            metrics,
            window_minutes=15,
            wall_seconds=active,
            active_seconds=active,
            suspension_seconds=0,
            suspension_reason="none",
            completed=completed,
            speech_deadline_met=speech,
            deadline_seconds=180,
        )
        == expected
    )


def test_invalid_composite_is_atomic() -> None:
    metrics = Metrics()
    with pytest.raises(ValueError):
        record_composite(
            metrics,
            window_minutes=15,
            wall_seconds=1,
            active_seconds=10,
            suspension_seconds=0,
            suspension_reason="none",
            completed=True,
            speech_deadline_met=True,
            deadline_seconds=180,
        )
    assert metrics.render() == ""
