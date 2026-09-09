# Transcript, word, uncertainty, correction, and model lineage

**Issue:** [#44](https://github.com/fgomensoro/tam-forge/issues/44) (E4-I05)
**Plan task:** 7.1 Processing order, step 5
**Privacy impact:** high
**Date:** 2026-09-09

## Purpose

Step 5 of the processing order says: persist transcript, word timestamps,
model/config hashes, quality metadata, and correction lineage to FastAPI. Nothing
implements it today, so the last two steps of the order can never run.

The consequence is concrete. The macOS client already computes the full result and
then drops it on the floor. `RecordingReleaseGates.mayDeleteLocalSpool` requires both
`audioCreatedOnServer` and `transcriptLineageAccepted`, and the second flag has no
writer anywhere in the system. Every sealed recording therefore parks in
`waitingForTranscript` forever and its encrypted spool is never released. The retention
policy in the redesign spec is correct in principle and unreachable in practice.

## Scope

In scope:

- A `speech` module in the backend holding an immutable transcript per recording track,
  its words with timestamps and uncertainty, its derivation lineage, and its model
  identity.
- Append-only human corrections that reference a transcript without altering it.
- Accepting a transcript flips `Recording.transcript_lineage_accepted`.
- The macOS client submitting the transcript once local transcription succeeds.

Out of scope:

- Any correction UI. The model and the write endpoint exist; the screen that produces
  corrections belongs to the issue that needs it.
- Pace, pause, filler and restart metrics. Those are issue #45 and read what this
  stores.
- System-audio transcription policy. The schema accepts either track; deciding when a
  system-audio transcript is required stays with the interview work.

## Data model

Two tables in one migration, `20260909_0018_transcripts`. The revision id is 26
characters, under the 32-character ceiling of `alembic_version.version_num`.

### speech_transcripts

One row per recording and track. The row is written once and never updated.

| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT identity | |
| `owner_id` | BIGINT | FK to owners, RESTRICT |
| `recording_id` | BIGINT | FK to recordings, RESTRICT |
| `track` | TEXT | `microphone` or `system_audio` |
| `canonical_json` | TEXT | the transcript body, provenance JSON v1 |
| `content_hash` | BYTEA(32) | SHA-256 of `canonical_json` |
| `hash_format` | INTEGER | fixed at 1 |
| `created_at` | TIMESTAMPTZ | |

Constraints follow the `privacy_attestations` precedent: `content_hash` is verified in
the database with `public.digest`, and `canonical_json` must equal
`public.tamforge_provenance_canonical(canonical_json::jsonb)` so a row that is not
canonical cannot exist. Uniqueness is `(owner_id, recording_id, track)`, which makes a
second transcript for the same track a conflict rather than a silent second opinion.

`canonical_json` is bounded to 4 MiB. A 120-minute recording is roughly 18,000 words;
at about 69 canonical bytes per word plus segment overhead that lands near 1.6 MB, so
the bound leaves a little over twice the worst realistic case without inviting an
unbounded body. Immutability is structural: no update path exists in the repository,
and the canonical and hash constraints mean any rewrite would have to recompute both.

Segment text repeats the text of its own words. It is kept because whisper.cpp
punctuates and spaces a segment in a way that concatenating its words does not
reproduce, and the analysis that reads this needs the punctuated form.

### Transcript body

The body carries exactly what the client already produces, renamed to snake_case:

```
{
  "schema_version": 1,
  "segments": [
    {"text": "...", "start_ms": 0, "end_ms": 1200,
     "words": [{"text": "...", "start_ms": 0, "end_ms": 300, "probability": 0.98}]}
  ],
  "model_identity": {
    "runtime_version": "b4938", "model_filename": "...", "model_sha256": "...",
    "metal_requested": true, "used_builtin_vad": false, "language": "en"
  },
  "derivation": {
    "derivation_version": "tamforge-asr16k-v1",
    "source_sample_rate": 48000, "source_channel_count": 1,
    "source_sample_count": 0, "output_sample_rate": 16000, "output_sample_count": 0,
    "zero_filled_gaps": [], "source_pcm_sha256": "...", "derived_pcm_sha256": "...",
    "quality": {...}
  }
}
```

Uncertainty is the per-word `probability` whisper.cpp already returns. Reproducibility
is the pair of PCM hashes plus the model hash: given the same sealed audio and the same
model file, a rerun is checkable against what was stored. The backend records the model
hash as declared by the client; it holds no model and cannot verify it.

### speech_transcript_corrections

Append-only, one row per correction.

| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT identity | |
| `owner_id` | BIGINT | FK to owners, RESTRICT |
| `transcript_id` | BIGINT | FK to speech_transcripts, RESTRICT |
| `canonical_json` | TEXT | the correction body, provenance JSON v1 |
| `content_hash` | BYTEA(32) | SHA-256, verified in the database |
| `hash_format` | INTEGER | fixed at 1 |
| `created_at` | TIMESTAMPTZ | |

The correction body names a span by segment and word index, and carries the original
text alongside the replacement:

```
{"schema_version": 1, "segment_index": 3, "word_start_index": 7, "word_end_index": 9,
 "original_text": "...", "corrected_text": "...", "reason": "misheard_term"}
```

Storing `original_text` is redundant against the transcript on purpose. It makes a
correction self-describing in an export and detects a correction pointing at a span it
was not written against. Bounded to 8 KiB.

## API

Three operations under `/recordings/{recording_id}/transcripts`, matching the existing
recording router's conventions: bearer owner auth, `Idempotency-Key` header on writes,
and the `no-store` response headers from `_prevent_storage`.

| Method | Path | Result |
|---|---|---|
| POST | `/recordings/{id}/transcripts` | 201 with the stored transcript summary |
| GET | `/recordings/{id}/transcripts` | 200 with transcripts and their corrections |
| POST | `/recordings/{id}/transcripts/{track}/corrections` | 201 with the correction |

Accepting a transcript is what sets `Recording.transcript_lineage_accepted`. The
existing `transcript_lineage_requires_audio` check constraint already forbids that flag
without durable server audio, so a transcript for a recording that is not `stored` or
`stored_with_gaps` is rejected as a conflict rather than deferred.

Idempotency follows the seal endpoint: an identical resubmission returns the stored
result, and a submission that differs on the same track is a conflict. This matters
because the client retries on a timer and must not create a second lineage.

Response bodies never include the transcript text in a summary field, and no
identifier derived from transcript text ever reaches an object key or a log line. The
GET returns the body only to its owner.

## Client flow

`RecordingCoordinator.beginTranscription` already ends at
`transcriptState = .ready(recordingID, result)`. One submission step is added there:
map the result to the wire body, POST it, and on success let the existing upload path
do the rest. `RecordingUploader.upload` already re-reads the server status when audio
is on the server, remarks the gates, and calls `releaseIfEligible`, so a spool releases
on the next worker pass with no new deletion logic.

Failure keeps the spool. A submission that fails leaves `transcript_lineage_accepted`
false, the gate stays closed, and the recording stays in `waitingForTranscript` for the
next retry. That is the retention rule the redesign spec asks for, and it is the
default behaviour of the code that already exists.

## Testing

Test-first throughout. The issue's own verification is
`uv run pytest apps/backend/tests/speech/test_transcript_repository.py apps/backend/tests/speech/test_transcript_routes.py -q`.

Backend coverage: canonical round-trip and hash agreement between Python and
PostgreSQL, uniqueness per recording and track, rejection of a transcript for a
recording without durable audio, idempotent resubmission, conflicting resubmission,
oversized body rejection, correction append and ordering, and owner isolation on every
read.

Client coverage: submission after a ready transcript, no submission after a failed one,
retry after a failed submission, and the release of a spool once the server reports both
gates true.

## Risks

Touching `apps/macos` invalidates the committed recording-verification evidence on the
issue #36 branch, which is being reverted to its sentinel template separately. The
evidence gate compares against paths, not intent, so this is expected rather than a
defect here.

A new schema shape reaching HTTP for the first time can emit an OpenAPI 3.1 construct
that the Swift client generator cannot parse. Construct counts in the generated
`openapi.yaml` are compared against main before pushing.

The migration moves the head asserted in `test_curriculum_schema.py` and the frozen
OpenAPI digest in `test_check_openapi.py`. Both are consequences of the change.
