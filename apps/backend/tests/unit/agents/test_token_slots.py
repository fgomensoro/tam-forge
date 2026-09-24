from __future__ import annotations

from tamforge_backend.agents.token_slots import install_slot_token, installed_tokens


def test_installed_tokens_reads_one_variable_per_slot() -> None:
    environ = {
        "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-fixture",
        "CLAUDE_CODE_OAUTH_TOKEN_B": "sk-ant-oat01-fixture-b",
        "UNRELATED": "x",
    }
    assert installed_tokens(environ) == {
        "a": "sk-ant-oat01-fixture",
        "b": "sk-ant-oat01-fixture-b",
    }
    assert installed_tokens({}) == {"a": "", "b": ""}


def test_the_chosen_slot_token_becomes_the_one_claude_reads() -> None:
    tokens = {"a": "sk-ant-oat01-fixture", "b": "sk-ant-oat01-fixture-b"}
    environ = {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-fixture"}

    install_slot_token("b", tokens=tokens, environ=environ)
    assert environ["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-fixture-b"

    install_slot_token("a", tokens=tokens, environ=environ)
    assert environ["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-fixture"


def test_a_slot_without_a_token_leaves_no_token_to_read() -> None:
    environ = {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-fixture"}
    install_slot_token("b", tokens={"a": "sk-ant-oat01-fixture", "b": "  "}, environ=environ)
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in environ
