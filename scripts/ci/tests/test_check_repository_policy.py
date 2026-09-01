from __future__ import annotations

from pathlib import PurePosixPath

from scripts.ci.check_repository_policy import violations


def test_policy_rejects_audio_and_private_key(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from scripts.ci import check_repository_policy

    monkeypatch.setattr(check_repository_policy, "ROOT", tmp_path)
    (tmp_path / "recording.wav").write_bytes(b"audio")
    (tmp_path / "notes.txt").write_text(
        "-----BEGIN " + "PRIVATE KEY-----\nnot-a-real-key\n",
        encoding="utf-8",
    )
    found = violations((PurePosixPath("recording.wav"), PurePosixPath("notes.txt")))
    assert found == (
        "forbidden tracked artifact: recording.wav",
        "private key pattern in notes.txt",
    )


def test_policy_allows_placeholders_and_source_files(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from scripts.ci import check_repository_policy

    monkeypatch.setattr(check_repository_policy, "ROOT", tmp_path)
    (tmp_path / ".env.example").write_text("TOKEN=replace-me\n", encoding="utf-8")
    (tmp_path / "server.py").write_text(
        "TOKEN = 'ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'\n",
        encoding="utf-8",
    )
    assert violations(
        (PurePosixPath(".env.example"), PurePosixPath("server.py"))
    ) == ()


def test_policy_rejects_non_placeholder_provider_token(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from scripts.ci import check_repository_policy

    monkeypatch.setattr(check_repository_policy, "ROOT", tmp_path)
    (tmp_path / "unsafe.txt").write_text(
        "ghp_" + "AbCdEfGhIjKlMnOpQrStUvWxYz123456",
        encoding="utf-8",
    )
    assert violations((PurePosixPath("unsafe.txt"),)) == (
        "GitHub token pattern in unsafe.txt",
    )


def test_policy_rejects_reintroduced_product_node_runtime(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from scripts.ci import check_repository_policy

    monkeypatch.setattr(check_repository_policy, "ROOT", tmp_path)
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "apps").mkdir()
    (tmp_path / "apps" / "web").mkdir()
    (tmp_path / "apps" / "web" / "main.tsx").write_text("export {}", encoding="utf-8")
    (tmp_path / "Makefile").write_text("check:\n\tpnpm test\n", encoding="utf-8")
    assert violations(
        (
            PurePosixPath("package.json"),
            PurePosixPath("apps/web/main.tsx"),
            PurePosixPath("Makefile"),
        )
    ) == (
        "forbidden product Node runtime: package.json",
        "forbidden product Node runtime: apps/web/main.tsx",
        "forbidden product Node invocation in Makefile",
    )
