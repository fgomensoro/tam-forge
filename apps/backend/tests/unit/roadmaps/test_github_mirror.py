from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx
from tamforge_backend.roadmaps.github_mirror import GitHubRoadmapMirror
from tamforge_backend.roadmaps.ports import MirrorRequest


@pytest.mark.anyio
@respx.mock
async def test_mirror_creates_one_non_force_commit_with_source_files_and_manifest() -> None:
    api = "https://api.github.com/repos/fgomensoro/tam-forge"
    respx.get(f"{api}/git/ref/heads/roadmap-snapshots").mock(
        return_value=httpx.Response(200, json={"object": {"sha": "parent-sha"}})
    )
    respx.get(f"{api}/git/commits/parent-sha").mock(
        return_value=httpx.Response(200, json={"tree": {"sha": "parent-tree"}})
    )
    blob_route = respx.post(f"{api}/git/blobs").mock(
        side_effect=[
            httpx.Response(201, json={"sha": "blob-readme"}),
            httpx.Response(201, json={"sha": "blob-manifest"}),
        ]
    )
    tree_route = respx.post(f"{api}/git/trees").mock(
        return_value=httpx.Response(201, json={"sha": "tree-sha"})
    )
    respx.post(f"{api}/git/commits").mock(
        return_value=httpx.Response(201, json={"sha": "commit-sha"})
    )
    ref_route = respx.patch(f"{api}/git/refs/heads/roadmap-snapshots").mock(
        return_value=httpx.Response(200, json={"object": {"sha": "commit-sha"}})
    )
    mirror = GitHubRoadmapMirror(
        token="mirror-token",
        repository="fgomensoro/tam-forge",
        branch="roadmap-snapshots",
    )
    request = MirrorRequest(
        version_id=7,
        roadmap_version="month-1-v2",
        files={"README.md": b"# Roadmap\n"},
        manifest={"schema_version": 1, "content_hash": "a" * 64, "files": []},
    )

    result = await mirror.mirror(request)

    assert result == "commit-sha"
    assert blob_route.call_count == 2
    readme_blob = blob_route.calls[0].request
    assert readme_blob.headers["authorization"] == "Bearer mirror-token"
    assert json.loads(readme_blob.content)["content"] == base64.b64encode(
        b"# Roadmap\n"
    ).decode()
    tree = json.loads(tree_route.calls[0].request.content)
    assert tree["base_tree"] == "parent-tree"
    assert {item["path"] for item in tree["tree"]} == {
        "roadmaps/imports/7/README.md",
        "roadmaps/imports/7/manifest.json",
    }
    assert json.loads(ref_route.calls[0].request.content) == {
        "sha": "commit-sha",
        "force": False,
    }


@pytest.mark.anyio
@respx.mock
async def test_mirror_maps_permission_failure_to_closed_machine_code() -> None:
    from tamforge_backend.roadmaps.ports import MirrorFailure

    api = "https://api.github.com/repos/fgomensoro/tam-forge"
    respx.get(f"{api}/git/ref/heads/roadmap-snapshots").mock(
        return_value=httpx.Response(403, json={"message": "provider details must stay private"})
    )
    mirror = GitHubRoadmapMirror(
        token="mirror-token",
        repository="fgomensoro/tam-forge",
        branch="roadmap-snapshots",
    )

    with pytest.raises(MirrorFailure) as captured:
        await mirror.mirror(
            MirrorRequest(
                version_id=7,
                roadmap_version="month-1-v2",
                files={"README.md": b"# Roadmap\n"},
                manifest={"schema_version": 1, "content_hash": "a" * 64, "files": []},
            )
        )

    assert captured.value.code == "permission_denied"
    assert "provider details" not in str(captured.value)
