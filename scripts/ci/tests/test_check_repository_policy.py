from __future__ import annotations

from pathlib import Path, PurePosixPath

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
    assert violations((PurePosixPath(".env.example"), PurePosixPath("server.py"))) == ()


def test_policy_rejects_non_placeholder_provider_token(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from scripts.ci import check_repository_policy

    monkeypatch.setattr(check_repository_policy, "ROOT", tmp_path)
    (tmp_path / "unsafe.txt").write_text(
        "ghp_" + "AbCdEfGhIjKlMnOpQrStUvWxYz123456",
        encoding="utf-8",
    )
    assert violations((PurePosixPath("unsafe.txt"),)) == ("GitHub token pattern in unsafe.txt",)


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


def test_policy_rejects_node_launchers_in_every_workflow_extension(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from scripts.ci import check_repository_policy

    monkeypatch.setattr(check_repository_policy, "ROOT", tmp_path)
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "release.yaml").write_text(
        "jobs:\n  check:\n    steps:\n      - run: command npx verify\n",
        encoding="utf-8",
    )
    (workflow_dir / "bypass.yml").write_text(
        "jobs:\n  check:\n    steps:\n      - run: |\n" "          env CI=1 yarn test\n",
        encoding="utf-8",
    )
    assert violations(
        (
            PurePosixPath(".github/workflows/release.yaml"),
            PurePosixPath(".github/workflows/bypass.yml"),
        )
    ) == (
        "forbidden product Node invocation in .github/workflows/release.yaml",
        "forbidden product Node invocation in .github/workflows/bypass.yml",
    )


def test_policy_rejects_node_launcher_in_all_yaml_block_scalar_forms(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from scripts.ci import check_repository_policy

    monkeypatch.setattr(check_repository_policy, "ROOT", tmp_path)
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    paths: list[PurePosixPath] = []
    for index, indicator in enumerate(("|2", "|2-", "|-2", ">+2", "|2 # shell")):
        name = f"block-{index}.yaml"
        (workflow_dir / name).write_text(
            f"jobs:\n  check:\n    steps:\n      - run: {indicator}\n"
            "          command npm test\n",
            encoding="utf-8",
        )
        paths.append(PurePosixPath(".github/workflows") / name)

    assert violations(tuple(paths)) == tuple(
        f"forbidden product Node invocation in {path}" for path in paths
    )


def test_policy_rejects_node_launcher_in_deferred_plain_scalar_run(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from scripts.ci import check_repository_policy

    monkeypatch.setattr(check_repository_policy, "ROOT", tmp_path)
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "deferred.yml").write_text(
        "jobs:\n  check:\n    steps:\n      - run:\n          npm ci\n",
        encoding="utf-8",
    )
    (workflow_dir / "commented.yml").write_text(
        "jobs:\n  check:\n    steps:\n      - run: # shell\n          npm ci\n",
        encoding="utf-8",
    )
    assert violations(
        (
            PurePosixPath(".github/workflows/deferred.yml"),
            PurePosixPath(".github/workflows/commented.yml"),
        )
    ) == (
        "forbidden product Node invocation in .github/workflows/deferred.yml",
        "forbidden product Node invocation in .github/workflows/commented.yml",
    )


def test_policy_rejects_every_node_launcher_from_make_recipes(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from scripts.ci import check_repository_policy

    monkeypatch.setattr(check_repository_policy, "ROOT", tmp_path)
    (tmp_path / "Makefile").write_text(
        "check:\n"
        "\tnode script.js\n"
        "\tnpm test\n"
        "\tpnpm test\n"
        "\tnpx verify\n"
        "\tyarn test\n"
        "\tbun run check\n",
        encoding="utf-8",
    )
    assert violations((PurePosixPath("Makefile"),)) == (
        "forbidden product Node invocation in Makefile",
    )


def test_policy_ignores_node_words_outside_active_commands(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from scripts.ci import check_repository_policy

    monkeypatch.setattr(check_repository_policy, "ROOT", tmp_path)
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "notes.yaml").write_text(
        "name: node migration\njobs:\n  check:\n    steps:\n      - name: npm is forbidden\n",
        encoding="utf-8",
    )
    (tmp_path / "Makefile").write_text(
        "# pnpm is forbidden\ncheck:\n\t@echo native\n", encoding="utf-8"
    )
    assert (
        violations(
            (
                PurePosixPath(".github/workflows/notes.yaml"),
                PurePosixPath("Makefile"),
            )
        )
        == ()
    )


def test_ci_runs_recording_contract_tests_and_remains_node_free() -> None:
    root = Path(__file__).parents[3]
    workflow = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "apps/backend/tests/recordings" in workflow
    assert violations((PurePosixPath(".github/workflows/ci.yml"),)) == ()
