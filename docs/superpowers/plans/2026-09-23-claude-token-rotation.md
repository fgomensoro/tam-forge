# Claude Token Rotation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the owner change the Claude Agent SDK subscription token with one command, and see from the Mac app whether the server's Claude worker is running with a valid token.

**Architecture:** The token never passes through TAM Forge (docs/runbooks/claude-subscription.md forbids any endpoint that accepts it). `make rotate-claude-token` reads the token with echo off on the operator's Mac and pipes it over one ssh session to tamforge-prod, where it replaces `/etc/tamforge/secrets/claude-oauth.env`, restarts `tamforge-claude-worker` and waits for the worker's next heartbeat. The Mac app gets a native `Settings` scene (Cmd+,) whose Claude pane reads the existing owner-only `GET /ops/status` and shows the `claude` component plus the rotation command.

**Tech Stack:** bash, pytest, systemd unit files, SwiftUI (macOS), the existing `NativeAPITransport`.

**Spec:** design approved in chat on 2026-09-23 (bounded path, no spec file).

## Global Constraints

- No endpoint, request body, log line or file in the repository ever carries the token.
- The token file on the host is `/etc/tamforge/secrets/claude-oauth.env`, mode 0640, owner `root:tamforge-claude`, one line `CLAUDE_CODE_OAUTH_TOKEN=<token>`.
- The rotation script's default ssh alias is `hetzner-server-2` (logs in as root); override with `TAMFORGE_HOST`.
- UI copy is English. Chat is not.
- Commits are conventional commits in English, each ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Test fixtures never contain a realistic-looking token (the secret-scan job flags `sk-ant-` plus 20 or more characters): use `sk-ant-oat01-fixture` and `sk-ant-api03-fixture`.

---

### Task 1: Rotation script, host unit and runbook (independent)

**Files:**
- Create: `scripts/dev/rotate_claude_token.sh`
- Create: `scripts/dev/tests/test_rotate_claude_token.py`
- Modify: `Makefile` (new `rotate-claude-token` target and `.PHONY` entry)
- Modify: `infra/systemd/tamforge-claude-worker.service:21` (replace the dead `LoadCredential`)
- Modify: `infra/tests/test_systemd_units.py:84-95`
- Modify: `docs/runbooks/claude-subscription.md` ("Storing it safely" names the file; new "Rotating the token" section)
- Modify: `docs/runbooks/host-provisioning.md:43-44` (the Claude worker gets its token from an env file, not `LoadCredential`)

**Interfaces:**
- Consumes: nothing.
- Produces: the command string `make rotate-claude-token`, which Task 2 shows in the app.

- [ ] **Step 1: Write the failing tests**

`scripts/dev/tests/test_rotate_claude_token.py`:

```python
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path("scripts/dev/rotate_claude_token.sh")
TOKEN = "sk-ant-oat01-fixture"


@pytest.fixture
def fake_ssh(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_log = tmp_path / "ssh-argv"
    stdin_log = tmp_path / "ssh-stdin"
    ssh = bin_dir / "ssh"
    ssh.write_text(
        "#!/bin/bash\nset -eu\n"
        'printf "%s\\n" "$@" > "$FAKE_SSH_ARGV"\n'
        'cat > "$FAKE_SSH_STDIN"\n'
        'printf "%s\\n" "${FAKE_SSH_RESULT:-ok none}"\n',
        encoding="utf-8",
    )
    ssh.chmod(0o700)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_SSH_ARGV": str(argv_log),
        "FAKE_SSH_STDIN": str(stdin_log),
        "TAMFORGE_SKIP_SETUP_TOKEN": "1",
    }
    return env, argv_log, stdin_log


def run(env: dict[str, str], token: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT)], input=f"{token}\n", env=env, capture_output=True, text=True
    )


def test_the_token_travels_only_on_ssh_stdin(fake_ssh: tuple[dict[str, str], Path, Path]) -> None:
    env, argv_log, stdin_log = fake_ssh
    result = run(env, TOKEN)
    assert result.returncode == 0, result.stderr
    assert stdin_log.read_text() == f"CLAUDE_CODE_OAUTH_TOKEN={TOKEN}\n"
    assert TOKEN not in argv_log.read_text()
    assert TOKEN not in result.stdout + result.stderr
    assert "ready" in result.stdout


def test_the_host_side_installs_the_file_atomically_and_restarts_the_worker(
    fake_ssh: tuple[dict[str, str], Path, Path],
) -> None:
    env, argv_log, _ = fake_ssh
    run(env, TOKEN)
    remote = argv_log.read_text()
    assert remote.splitlines()[0] == "hetzner-server-2"
    for fragment in (
        "umask 077",
        "chown root:tamforge-claude /etc/tamforge/secrets/claude-oauth.env.new",
        "chmod 0640 /etc/tamforge/secrets/claude-oauth.env.new",
        "mv -f /etc/tamforge/secrets/claude-oauth.env.new /etc/tamforge/secrets/claude-oauth.env",
        "systemctl restart tamforge-claude-worker",
        "worker_heartbeats",
    ):
        assert fragment in remote


def test_a_value_that_is_not_a_subscription_token_changes_nothing(
    fake_ssh: tuple[dict[str, str], Path, Path],
) -> None:
    env, argv_log, _ = fake_ssh
    result = run(env, "sk-ant-api03-fixture")
    assert result.returncode == 1
    assert not argv_log.exists()
    assert "Nothing changed" in result.stderr


def test_a_worker_that_is_not_ready_after_the_restart_fails_the_rotation(
    fake_ssh: tuple[dict[str, str], Path, Path],
) -> None:
    env, _, _ = fake_ssh
    result = run({**env, "FAKE_SSH_RESULT": "needs_attention auth"}, TOKEN)
    assert result.returncode == 1
    assert "needs_attention (auth)" in result.stderr
```

