import asyncio

from starlette.types import Message, Receive, Scope, Send
from tamforge_backend.observability.metrics import Metrics
from tamforge_backend.observability.middleware import OperationalMiddleware


def test_middleware_preserves_streaming_and_does_not_fail_when_metrics_are_full() -> None:
    class FullMetrics(Metrics):
        def observe(self, name: str, value: float, **labels: str) -> None:
            raise ValueError("metric series limit reached")

    received: list[Message] = []
    sent: list[Message] = []
    chunks: list[Message] = [
        {"type": "http.request", "body": b"first", "more_body": True},
        {"type": "http.request", "body": b"last", "more_body": False},
    ]
    responses: list[Message] = [
        {"type": "http.response.start", "status": 200, "headers": []},
        {"type": "http.response.body", "body": b"event: first\n\n", "more_body": True},
        {"type": "http.response.body", "body": b"event: last\n\n", "more_body": False},
    ]

    async def receive() -> Message:
        chunk = chunks[len(received)]
        received.append(chunk)
        return chunk

    async def send(message: Message) -> None:
        sent.append(message)

    async def streaming_app(scope: Scope, receive: Receive, send: Send) -> None:
        assert received == []  # No eager body consumption.
        assert await receive() is chunks[0]
        await send(responses[0])
        await send(responses[1])
        assert sent == responses[:2]  # No buffering pending app completion.
        assert await receive() is chunks[1]
        await send(responses[2])

    asyncio.run(
        OperationalMiddleware(streaming_app, metrics=FullMetrics())(
            {"type": "http"},
            receive,
            send,
        )
    )
    assert sent == responses


def test_middleware_preserves_original_failure_when_metrics_are_full() -> None:
    import pytest

    class FullMetrics(Metrics):
        def observe(self, name: str, value: float, **labels: str) -> None:
            raise ValueError("metric series limit reached")

    original = RuntimeError("private application error")

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        raise original

    async def receive() -> Message:
        raise AssertionError("must not consume input")

    async def send(message: Message) -> None:
        raise AssertionError("must not synthesize a response")

    with pytest.raises(RuntimeError) as caught:
        asyncio.run(
            OperationalMiddleware(app, metrics=FullMetrics())(
                {"type": "http"},
                receive,
                send,
            )
        )
    assert caught.value is original
