# Native authentication threat model

## Scope and assets

E10-I04 adds GitHub OAuth for the macOS app while preserving browser cookie and
CSRF authentication. Protected assets are the immutable owner identity, OAuth
provider code, one-time app exchange code, access token, rotating refresh token,
and server-side session state.

Trust boundaries are the system browser, GitHub, the public FastAPI callback,
the `tamforge://auth/callback` handoff, PostgreSQL, app memory, and macOS
Keychain. The native app is a public OAuth client and contains no client secret.

## Control checklist

- [x] `ASWebAuthenticationSession` opens the system browser. The app contains no
  embedded browser.
- [x] A 43-character opaque state is stored server-side only as a SHA-256 hash,
  expires after five minutes, and is consumed atomically before provider exchange.
  A PostgreSQL advisory lock caps outstanding flow rows at 64 and each start
  transaction deletes expired flow and exchange rows.
- [x] PKCE S256 binds the OAuth flow and the two-minute one-time exchange code to
  the initiating app instance.
- [x] GitHub authorization succeeds only for immutable user ID `102269369`.
- [x] The callback URL contains only the bounded one-time exchange code. The
  application access logger removes auth query strings and all auth responses are
  `no-store`; Caddy verification remains a production gate below.
- [x] Native request-validation errors are generic and never echo submitted codes,
  verifiers, or tokens.
- [x] Access tokens expire after 15 minutes and exist only in app memory. Refresh
  tokens expire after 30 days, rotate on every use, and use generic-password
  macOS Keychain items marked non-synchronizable. The app tries the Data Protection
  Keychain first with `WhenUnlockedThisDeviceOnly`, then falls back to the
  legacy/file-based Keychain only for `errSecMissingEntitlement`. The fallback uses
  legacy Keychain ACL semantics and lacks `ThisDeviceOnly`; it omits
  `kSecAttrAccessible`, which macOS permits only for Data Protection or
  synchronizable items, so standard-Keychain access defaults to when unlocked.
  The supported local distribution uses the stable self-signed `TAM Forge Local
  Development` identity: true ad-hoc rebuilds can change designated requirements
  and are not the credential-continuity guarantee. No application identifier or
  Keychain access group is required, and refresh tokens never reach files or
  `UserDefaults`.
- [x] PostgreSQL stores only fixed-size SHA-256 hashes. Old refresh generations
  remain as replay evidence.
- [x] Exchange replay fails. Refresh replay revokes the whole token family in the
  same transaction and emits a redacted audit event.
- [x] Refresh is single-flight in the app. An indeterminate refresh clears memory,
  quarantines the old refresh token for revocation, and requires reauthentication.
- [x] Login, refresh, and logout share a generation boundary. Logout invalidates
  in-flight work; a late token pair is revoked and cannot restore local credentials.
- [x] Offline logout removes the active local credential and keeps one pending
  Keychain revocation credential until the server acknowledges it. Crash recovery
  handles the temporary state where active and pending entries match.
- [x] Cookie and bearer credentials cannot be mixed. Bearer requests bypass browser
  Origin/CSRF checks only after server-side token validation; owner scoping remains
  unchanged.
- [x] Migration downgrade refuses to remove native auth tables while any active
  refresh-backed session remains.

## Residual risks and production gates

- macOS custom URL schemes are not globally exclusive. State, PKCE, strict
  scheme/host/path validation, and `ASWebAuthenticationSession` limit interception,
  but a separately installed malicious local app remains outside TAM Forge's trust
  boundary. A claimed HTTPS callback can replace the scheme if that risk becomes
  material.
- [ ] Before public production exposure, the exact deployed Caddy configuration
  must rate-limit native start/exchange/refresh/revoke requests and redact the
  complete GitHub callback query from access and error logs. A non-production
  synthetic callback marker must be absent from both Caddy and application logs
  before the gate can be checked. The database cap is defense in depth, not a
  replacement for edge throttling.
- [ ] Monitor native flow-capacity rejections and expired-row cleanup in production.
  Sustained `429 native_auth_capacity` responses block rollout progression.
- Malware running as the same macOS user may target app memory or Keychain access.
  Device security, stable code signing, FileVault, and OS updates remain required.

## Verification evidence

- Backend unit/security command:
  `uv run pytest apps/backend/tests/unit/auth apps/backend/tests/security/test_github_oauth.py -q`
- PostgreSQL integration coverage:
  `apps/backend/tests/integration/auth/test_native_auth_integration.py`
- Native unit/login/logout/Keychain coverage:
  `apps/macos/TAMForgeTests/NativeAuthenticationTests.swift`
- OpenAPI drift gate: `uv run python scripts/ci/check_openapi.py`

PostgreSQL integration runs only in isolated CI or with explicit local Docker
approval. A live GitHub login remains a manual smoke against configured non-production
OAuth credentials; automated tests never receive production credentials.
