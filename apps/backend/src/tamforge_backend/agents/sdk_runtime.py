"""The Claude Agent SDK behind the two seams the rest of the app already has.

`ClaudeRuntime.probe` for the compatibility probe and `PlannerTransport.propose`
for the planner. Both run one bounded, tool-less query with a structured output
schema and read back exactly what the SDK returned. The subscription credential
reaches the SDK only through the environment the caller hands over; nothing here
reads or logs it, and SDK error text (which can carry it) never leaves this module.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import os
import shutil
import subprocess
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..roadmaps.planner import PlannerRequest
from .compatibility import (
    SUBSCRIPTION_AUTHENTICATION,
    ProbeAuthenticationFailed,
    ProbeError,
    ProbeObservation,
    ProbeQuotaExhausted,
)
from .roles.coach import CoachRequest, NoteRequest
from .runtime import (
    AgentAuthenticationFailed,
    AgentQuotaExhausted,
    AgentServiceUnavailable,
)
from .settings import FORBIDDEN_CREDENTIAL_VARS, SUBSCRIPTION_TOKEN_VAR, WORKER_TELEMETRY_OPT_OUTS

SDK_DISTRIBUTION = "claude-agent-sdk"
PROBE_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "probe": {"type": "string", "enum": ["ok"]},
        "schema_version": {"type": "integer", "enum": [1]},
    },
    "required": ["probe", "schema_version"],
    "additionalProperties": False,
}
PROBE_PROMPT = 'Return the object {"probe": "ok", "schema_version": 1} and nothing else.'
PLANNER_SYSTEM_PROMPT = (
    "You are the TAM Forge planner. You turn a learner's roadmap package into a study "
    "scheme: ordered study days, each with a kind (weekday or assessment), a minute "
    "budget that equals the sum of its blocks, and blocks with a contract type, minutes, "
    "a source file and heading that exist in the package, and a one-line objective. "
    "Use only the files you are given. Never invent files or headings. Return only the "
    "scheme object."
)

COACH_SYSTEM_PROMPT = (
    "You are the TAM Forge coach. The learner has committed an attempt for one study "
    "block. Respond to what they wrote: name what is strong, name the gap against the "
    "pass criteria, and give one concrete improvement. Repeat the plan's next step "
    "verbatim in next_step; never invent a different one. Propose at most five short "
    "evidence notes the learner may record. Never claim to have recorded, scored or "
    "completed anything. Answer in the learner's language. Return only the object."
)

QueryFactory = Callable[..., AsyncIterator[Any]]


@dataclass(frozen=True, slots=True)
class StructuredRun:
    resolved_model: str | None
    structured_output: Mapping[str, object] | None
    num_turns: int
    is_error: bool
    api_error_status: int | None
    stop_reason: str | None


class AgentSdkRuntime:
    """One bounded structured query per call; no tools, no settings, no project files."""

    def __init__(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        query: QueryFactory | None = None,
        cli_version: Callable[[], str | None] | None = None,
        sdk_version: Callable[[], str | None] | None = None,
    ) -> None:
        self._environ = dict(os.environ if environ is None else environ)
        self._query = query
        self._cli_version = cli_version or _installed_cli_version
        self._sdk_version = sdk_version or _installed_sdk_version

    # -- compatibility probe -------------------------------------------------------

    async def probe(self, *, requested_model: str) -> ProbeObservation:
        sdk_version = self._sdk_version()
        authentication = self._authentication_method()
        if sdk_version is None or authentication != SUBSCRIPTION_AUTHENTICATION:
            return ProbeObservation(
                sdk_version=sdk_version,
                cli_version=self._cli_version(),
                authentication_method=authentication,
                resolved_model=None,
                supported_models=(),
                structured_response=None,
            )
        try:
            run = await self._structured(
                prompt=PROBE_PROMPT,
                schema=PROBE_SCHEMA,
                model=requested_model,
                system_prompt="Answer with the requested object only.",
                max_turns=1,
            )
        except AgentAuthenticationFailed:
            raise ProbeAuthenticationFailed("the subscription credential was refused") from None
        except AgentQuotaExhausted:
            raise ProbeQuotaExhausted("the subscription quota is spent") from None
        except AgentServiceUnavailable:
            raise ProbeError("the probe did not complete") from None
        return ProbeObservation(
            sdk_version=sdk_version,
            cli_version=self._cli_version(),
            authentication_method=authentication,
            resolved_model=run.resolved_model,
            supported_models=() if run.resolved_model is None else (run.resolved_model,),
            structured_response=(
                dict(run.structured_output) if run.structured_output is not None else None
            ),
        )

    # -- planner transport ---------------------------------------------------------

    async def propose(self, request: PlannerRequest) -> Mapping[str, object]:
        from ..roadmaps.scheme import SchemeFile

        prompt = _planner_prompt(request)
        run = await self._structured(
            prompt=prompt,
            schema=SchemeFile.model_json_schema(),
            model=self._environ.get("TAMFORGE_PLANNER_MODEL", "claude-fable-5-1"),
            system_prompt=PLANNER_SYSTEM_PROMPT,
            max_turns=4,
        )
        if run.structured_output is None:
            return {}
        return dict(run.structured_output)

    # -- coach transport -----------------------------------------------------------

    async def respond(self, request: CoachRequest) -> Mapping[str, object]:
        from .roles.coach import coach_turn_schema, render_coach_prompt

        run = await self._structured(
            prompt=render_coach_prompt(request),
            schema=coach_turn_schema(),
            model=self._environ.get("TAMFORGE_COACH_MODEL", "claude-opus-5"),
            system_prompt=COACH_SYSTEM_PROMPT,
            max_turns=4,
        )
        return {} if run.structured_output is None else dict(run.structured_output)

    async def draft_note(self, request: NoteRequest) -> Mapping[str, object]:
        from .roles.coach import note_draft_schema, render_note_prompt

        run = await self._structured(
            prompt=render_note_prompt(request),
            schema=note_draft_schema(),
            model=self._environ.get("TAMFORGE_COACH_MODEL", "claude-opus-5"),
            system_prompt=COACH_SYSTEM_PROMPT,
            max_turns=4,
        )
        return {} if run.structured_output is None else dict(run.structured_output)

    # -- shared -------------------------------------------------------------------

    async def _structured(
        self,
        *,
        prompt: str,
        schema: Mapping[str, object],
        model: str,
        system_prompt: str,
        max_turns: int,
    ) -> StructuredRun:
        from claude_agent_sdk import (
            ClaudeAgentOptions,
            CLIConnectionError,
            CLINotFoundError,
            ProcessError,
            ResultMessage,
            SystemMessage,
        )
        from claude_agent_sdk import query as sdk_query

        options = ClaudeAgentOptions(
            model=model,
            max_turns=max_turns,
            system_prompt=system_prompt,
            allowed_tools=[],
            disallowed_tools=["Bash", "Read", "Write", "Edit", "WebSearch", "WebFetch"],
            permission_mode="dontAsk",
            setting_sources=[],
            env={**self._worker_environment(), **WORKER_TELEMETRY_OPT_OUTS},
            output_format={"type": "json_schema", "schema": dict(schema)},
        )
        query = self._query or sdk_query
        resolved_model: str | None = None
        result: Any = None
        try:
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, SystemMessage) and message.subtype == "init":
                    value = message.data.get("model")
                    resolved_model = str(value) if value else None
                elif isinstance(message, ResultMessage):
                    result = message
        except CLINotFoundError:
            raise AgentServiceUnavailable("the Claude Code CLI is not installed") from None
        except (CLIConnectionError, ProcessError) as exc:
            raise _translate_process_error(exc) from None
        except (AgentAuthenticationFailed, AgentQuotaExhausted, AgentServiceUnavailable):
            raise
        except asyncio.CancelledError:
            raise
        except Exception:
            raise AgentServiceUnavailable("the agent runtime failed to complete") from None
        if result is None:
            raise AgentServiceUnavailable("the run ended without a result")
        status = getattr(result, "api_error_status", None)
        if status in (401, 403):
            raise AgentAuthenticationFailed("the subscription credential was refused")
        if status == 429:
            raise AgentQuotaExhausted("the subscription quota is spent")
        if result.is_error and result.structured_output is None:
            raise AgentServiceUnavailable("the run reported an error")
        structured = result.structured_output
        if isinstance(structured, str):
            try:
                structured = json.loads(structured)
            except ValueError:
                structured = None
        return StructuredRun(
            resolved_model=resolved_model,
            structured_output=structured if isinstance(structured, Mapping) else None,
            num_turns=int(result.num_turns),
            is_error=bool(result.is_error),
            api_error_status=status if isinstance(status, int) else None,
            stop_reason=getattr(result, "stop_reason", None),
        )

    def _authentication_method(self) -> str:
        if any(variable in self._environ for variable in FORBIDDEN_CREDENTIAL_VARS):
            return "api_key"
        return (
            SUBSCRIPTION_AUTHENTICATION
            if self._environ.get(SUBSCRIPTION_TOKEN_VAR, "").strip()
            else "none"
        )

    def _worker_environment(self) -> dict[str, str]:
        token = self._environ.get(SUBSCRIPTION_TOKEN_VAR, "").strip()
        return {SUBSCRIPTION_TOKEN_VAR: token} if token else {}


def _translate_process_error(exc: Exception) -> Exception:
    text = " ".join(
        str(part).lower()
        for part in (getattr(exc, "stderr", None), getattr(exc, "message", None), str(exc))
        if part
    )
    if any(
        marker in text
        for marker in (
            "401",
            "403",
            "unauthorized",
            "authentication",
            "not logged in",
            "invalid api key",
            "oauth",
        )
    ):
        return AgentAuthenticationFailed("the subscription credential was refused")
    if any(marker in text for marker in ("429", "rate limit", "usage limit", "quota")):
        return AgentQuotaExhausted("the subscription quota is spent")
    return AgentServiceUnavailable("the agent runtime failed to complete")


def _planner_prompt(request: PlannerRequest) -> str:
    sections = [
        f"Mode: {request.mode}.",
        f"Today: {request.today.isoformat()}.",
        f"Instruction: {request.instruction or 'none'}.",
    ]
    if request.current_scheme is not None:
        sections.append(
            "Current scheme (JSON):\n" + json.dumps(dict(request.current_scheme), sort_keys=True)
        )
    if request.evidence_summary:
        lines = "\n".join(f"- {line.block_id}: {line.status}" for line in request.evidence_summary)
        sections.append("Evidence so far:\n" + lines)
    if request.repair_errors:
        sections.append(
            "Your previous proposal was refused for these reasons; fix them:\n"
            + "\n".join(f"- {error}" for error in request.repair_errors)
        )
    files = "\n\n".join(f"### {path}\n{text}" for path, text in sorted(request.files.items()))
    sections.append("Package files:\n" + files)
    return "\n\n".join(sections)


def _installed_sdk_version() -> str | None:
    try:
        return importlib.metadata.version(SDK_DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError:
        return None


def _installed_cli_version() -> str | None:
    executable = shutil.which("claude")
    if executable is None:
        return None
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [executable, "--version"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = completed.stdout.strip() or completed.stderr.strip()
    return output.split()[0] if output else None


__all__ = ["AgentSdkRuntime", "PROBE_PROMPT", "PROBE_SCHEMA", "StructuredRun"]
