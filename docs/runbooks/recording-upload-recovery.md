# Recording upload and recovery

TAM Forge uploads only a locally sealed recording. Capture always has priority: if a new
recording starts, upload work is cancelled at the current file-backed request boundary and
returns to the deterministic pending queue.

## Durable states

1. `state.json` authenticates recording identity, start/end times, the exact gap-journal
   count, one checkpoint per track (record count, exact file bytes, terminal sample end),
   and the two release gates with a key derived from the recording root key.
2. `upload-journal.json` contains only non-secret task identities, file identity, completed
   parts, and retry count. A prior in-flight entry becomes pending on relaunch.
3. Authenticated one-second records are grouped by track and contiguous timeline into bounded
   parts of at most 60 seconds. One read-only encrypted part exists at a time; its AES-GCM key
   and nonce are derived deterministically, but the key exists only in the live request header.
   A streamed ciphertext digest plus device/inode/size identity is checked before and after the
   ephemeral/default `URLSessionUploadTask(fromFile:)`.
4. Before any network call, a bounded streaming pass re-authenticates every record and
   compares each track against its sealed checkpoint. A missing or truncated sealed track
   file, structural corruption, a gap-journal mismatch, or an unknown conversion version
   blocks upload entirely and the recording needs attention. A corrupt-ciphertext record
   whose authenticated metadata and checkpoint still match becomes an explicit manifest
   gap, never audio.
5. The seal manifest declares source lineage built from the original authenticated records:
   one segment per contiguous equal-source range (rate, channels, device, route, conversion),
   covering uploaded audio only, with nanosecond presentation times.
6. Server create, part, and seal calls are idempotent. A lost response may cause a replay; it
   cannot create a competing immutable part.

## Recovery actions

- **Waiting for sign-in:** sign in, then press Retry. A `401` creates one replacement upload
  task only while the original authentication-generation lease remains current. Sign-out
  cancels active uploads; an old request cannot continue under a later login.
- **Waiting for network:** reconnect, then press Retry. Completed part receipts remain in the
  non-secret journal.
- **Needs attention:** do not remove the spool. Retry once; if the conflict remains, preserve
  the recording directory and collect only redacted app/server diagnostics.
- **Waiting for transcript acceptance:** no action is required. Server audio `201 Created`
  deliberately does not delete the encrypted spool.
- **Discard:** only the explicit confirmed UI action crypto-shreds the key and removes the
  local directory before both release gates pass.

Automatic deletion is legal only when server audio is durable and transcript lineage is
accepted. The app rechecks those gates on launch or manual Retry.
