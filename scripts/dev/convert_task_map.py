#!/usr/bin/env python3
"""Turn a server-side task map plus its package into a package that carries roadmap.yaml.

The two maps the repo has known so far (the Month 1 map at `config/` and the
six-week release under `config/releases/`) become ordinary scheme packages: the
same Markdown files plus a `roadmap.yaml` at the root. Output is deterministic
(sorted entries, fixed timestamps) so `--check` can prove a checked-in package
still matches its source.
"""

from __future__ import annotations

import argparse
import io
import sys
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "backend" / "src"))

from tamforge_backend.evidence.config_loader import load_config_bundle  # noqa: E402
from tamforge_backend.roadmaps.scheme import (  # noqa: E402
    SCHEME_FILE_NAME,
    SchemeFile,
    scheme_from_payload,
    validate_scheme,
)

# Contract names the six-week release uses, mapped onto the server vocabulary.
_V2_CONTRACTS = {
    "interview": "communication",
    "sealed_interview": "communication",
    "pipeline": "pipeline",
    "roadmap": "technical",
    "close": "close",
}
# Saturday segments in the six-week release, by the suffix of their stable id.
_SATURDAY_TYPES = (
    ("no-ai-sql", "saturday_sql"),
    ("gauntlet", "saturday_gauntlet"),
    ("portfolio", "saturday_portfolio"),
    ("writing", "saturday_writing"),
    ("behavioral", "saturday_behavioral"),
    ("case", "saturday_case"),
    ("mock", "saturday_case"),
    ("technical-transfer", "saturday_case"),
)
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


class ConversionError(ValueError):
    """The task map cannot be expressed as a scheme."""


def _contract_type(task: Mapping[str, Any]) -> str:
    contract = str(task["contract"])
    if contract == "saturday":
        suffix = str(task["stable_id"])
        for marker, contract_type in _SATURDAY_TYPES:
            if marker in suffix:
                return contract_type
        return "saturday_scoring"
    return _V2_CONTRACTS.get(contract, contract)


def _objective(task: Mapping[str, Any], heading: str, contracts: Mapping[str, Any]) -> str:
    objective = task.get("objective")
    if objective:
        return str(objective)
    contract = contracts.get(str(task["contract"])) or {}
    outputs = contract.get("required_output") or ()
    first = str(outputs[0]) if outputs else "Complete the block."
    return f"{heading}: {first}"


def scheme_payload_from_task_map(task_map: Mapping[str, Any]) -> dict[str, Any]:
    contracts = task_map.get("contracts") or {}
    if isinstance(contracts.get("tasks"), Mapping):
        contracts = contracts["tasks"]
    version = str(task_map["roadmap_version"])
    program = task_map.get("program") or {}
    days: list[dict[str, Any]] = []
    for day in sorted(task_map["days"], key=lambda item: int(item["day"])):
        blocks: list[dict[str, Any]] = []
        for task in sorted(day["tasks"], key=lambda item: int(item["order"])):
            contract_type = _contract_type(task)
            source_path = str(task.get("source_path") or day["source_path"])
            heading = str(task.get("source_heading") or day["source_heading"])
            block: dict[str, Any] = {
                "id": str(task["stable_id"]),
                "type": contract_type,
                "minutes": int(task["timebox_minutes"]),
                "source": {"file": source_path, "heading": heading},
                "objective": _objective(task, heading, contracts),
            }
            if not bool(task.get("required", True)):
                block["required"] = False
            exercise = task.get("exercise_type")
            if exercise and contract_type != "correction":
                block["exercise_type"] = str(exercise)
            role = task.get("allowed_ai_role")
            if role:
                block["allowed_ai_role"] = str(role)
            blocks.append(block)
        assessment = all(str(task["block"]) == "saturday_assessment" for task in day["tasks"])
        budget = sum(
            block["minutes"]
            for block in blocks
            if block.get("required", True) and block["type"] != "correction"
        )
        days.append(
            {
                "id": f"{version}-d{int(day['day']):02d}",
                "kind": "assessment" if assessment else "weekday",
                "budget_minutes": budget,
                "blocks": blocks,
            }
        )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "program": {
            "key": str(program.get("program_key") or version.replace("-", "_")),
            "title": str(program.get("display_name") or version),
        },
        "rest_weekdays": ["sunday"],
        "days": days,
    }
    lineage = task_map.get("lineage") or {}
    predecessor = lineage.get("predecessor_roadmap_version")
    if predecessor:
        payload["lineage"] = {"predecessor_version": str(predecessor)}
    return payload


def _package_files(package_zip: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(package_zip) as archive:
        return {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}


def build_package(files: Mapping[str, bytes], scheme_text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        entries = dict(files)
        entries[SCHEME_FILE_NAME] = scheme_text.encode("utf-8")
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, entries[name])
    return buffer.getvalue()


def convert_task_map(
    task_map_path: Path, package_zip: Path, output_zip: Path, *, check: bool = False
) -> SchemeFile:
    task_map = yaml.safe_load(task_map_path.read_text(encoding="utf-8"))
    payload = scheme_payload_from_task_map(task_map)
    scheme = scheme_from_payload(payload)
    files = _package_files(package_zip)
    issues = validate_scheme(scheme, files=files, config=load_config_bundle(ROOT / "config"))
    if issues:
        raise ConversionError("; ".join(issues))
    scheme_text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=120)
    package = build_package(files, scheme_text)
    if check:
        if not output_zip.is_file() or output_zip.read_bytes() != package:
            raise ConversionError(f"{output_zip} does not match its task map and package")
        return scheme
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    output_zip.write_bytes(package)
    return scheme


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_map", type=Path)
    parser.add_argument("package_zip", type=Path)
    parser.add_argument("output_zip", type=Path)
    parser.add_argument(
        "--check", action="store_true", help="Fail when the output differs from a fresh conversion."
    )
    args = parser.parse_args(argv)
    try:
        scheme = convert_task_map(
            args.task_map, args.package_zip, args.output_zip, check=args.check
        )
    except ConversionError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        f"{args.output_zip}: {len(scheme.days)} study days, "
        f"{sum(len(day.blocks) for day in scheme.days)} blocks"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
