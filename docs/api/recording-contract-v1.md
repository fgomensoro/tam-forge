# Recording contract v1

Recording v1 stores two canonical tracks: 48 kHz signed little-endian interleaved
PCM16, one microphone channel and two system-audio channels. Integer sample ranges,
not wall-clock seconds, define ordering. A manifest is valid only when ordered parts
and explicit gaps cover each track exactly once from sample zero through
`total_sample_count`.

## Canonical bytes and hashes

Canonical JSON uses UTF-8, lexicographically sorted object keys, compact separators,
ASCII escaping, no trailing newline, and no floating-point values. UUIDs and aware
timestamps use Pydantic JSON encoding. Hash inputs start with one domain and a NUL
byte:

- `tamforge.recording.manifest.v1\0` for a complete `RecordingSealCommand`.
- `tamforge.recording.timeline.v1\0` for a track without its final PCM or timeline
  digest fields.
- `tamforge.recording.part-aad.v1\0` for upload metadata except the ciphertext
  digest. The ciphertext digest cannot authenticate itself; AES-GCM authenticates
  the ciphertext and the server verifies its declared digest separately.

SHA-256 values are lowercase hexadecimal. PCM digests cover the exact canonical
little-endian bytes, without a WAV header. Byte length must equal
`sample_count * channel_count * 2`.

## Encrypted part body

Each request body is `ciphertext || 16-byte AES-GCM tag`. The 12-byte nonce is sent
as unpadded base64url in `X-TAM-Part-Nonce`. A per-part 256-bit key derived by
HKDF-SHA256 is sent as unpadded base64url in `X-TAM-Part-Key`. The root recording key
never leaves the Mac. `Authorization` and `X-TAM-Part-Key` are always redacted.

The remaining `X-TAM-*` headers carry schema, track kind, PCM format, sequence,
sample range, plaintext/ciphertext lengths and SHA-256 values, plus encryption
version. `Idempotency-Key` identifies create, part, or seal commands. Identical
identity and content may replay; different content for the same identity is a
conflict.

## Release gates

Server `201 Created` sets `audio_created_on_server`. It does not authorize local
deletion. The encrypted spool and recording key remain until a later workflow sets
`transcript_lineage_accepted`. A recording with explicit gaps is durable but reports
`stored_with_gaps`; it never reports complete coverage.