- [ ] **Step 2: Run them to verify they fail**

Run: `~/.local/bin/uv run pytest scripts/dev/tests/test_rotate_claude_token.py -q`
Expected: 4 failures (script missing, bash exits 127).

- [ ] **Step 3: Write the script**

`scripts/dev/rotate_claude_token.sh` (chmod 0755):

```bash
#!/bin/bash
# Rotates the Claude subscription token on the production host.
#
# The token is read with echo off and travels only on ssh's stdin: never in argv, a
# local file, or the terminal scrollback. Everything on the host happens inside one
# ssh session, so the Bitwarden agent prompts once. See
# docs/runbooks/claude-subscription.md, "Rotating the token".
set -euo pipefail

host="${TAMFORGE_HOST:-hetzner-server-2}"
wait_seconds="${TAMFORGE_ROTATE_WAIT_SECONDS:-90}"

if [ "${TAMFORGE_SKIP_SETUP_TOKEN:-0}" != "1" ]; then
  if command -v claude >/dev/null 2>&1; then
    echo "Running 'claude setup-token'. Finish the browser sign-in, then copy the token it prints."
    claude setup-token
  else
    echo "The claude CLI is not on PATH. Run 'claude setup-token' elsewhere and paste its token here." >&2
  fi
fi

printf 'Paste the new token (input is hidden): ' >&2
IFS= read -rs token
printf '\n' >&2
token="${token//[[:space:]]/}"
case "$token" in
  sk-ant-oat*) ;;
  *)
    echo "That is not a subscription token (expected the sk-ant-oat prefix). Nothing changed." >&2
    exit 1
    ;;
esac

remote="$(cat <<REMOTE
set -euo pipefail
umask 077
cat > /etc/tamforge/secrets/claude-oauth.env.new
chown root:tamforge-claude /etc/tamforge/secrets/claude-oauth.env.new
chmod 0640 /etc/tamforge/secrets/claude-oauth.env.new
mv -f /etc/tamforge/secrets/claude-oauth.env.new /etc/tamforge/secrets/claude-oauth.env
started="\$(date -u +%Y-%m-%dT%H:%M:%SZ)"
systemctl restart tamforge-claude-worker
for _ in \$(seq 1 $((wait_seconds / 5))); do
  sleep 5
  beat="\$(sudo -u postgres psql -d tamforge -Atc "select status || ' ' || reason from worker_heartbeats where worker = 'claude' and observed_at > '\$started'")"
  if [ -n "\$beat" ]; then echo "\$beat"; exit 0; fi
done
echo "unknown not_observed"
REMOTE
)"

# printf is a shell builtin, so the token never shows up in a process listing.
result="$(printf 'CLAUDE_CODE_OAUTH_TOKEN=%s\n' "$token" | ssh "$host" "$remote")"
unset token

status="${result%% *}"
reason="${result#* }"
next="$(date -u -v+1y +%Y-%m-%d 2>/dev/null || date -u -d '+1 year' +%Y-%m-%d)"
if [ "$status" = "ok" ]; then
  echo "Claude worker is ready with the new token. Rotate again before $next."
  exit 0
fi
echo "Token installed, but the Claude worker reports $status ($reason). See docs/runbooks/claude-subscription.md." >&2
exit 1
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/.local/bin/uv run pytest scripts/dev/tests/test_rotate_claude_token.py -q`
Expected: 4 passed.

