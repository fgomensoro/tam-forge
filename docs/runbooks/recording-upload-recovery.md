# Recording upload and recovery

TAM Forge uploads only a locally sealed recording. Capture always has priority: if a new
recording starts, upload work is cancelled at the current file-backed request boundary and
returns to the deterministic pending queue.

## Durable states

1. `state.json` authenticates recording identity, start/end times, explicit gaps, and the two
   release gates with a key derived from the recording root key.
2. `upload-journal.json` contains only non-secret task identities, file identity, completed
   parts, and retry count. A prior in-flight entry becomes pending on relaunch.
3. Each upload part is rebuilt one at a time from one authenticated spool record. Its AES-GCM
   key and nonce are derived deterministically, but the key exists only in the live request
   header. The encrypted body uses an ephemeral/default `URLSessionUploadTask(fromFile:)`.
4. Server create, part, and seal calls are idempotent. A lost response may cause a replay; it
   cannot create a competing immutable part.

## Recovery actions

- **Waiting for sign-in:** sign in, then press Retry. A `401` creates one replacement upload
  task with a refreshed bearer token.
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
