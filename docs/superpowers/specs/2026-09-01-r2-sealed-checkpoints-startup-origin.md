# R2 Sealed Checkpoints and Startup Origin

## Problema
Sealed recovery can miss removal of a complete record suffix or an entire track file because neither case creates an incomplete tail. Capture also chooses its shared timeline origin from whichever track callback arrives first, so later arrival of an earlier timestamp can fail or shift canonical ranges.

## Objetivo y no-objetivos
Authenticate enough terminal state to detect every sealed track truncation/removal and choose one callback-order-independent origin from both required tracks. Keep independently authenticated corrupt ciphertext ranges recoverable when the sealed file checkpoint still matches. Do not add legacy state compatibility, monitoring APIs, synthesized audio, or runtime verification in this amendment.

## Alcance
Change encrypted spool state/seal/recovery, capture startup gating, coordinator fatal-capture handling, and focused recording tests. AES-GCM record format, AAD, one-second accumulation, gap journal, callback handoff, release gates, and upload contracts stay unchanged.

## Fuente de datos
Sealed state schema 3 contains recording ID, seal flag, authenticated gap count, release gates, and exactly one checkpoint for each `RecordingTrackKind`. Each checkpoint stores track, record count, exact file bytes, and terminal canonical sample end. Startup inputs are canonical chunks with level, dropped intervals with reason, or failed intervals with reason/failure. Their anchor is chunk presentation time or interval start; input order is a monotonic tie-breaker. Startup retains at most 48,000 canonical audio samples, one second of presentation span, and 256 inputs per track.

## Algoritmo
Seal:
1. Persist supplied gaps.
2. Ensure both track files exist, synchronize, and close them.
3. For each track, capture durable sequence count, exact file size, and last canonical sample end.
4. Atomically persist authenticated schema-3 sealed state with both checkpoints.

Recovery:
1. Authenticate schema-3 state before accepting checkpoint fields.
2. Scan each existing track without guessing boundaries; count every structurally trusted complete record, total exact file bytes, and terminal sample end. Ciphertext failure remains an exact corrupt range only because its metadata HMAC is valid.
3. For sealed state, require both files and compare all three scan fields to the matching checkpoint.
4. Any missing file or mismatch is unrecoverable. Suppress exact corrupt ranges from a mismatched track. A matching scan may retain exact corrupt ciphertext ranges.

Startup:
1. Buffer every chunk, dropped interval, and failed interval until both tracks have anchors.
2. Reject and enter terminal startup failure before any track exceeds 48,000 audio samples, one-second span, or 256 inputs.
3. Once both anchors exist, choose the minimum buffered anchor, initialize the timeline once, sort inputs by anchor then insertion order, and replay through existing gap/accumulator/level logic.
4. If finish occurs before both anchors, discard buffered startup inputs and emit `requiredTracksMissing`.
5. Coordinator records that failure as fatal coverage loss and abandons the unsealed spool after pending writes drain.

## Casos límite y errores
| Condición | Comportamiento esperado |
|---|---|
| Complete last record removed | Sealed checkpoint mismatch; unrecoverable |
| Expected track file removed, including expected empty file | Sealed checkpoint mismatch; unrecoverable |
| Ciphertext corrupt; file length/count/end unchanged | Exact corrupt range; checkpoint accepted |
| Structural corruption prevents trusted scan | Existing structural unrecoverable result; checkpoint mismatch also blocks upload |
| System callback arrives first with later timestamp | Buffer; earlier microphone timestamp becomes shared origin; chronological replay |
| Only one track appears and reaches startup bound | Emit one fatal `requiredTracksMissing`; no buffered audio emitted |
| Only one track appears before finish | Emit one fatal `requiredTracksMissing`; no seal |
| Dropped/failure interval is first input for a track | Interval start is that track's startup anchor |

## Invariantes
- Authenticated sealed state has exactly two unique checkpoints, one per track.
- Matching sealed checkpoint means scan record count, physical bytes, and terminal sample end all match exactly.
- No corrupt range is accepted from a sealed track whose checkpoint mismatches.
- No startup input reaches timeline placement before both tracks provide anchors.
- Shared origin equals minimum buffered anchor, independent of callback order.
- Startup memory is fixed-bounded; failure emits no partial buffered audio.
- `requiredTracksMissing` prevents coordinator seal.

## Cambios de código
| Acción | Símbolo o archivo | Motivo |
|---|---|---|
| Cambiar | `EncryptedRecordingSpool` state/checkpoint recovery | Detect aligned suffix and whole-file loss |
| Cambiar | `RecordingCapturePipeline` / `RecordingTimelineAssembler` | Two-track origin gate and replay |
| Cambiar | `RecordingCaptureFailure` / `RecordingCoordinator` | Fatal missing-track coverage cannot seal |
| Agregar | `RecordingFeatureTests` regressions | Lock checkpoint and startup invariants |

## Plan de pruebas
Write first: aligned complete-record truncation, missing sealed track file, matching-checkpoint ciphertext corruption, system-first/later-earlier microphone replay, startup bound failure, missing-second-track finish, and coordinator no-seal on required-track failure. Execution remains deferred; use static Swift parse and diff inspection only.