- [ ] **Step 5: Makefile target**

Add `rotate-claude-token` to the `.PHONY` line and, after `macos-release-dmg`:

```make
# Replaces the Claude subscription token on the production host (never in CI).
rotate-claude-token:
	scripts/dev/rotate_claude_token.sh
```

- [ ] **Step 6: Align the unit with the host and update its test**

In `infra/systemd/tamforge-claude-worker.service` replace
`LoadCredential=claude-token:/etc/tamforge/secrets/claude-token` with:

```ini
# The subscription token; replaced by `make rotate-claude-token`.
EnvironmentFile=-/etc/tamforge/secrets/claude-oauth.env
```

In `infra/tests/test_systemd_units.py`, drop the `token` lines from
`test_credentials_are_per_service_and_never_shared` and add:

```python
def test_only_the_claude_worker_loads_the_subscription_token() -> None:
    token_file = "-/etc/tamforge/secrets/claude-oauth.env"
    loaders = [u.stem for u in UNITS if token_file in parse(u).get("EnvironmentFile", [])]
    assert loaders == ["tamforge-claude-worker"]
```

Run: `~/.local/bin/uv run pytest infra/tests/test_systemd_units.py -q`
Expected: all pass.

- [ ] **Step 7: Runbooks**

`docs/runbooks/claude-subscription.md`, "Storing it safely": name the exact file
(`/etc/tamforge/secrets/claude-oauth.env`, 0640 `root:tamforge-claude`, loaded by the
unit's `EnvironmentFile`). Add after it a "Rotating the token" section: run
`make rotate-claude-token` from the repository on the operator's Mac; it runs
`claude setup-token`, asks for the token with input hidden, installs it over one ssh
session, restarts the worker and waits up to 90 seconds for its heartbeat; it exits
non-zero unless the worker reports ready; the Mac app's Settings > Claude pane shows
the same status. Keep the existing rule that no TAM Forge endpoint accepts a token.

`docs/runbooks/host-provisioning.md:43-44`: the Claude worker reads its token from
`/etc/tamforge/secrets/claude-oauth.env` through `EnvironmentFile`, not `LoadCredential`.

- [ ] **Step 8: Full Python gate and commit**

Run: `~/.local/bin/uv run ruff check . && ~/.local/bin/uv run pytest -m "not integration" -q`
Expected: clean, all pass.

```bash
git add scripts/dev/rotate_claude_token.sh scripts/dev/tests/test_rotate_claude_token.py Makefile infra/systemd/tamforge-claude-worker.service infra/tests/test_systemd_units.py docs/runbooks/claude-subscription.md docs/runbooks/host-provisioning.md
git commit -m "feat(ops): rotate the Claude subscription token with one command" -m "..." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Settings scene with a Claude status pane (independent)

**Files:**
- Create: `apps/macos/TAMForge/Features/Settings/ClaudeStatus.swift`
- Create: `apps/macos/TAMForge/Features/Settings/ClaudeSettingsView.swift`
- Create: `apps/macos/TAMForgeTests/ClaudeSettingsModelTests.swift`
- Modify: `apps/macos/TAMForge/App/TAMForgeApp.swift` (lift `NativeShellComposition` into the App, add `claudeStatus` to `NativeFeatureServices`, add the `Settings` scene)
- Modify: `apps/macos/TAMForge.xcodeproj/project.pbxproj` (wire the three new files; follow the `macos-organic-ui` skill)

**Interfaces:**
- Consumes: `GET /ops/status` (owner auth) returning `{"status", "ready", "components": {name: {"status", "reason"}}}`, `NativeAPITransport`, `ShellSessionModel.phase`, and the command string `make rotate-claude-token` from Task 1.
- Produces: nothing other tasks use.

- [ ] **Step 1: Write the failing tests**

`apps/macos/TAMForgeTests/ClaudeSettingsModelTests.swift`:

```swift
import Foundation
import XCTest

@MainActor
final class ClaudeSettingsModelTests: XCTestCase {
    func testEveryHeartbeatReasonMapsToOneState() {
        XCTAssertEqual(ClaudeTokenState(status: "ok", reason: "none"), .ready)
        XCTAssertEqual(ClaudeTokenState(status: "needs_attention", reason: "auth"), .tokenRefused)
        XCTAssertEqual(ClaudeTokenState(status: "needs_attention", reason: "quota"), .quotaSpent)
        XCTAssertEqual(ClaudeTokenState(status: "needs_attention", reason: "permission_required"), .disabled)
        XCTAssertEqual(ClaudeTokenState(status: "unknown", reason: "stale"), .notReporting)
        XCTAssertEqual(ClaudeTokenState(status: "unknown", reason: "not_observed"), .notReporting)
        XCTAssertEqual(ClaudeTokenState(status: "needs_attention", reason: "service"), .serviceProblem)
    }

    func testTheLiveClientReadsTheClaudeComponentOfOpsStatus() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 200, body: Data("""
        {"status": "degraded", "ready": true, "components": {
          "database": {"status": "ok", "reason": "none"},
          "claude": {"status": "needs_attention", "reason": "auth"}}}
        """.utf8)))
        let api = LiveClaudeStatusAPI(transport: NativeAPITransport(
            baseURL: URL(string: "https://api.example.test")!, session: fixture.session()
        ))

        let state = try await api.claudeState()

        XCTAssertEqual(state, .tokenRefused)
        XCTAssertEqual(fixture.requests.first?.url?.path, "/ops/status")
    }

    func testAFailedRefreshClearsTheStateAndSaysSo() async {
        let model = ClaudeSettingsModel(api: FailingClaudeStatusAPI())

        await model.refresh()

        XCTAssertNil(model.state)
        XCTAssertNotNil(model.errorMessage)
    }
}

