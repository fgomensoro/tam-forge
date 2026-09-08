# Stable signing and permission persistence evidence (issue #38, E3-I12)

**Recorded:** 2026-09-08 (UTC). **Machine profile:** macbook-air-apple-m5-24gb. **Verified code:** `212cb58b862b63473fc9fc05e7e79c675b5cbcdc` (branch `codex/issue-38-stable-signing`, base `dd9552d`).

Signing material never enters the repository. The identity is a self-signed Code Signing certificate named `TAM Forge Local Development` in the owner's login keychain, trusted for code signing on this Mac only, valid until 2027-09-08.

## Release build and DMG

- Built with `scripts/dev/build_release_dmg.sh` (`make macos-release-dmg`); `scripts/ci/check_native_bundle.py --require-identity "TAM Forge Local Development"` passed.
- Signature: `Authority=TAM Forge Local Development`, hardened runtime, designated requirement `identifier "com.fgomensoro.tamforge" and certificate leaf = H"0ee5c606648b5c5fdd8de79c5742bd68681ddebf"`.
- Entitlements on the installed app: com.apple.security.app-sandbox com.apple.security.device.audio-input com.apple.security.files.user-selected.read-only com.apple.security.network.client 
- DMG: 3856715 bytes, sha256 `8502f27a3cac44fac657284eaaf46153b0aa5b944cb45b6d37912c0ea8de97b7`; mounted read-only, app copied to `/Applications/TAMForge.app`, `codesign --verify --deep --strict` passed on the installed copy (CDHash `904859b5f5536727b42ac3ed7c9a48ce9a7f5b0a`).

## Permission persistence across builds

The privacy grant is keyed to the designated requirement, so any build signed with the identity shares it. Both smoke builds were Debug builds of the same head launched with the fixture arguments (no live backend exists for a production sign-in).

| Step | Binary CDHash | Result |
|---|---|---|
| First signed build, first Start (04:09Z) | `50d5ed7455fc30371da570b6cbf9c13e963ac03a` | Microphone already authorized; Screen Recording blocked until the owner granted it once in System Settings for the signed app |
| Same build after the grant (04:20Z) | `50d5ed7455fc30371da570b6cbf9c13e963ac03a` | Recording started, both tracks, sealed |
| Rebuilt with a different build number (04:21Z) | `9d15ed3720c4d47379f3fe29cedb8ffb08a5cc9f` | Recording started and sealed with no System Settings change. macOS showed its screen-recording re-consent dialog for the new binary and the owner confirmed it; no microphone prompt |

Observation: macOS 15 and later show a screen-recording re-consent dialog for a new binary of an already-permitted app (and periodically); the underlying grant persists and the recording proceeds once the owner confirms. A stale Screen Recording entry left by the earlier ad-hoc copy had to be removed (`−`) and the signed app added (`+`) once; ad-hoc builds cannot share a grant because their designated requirement changes on every build.

## Scope decisions (owner, 2026-09-08)

- Clean-user smoke (a fresh macOS user account) is out of scope: TAM Forge is a single-user app on this one Mac, and the owner declined to create a second account. This amends the issue #38 acceptance criterion and spec line "clean-user smoke evidence"; the spec file is intentionally left unedited.
- The installed Release copy was verified by signature only. Its Recording screen needs a production sign-in against a live backend that does not exist yet, so the functional smoke used Debug builds signed with the same identity; the privacy grant is keyed to that identity, not to the build configuration.
- Notarization and Developer ID distribution are deferred by design (D3 in the redesign spec) until distribution beyond this Mac is needed.
- The certificate expires on 2027-09-08; renewing it changes the leaf hash, so permissions must be granted once more after renewal.
