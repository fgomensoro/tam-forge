"""The email channel: Resend's transactional API, bounded to one recipient and one sender.

The API key lives in `/etc/tamforge/secrets/resend.env` on the host and reaches the
process through its environment; nothing here logs it or the message body. A delivery
never raises: the report is already stored, so a failed send is a status on the row.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from .delivery import Delivery, NullReportSender, ReportSender

RESEND_ENDPOINT = "https://api.resend.com/emails"
DEFAULT_FROM = "TAM Forge <reports@homegastos.xyz>"
SEND_TIMEOUT_SECONDS = 20.0
MAX_BODY_BYTES = 200_000

Poster = Callable[[str, dict[str, str], dict[str, Any]], tuple[int, str]]


def _post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> tuple[int, str]:
    response = httpx.post(url, headers=headers, json=payload, timeout=SEND_TIMEOUT_SECONDS)
    return response.status_code, response.text[:300]


class ResendReportSender:
    def __init__(
        self,
        *,
        api_key: str,
        recipient: str,
        sender: str = DEFAULT_FROM,
        endpoint: str = RESEND_ENDPOINT,
        post: Poster = _post,
    ) -> None:
        self._api_key = api_key
        self._recipient = recipient
        self._sender = sender
        self._endpoint = endpoint
        self._post = post

    async def send(self, *, owner_id: int, subject: str, body: str) -> Delivery:
        del owner_id  # one learner, one recipient: the address is configured, never looked up
        payload = {
            "from": self._sender,
            "to": [self._recipient],
            "subject": subject[:200],
            "text": body.encode("utf-8")[:MAX_BODY_BYTES].decode("utf-8", "ignore"),
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            status, text = await asyncio.to_thread(self._post, self._endpoint, headers, payload)
        except Exception as exc:  # noqa: BLE001 - a delivery failure is a status, not a crash
            return Delivery(status="failed", detail=f"resend request failed: {type(exc).__name__}")
        if 200 <= status < 300:
            return Delivery(status="sent", detail=f"resend accepted ({status})")
        return Delivery(status="failed", detail=f"resend refused ({status}): {text[:200]}")


def build_report_sender(environ: Mapping[str, str]) -> ReportSender:
    """The channel the environment configures: Resend when the key and recipient are set."""
    api_key = environ.get("TAMFORGE_RESEND_API_KEY", "").strip()
    recipient = environ.get("TAMFORGE_REPORT_TO", "").strip()
    if not api_key or not recipient:
        return NullReportSender()
    return ResendReportSender(
        api_key=api_key,
        recipient=recipient,
        sender=environ.get("TAMFORGE_REPORT_FROM", "").strip() or DEFAULT_FROM,
    )


__all__ = ["DEFAULT_FROM", "RESEND_ENDPOINT", "ResendReportSender", "build_report_sender"]