@MainActor
private final class FailingClaudeStatusAPI: ClaudeStatusAPI {
    func claudeState() async throws -> ClaudeTokenState { throw URLError(.notConnectedToInternet) }
}
```

Check `URLProtocolFixture` in `NativeAPITransportTests.swift:432` for the exact `enqueue`/`.response` signature before relying on it.

- [ ] **Step 2: Run to verify they fail**

Run: `xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' -only-testing:TAMForgeTests/ClaudeSettingsModelTests test`
Expected: build failure, `ClaudeTokenState` not found.

- [ ] **Step 3: Status model and client**

`apps/macos/TAMForge/Features/Settings/ClaudeStatus.swift`:

```swift
import Foundation

/// The `claude` component of `GET /ops/status`, as the Settings pane shows it.
/// The server's closed reason vocabulary lives in observability/logging.py.
enum ClaudeTokenState: Equatable, Sendable {
    case ready
    case tokenRefused
    case quotaSpent
    case disabled
    case notReporting
    case serviceProblem

    init(status: String, reason: String) {
        switch (status, reason) {
        case ("ok", _): self = .ready
        case (_, "auth"): self = .tokenRefused
        case (_, "quota"): self = .quotaSpent
        case (_, "permission_required"): self = .disabled
        case (_, "stale"), (_, "not_observed"): self = .notReporting
        default: self = .serviceProblem
        }
    }

    var title: String {
        switch self {
        case .ready: "Ready"
        case .tokenRefused: "Token expired or refused"
        case .quotaSpent: "Quota spent"
        case .disabled: "Disabled on the server"
        case .notReporting: "Worker not reporting"
        case .serviceProblem: "Service problem"
        }
    }

    var detail: String {
        switch self {
        case .ready: "The server's Claude worker is running with a valid token."
        case .tokenRefused: "Rotate the token with the command below."
        case .quotaSpent: "The subscription quota is used up. Wait for it to reset; a new token does not help."
        case .disabled: "Claude is off or has no current privacy attestation on the server."
        case .notReporting: "The Claude worker has not sent a heartbeat in the last minute."
        case .serviceProblem: "The worker is up but its compatibility check failed. Check its logs on the host."
        }
    }
}

@MainActor
protocol ClaudeStatusAPI {
    func claudeState() async throws -> ClaudeTokenState
}

@MainActor
final class LiveClaudeStatusAPI: ClaudeStatusAPI {
    private let transport: NativeAPITransport

    init(transport: NativeAPITransport) {
        self.transport = transport
    }

    func claudeState() async throws -> ClaudeTokenState {
        let snapshot = try await transport.send(.init(method: .get, path: "/ops/status"))
            .decoded(as: OperationalStatus.self)
        guard let claude = snapshot.components["claude"] else { return .notReporting }
        return ClaudeTokenState(status: claude.status, reason: claude.reason)
    }
}

private struct OperationalStatus: Decodable, Sendable {
    struct Component: Decodable, Sendable {
        let status: String
        let reason: String
    }

    let components: [String: Component]
}

@MainActor
final class ClaudeSettingsModel: ObservableObject {
    static let rotateCommand = "make rotate-claude-token"

    @Published private(set) var state: ClaudeTokenState?
    @Published private(set) var errorMessage: String?
    @Published private(set) var isLoading = false

    private let api: any ClaudeStatusAPI

    init(api: any ClaudeStatusAPI) {
        self.api = api
    }

    func refresh() async {
        isLoading = true
        defer { isLoading = false }
        do {
            state = try await api.claudeState()
            errorMessage = nil
        } catch {
            state = nil
            errorMessage = "Could not read the server status. Try again."
        }
    }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Same command as Step 2. Expected: 3 tests pass.

- [ ] **Step 5: The pane**

`apps/macos/TAMForge/Features/Settings/ClaudeSettingsView.swift`, built with the Organic
primitives (load the `macos-organic-ui` skill first; use its tokens, `OrganicStatusDot`,
`OrganicGhostButtonStyle`/`OrganicSecondaryButtonStyle`, Figtree fonts, dark only):

- Title "Claude".
- Signed out (`session.phase` is not `.signedIn`): one line, "Sign in to see Claude status."
- Signed in: a status row with `OrganicStatusDot` (`accent2_400` when `.ready`, `accent300`
  otherwise, `muted` while loading), `state.title`, `state.detail`, `errorMessage` when set,
  and a "Refresh" button that calls `model.refresh()`. Below it: "To change the token, run
  this from the repository on your Mac. The token never passes through the app.", the command
  `ClaudeSettingsModel.rotateCommand` in a monospaced, selectable text, and a "Copy" button
  that puts the command on `NSPasteboard.general`.
- `.task { await model.refresh() }`, fixed width around 460 pt, `Organic.Color.bg` background.
- Accessibility identifiers: `claudeSettingsStatus`, `claudeSettingsRefresh`,
  `claudeSettingsCommand`, `claudeSettingsCopyCommand`.

- [ ] **Step 6: Wire the scene**

In `apps/macos/TAMForge/App/TAMForgeApp.swift`:

- Add `let claudeStatus: any ClaudeStatusAPI` to `NativeFeatureServices` and build it in
  `NativeShellComposition.init` as `LiveClaudeStatusAPI(transport: transport)`.
- Move the composition from `NativeShellView` into `TAMForgeApp` as
  `@StateObject private var composition: NativeShellComposition`, created in
  `init(dependencies:)`, so the main window and the Settings window share one session.
  `NativeShellView` goes away; the `Window` builds `NativeSessionView` from
  `composition.session`, `.services`, `.recording` directly.
- Add after the `Window` scene:

```swift
Settings {
    ClaudeSettingsView(session: composition.session, api: composition.services.claudeStatus)
        .preferredColorScheme(.dark)
}
```

- [ ] **Step 7: Xcode wiring and the unit gate**

Add the three new files to `project.pbxproj` exactly as the `macos-organic-ui` skill
describes (app target for the two sources, `TAMForgeTests` for the test).

Run: `make macos-check`
Expected: build succeeds and every `TAMForgeTests` test passes. Do not run the UI test
target locally (it takes over the desktop); CI's native-ui job runs it.

- [ ] **Step 8: Commit**

```bash
git add apps/macos/TAMForge/Features/Settings apps/macos/TAMForgeTests/ClaudeSettingsModelTests.swift apps/macos/TAMForge/App/TAMForgeApp.swift apps/macos/TAMForge.xcodeproj/project.pbxproj
git commit -m "feat(macos): show the Claude worker status in Settings" -m "..." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
