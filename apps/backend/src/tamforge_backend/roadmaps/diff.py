"""Field-level semantic diff for normalized roadmap structures."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from .contracts import (
    ChangeStatus,
    DiffSection,
    EntityChange,
    FieldChange,
    JsonValue,
    ParsedRoadmap,
    SemanticRoadmapDiff,
)


def _section[T](
    before_items: Iterable[T],
    after_items: Iterable[T],
    *,
    key: Callable[[T], str],
    payload: Callable[[T], dict[str, JsonValue]],
) -> DiffSection:
    before = {key(item): payload(item) for item in before_items}
    after = {key(item): payload(item) for item in after_items}
    entries: list[EntityChange] = []
    for item_key in sorted(before.keys() | after.keys()):
        before_payload = before.get(item_key)
        after_payload = after.get(item_key)
        status: ChangeStatus
        if before_payload is None:
            status = "added"
            fields: tuple[FieldChange, ...] = ()
        elif after_payload is None:
            status = "removed"
            fields = ()
        else:
            fields = tuple(
                FieldChange(
                    name=field_name,
                    before=before_payload.get(field_name),
                    after=after_payload.get(field_name),
                )
                for field_name in sorted(before_payload.keys() | after_payload.keys())
                if before_payload.get(field_name) != after_payload.get(field_name)
            )
            status = "changed" if fields else "unchanged"
        entries.append(
            EntityChange(
                key=item_key,
                status=status,
                fields=fields,
                before=before_payload,
                after=after_payload,
            )
        )
    return DiffSection(entries=tuple(entries))


def diff_roadmaps(before: ParsedRoadmap, after: ParsedRoadmap) -> SemanticRoadmapDiff:
    """Compare normalized structures; source ordering and Markdown line order are irrelevant."""
    return SemanticRoadmapDiff(
        tasks=_section(
            before.tasks,
            after.tasks,
            key=lambda item: item.stable_id,
            payload=lambda item: item.core_dict(),
        ),
        pass_contracts=_section(
            before.contracts,
            after.contracts,
            key=lambda item: item.stable_id,
            payload=lambda item: item.to_dict(),
        ),
        resources=_section(
            before.resources,
            after.resources,
            key=lambda item: item.key,
            payload=lambda item: item.to_dict(),
        ),
        exit_criteria=_section(
            before.exit_criteria,
            after.exit_criteria,
            key=lambda item: item.key,
            payload=lambda item: item.to_dict(),
        ),
    )
