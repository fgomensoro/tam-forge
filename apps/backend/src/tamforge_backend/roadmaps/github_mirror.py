"""Private GitHub mirror adapter using one non-force Git Data commit."""

from __future__ import annotations

import base64
import json
import re
from urllib.parse import quote

import httpx

from .ports import MirrorFailure, MirrorRequest

_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_BRANCH = re.compile(r"^(?!/)(?!.*(?:\.\.|//|@\{|\\))[A-Za-z0-9._/-]{1,200}(?<![/.])$")


class GitHubRoadmapMirror:
    """Mirror a validated source tree without rewriting repository history."""

    enabled = True

    def __init__(
        self,
        *,
        token: str,
        repository: str,
        branch: str,
        base_branch: str = "main",
        api_url: str = "https://api.github.com",
    ) -> None:
        if not token or len(token) > 512:
            raise ValueError("roadmap mirror token is invalid")
        if not _REPOSITORY.fullmatch(repository):
            raise ValueError("roadmap mirror repository is invalid")
        if not _BRANCH.fullmatch(branch) or not _BRANCH.fullmatch(base_branch):
            raise ValueError("roadmap mirror branch is invalid")
        self._token = token
        self._repository = repository
        self._branch = branch
        self._base_branch = base_branch
        self._api_url = api_url.rstrip("/")

    async def mirror(self, request: MirrorRequest) -> str:
        prefix = f"roadmaps/imports/{request.version_id}"
        payloads = {
            f"{prefix}/{path}": content
            for path, content in sorted(request.files.items())
        }
        payloads[f"{prefix}/manifest.json"] = (
            json.dumps(request.manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode()
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient(
            base_url=self._api_url,
            headers=headers,
            timeout=20.0,
        ) as client:
            branch_ref, branch_exists = await self._branch_ref(client)
            commit = await self._json(
                client,
                "GET",
                f"/repos/{self._repository}/git/commits/{quote(branch_ref, safe='')}",
            )
            tree_value = commit.get("tree")
            if not isinstance(tree_value, dict) or not isinstance(tree_value.get("sha"), str):
                raise MirrorFailure("invalid_reference")
            tree_entries: list[dict[str, str]] = []
            for path, content in payloads.items():
                blob = await self._json(
                    client,
                    "POST",
                    f"/repos/{self._repository}/git/blobs",
                    json={
                        "content": base64.b64encode(content).decode("ascii"),
                        "encoding": "base64",
                    },
                )
                blob_sha = blob.get("sha")
                if not isinstance(blob_sha, str):
                    raise MirrorFailure("write_failed")
                tree_entries.append(
                    {"path": path, "mode": "100644", "type": "blob", "sha": blob_sha}
                )
            tree = await self._json(
                client,
                "POST",
                f"/repos/{self._repository}/git/trees",
                json={"base_tree": tree_value["sha"], "tree": tree_entries},
            )
            tree_sha = tree.get("sha")
            if not isinstance(tree_sha, str):
                raise MirrorFailure("write_failed")
            created = await self._json(
                client,
                "POST",
                f"/repos/{self._repository}/git/commits",
                json={
                    "message": f"roadmap snapshot: {request.roadmap_version}",
                    "tree": tree_sha,
                    "parents": [branch_ref],
                },
            )
            commit_sha = created.get("sha")
            if not isinstance(commit_sha, str):
                raise MirrorFailure("write_failed")
            if branch_exists:
                await self._json(
                    client,
                    "PATCH",
                    f"/repos/{self._repository}/git/refs/heads/{self._branch}",
                    json={"sha": commit_sha, "force": False},
                )
            else:
                await self._json(
                    client,
                    "POST",
                    f"/repos/{self._repository}/git/refs",
                    json={"ref": f"refs/heads/{self._branch}", "sha": commit_sha},
                )
            return commit_sha

    async def _branch_ref(self, client: httpx.AsyncClient) -> tuple[str, bool]:
        path = f"/repos/{self._repository}/git/ref/heads/{self._branch}"
        response = await self._request(client, "GET", path, allow_not_found=True)
        exists = response.status_code != 404
        if not exists:
            response = await self._request(
                client,
                "GET",
                f"/repos/{self._repository}/git/ref/heads/{self._base_branch}",
            )
        try:
            payload = response.json()
        except ValueError:
            raise MirrorFailure("invalid_reference") from None
        if not isinstance(payload, dict):
            raise MirrorFailure("invalid_reference")
        object_value = payload.get("object")
        if not isinstance(object_value, dict) or not isinstance(object_value.get("sha"), str):
            raise MirrorFailure("invalid_reference")
        return object_value["sha"], exists

    async def _json(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
    ) -> dict[str, object]:
        response = await self._request(client, method, path, json=json)
        try:
            payload = response.json()
        except ValueError:
            raise MirrorFailure("write_failed") from None
        if not isinstance(payload, dict):
            raise MirrorFailure("write_failed")
        return payload

    @staticmethod
    async def _request(
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
        allow_not_found: bool = False,
    ) -> httpx.Response:
        try:
            response = await client.request(method, path, json=json)
        except httpx.HTTPError:
            raise MirrorFailure("storage_unavailable") from None
        if allow_not_found and response.status_code == 404:
            return response
        if response.status_code in {401, 403}:
            raise MirrorFailure("permission_denied")
        if response.status_code == 404:
            raise MirrorFailure("invalid_reference")
        if response.status_code in {409, 422}:
            raise MirrorFailure("conflict")
        if response.status_code >= 500:
            raise MirrorFailure("storage_unavailable")
        if response.status_code >= 400:
            raise MirrorFailure("write_failed")
        return response
