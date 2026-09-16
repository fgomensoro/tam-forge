"""Where a report goes once it is written. The email channel (#292) plugs in here."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Delivery:
    status: str  # sent | failed | skipped
    detail: str


class ReportSender(Protocol):
    async def send(self, *, owner_id: int, subject: str, body: str) -> Delivery: ...


class NullReportSender:
    """No channel configured: the report is stored and the app shows it; nothing is sent."""

    async def send(self, *, owner_id: int, subject: str, body: str) -> Delivery:
        del owner_id, subject, body
        return Delivery(status="skipped", detail="no delivery channel configured")


def render_report_text(week_start: str, week_end: str, outcome: dict[str, object]) -> str:
    """The report as plain text: the email body, and what the app shows when there is none."""

    def lines(title: str, items: object) -> list[str]:
        if not isinstance(items, list) or not items:
            return []
        return [f"{title}:"] + [f"- {item}" for item in items] + [""]

    parts = [
        f"TAM Forge weekly report, {week_start} to {week_end}",
        "",
        str(outcome.get("headline", "")),
        "",
    ]
    parts += lines("Did", outcome.get("did"))
    parts += lines("Learned", outcome.get("learned"))
    parts += lines("Improved", outcome.get("improved"))
    skills = outcome.get("skills")
    if isinstance(skills, list) and skills:
        parts.append("Skills:")
        for line in skills:
            if isinstance(line, dict):
                parts.append(
                    f"- {line.get('skill_slug')}: {line.get('direction')}; {line.get('note')}"
                )
        parts.append("")
    suggestions = outcome.get("suggestions")
    if isinstance(suggestions, list) and suggestions:
        parts.append("Suggested adjustments (nothing is applied until you approve it):")
        for item in suggestions:
            if isinstance(item, dict):
                parts.append(
                    f"- {item.get('change')} ({item.get('reason')}; {item.get('skill_slug')})"
                )
        parts.append("")
    parts += lines("Risks", outcome.get("risks"))
    parts.append(f"Decision for you this week: {outcome.get('decision_for_frank', '')}")
    return "\n".join(parts)


__all__ = ["Delivery", "NullReportSender", "ReportSender", "render_report_text"]
