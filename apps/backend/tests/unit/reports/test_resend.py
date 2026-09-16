"""The Resend channel: bounded payload, closed outcomes, and off until it is configured."""

from __future__ import annotations

import asyncio
from typing import Any

from tamforge_backend.reports.delivery import NullReportSender
from tamforge_backend.reports.resend import (
    DEFAULT_FROM,
    RESEND_ENDPOINT,
    ResendReportSender,
    build_report_sender,
)


class Posts:
    def __init__(self, status: int = 200, text: str = '{"id":"m1"}') -> None:
        self.status, self.text = status, text
        self.calls: list[tuple[str, dict[str, str], dict[str, Any]]] = []

    def __call__(
        self, url: str, headers: dict[str, str], payload: dict[str, Any]
    ) -> tuple[int, str]:
        self.calls.append((url, headers, payload))
        if self.status == 0:
            raise ConnectionError("down")
        return self.status, self.text


def test_a_sent_report_carries_the_bearer_key_one_recipient_and_a_bounded_text() -> None:
    posts = Posts()
    sender = ResendReportSender(api_key="re_test", recipient="fjgomen@gmail.com", post=posts)
    delivery = asyncio.run(sender.send(owner_id=1, subject="s" * 300, body="hello"))
    assert delivery.status == "sent" and "200" in delivery.detail
    url, headers, payload = posts.calls[0]
    assert url == RESEND_ENDPOINT and headers == {"Authorization": "Bearer re_test"}
    assert payload["to"] == ["fjgomen@gmail.com"] and payload["from"] == DEFAULT_FROM
    assert len(payload["subject"]) == 200 and payload["text"] == "hello"


def test_refusals_and_network_failures_become_failed_deliveries_without_the_key() -> None:
    refused = ResendReportSender(
        api_key="re_test", recipient="a@b", post=Posts(422, '{"message":"bad"}')
    )
    delivery = asyncio.run(refused.send(owner_id=1, subject="s", body="b"))
    assert (
        delivery.status == "failed"
        and "422" in delivery.detail
        and "re_test" not in delivery.detail
    )
    down = ResendReportSender(api_key="re_test", recipient="a@b", post=Posts(0))
    delivery = asyncio.run(down.send(owner_id=1, subject="s", body="b"))
    assert delivery.status == "failed" and "ConnectionError" in delivery.detail


def test_the_channel_is_off_until_both_the_key_and_the_recipient_are_set() -> None:
    assert isinstance(build_report_sender({}), NullReportSender)
    assert isinstance(build_report_sender({"TAMFORGE_RESEND_API_KEY": "x"}), NullReportSender)
    sender = build_report_sender(
        {
            "TAMFORGE_RESEND_API_KEY": "x",
            "TAMFORGE_REPORT_TO": "a@b",
            "TAMFORGE_REPORT_FROM": "F <f@h>",
        }
    )
    assert isinstance(sender, ResendReportSender)
