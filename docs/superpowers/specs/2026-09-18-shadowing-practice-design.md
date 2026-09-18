# Shadowing practice

Date: 2026-09-18. Status: agreed with Frank in brainstorming, pending his review of this file.

## Why

English fluency and pronunciation are an explicit skill in TAM Forge, and every
spoken mode today has Frank producing his own words. Shadowing is the missing
half: speaking over a native speaker's audio, phrase by phrase, to absorb rhythm,
intonation and ready-made phrasing. Done on TAM material it pays twice, because
the phrases being drilled are the ones an interview or a customer call needs.

## What good shadowing needs

1. Short clips, 30 seconds to 2 minutes, never a whole video.
2. A transcript split into phrases with timestamps.
3. Looping one phrase, at reduced speed (0.75x) and at 1x, with and without text.
4. Recording the learner while the original plays, then comparing.

Exact phrase loops and variable speed are native to `AVPlayer` on a local file and
a fight against an embedded web player. That decides the media model below.

## Decisions taken with Frank

**The app imports local files; it does not fetch media.** Frank picks an mp4, m4a
or mp3, marks the start and end of the excerpt, and the app keeps only that
excerpt. Where the file came from is outside the product. There is no YouTube
downloader in the app and no embedded YouTube player. A starter set of clips with
free licenses is curated separately, license checked per clip and recorded on the
clip.

**Clips carry two labels.** Format is `solo` or `dialogue`. Topic is an existing
skill slug, grouped for browsing into three families: technical, TAM craft
(account management, customer success, escalations, QBRs, renewals, difficult
stakeholders) and general (series, talks, for accent and slang). Reusing skill
slugs means shadowing counts toward the same skill as cards and free practice.

**Dialogues are not diarized.** In the first version the learner shadows the whole
clip or toggles phrases off by hand to follow one speaker. Automatic speaker
detection is left out until its absence hurts.

**Feedback is measured locally, then coached by the model.** Shadowed text is not
the learner's own, so there is no content to grade, only execution.

**Headphones are required.** The learner is recorded while the original plays.
Capture already separates microphone and system audio into tracks; with
headphones the microphone track is clean. The attempt screen says so before
recording starts.

## Architecture

One new backend package `shadowing/` and one new macOS feature folder
`Features/Shadowing/`, following the shape of `practice/` and `Features/Cards/`.
Router registered in `api.py` next to the others.

### Data

- `ShadowingClip`: title, format (`solo`|`dialogue`), `skill_slug`, source note,
  license note, object-store key of the excerpt, duration, `phrases` JSONB (index,
  start ms, end ms, text, enabled), `annotations` JSONB (see clip preparation),
  preparation state.
- `ShadowingAttempt`: clip id, `recording_id` (existing `Recording`), playback
  speed, text shown or hidden, per-phrase `metrics` JSONB, coach `outcome` JSONB,
  `model`, `prompt_version`. Same async shape as `PracticeAnswer`: create returns
  202, the review lands later.

Alembic revision ids stay at or under 32 characters. Optional fields that reach
the Swift generator avoid bare `None` defaults.

### Media

The excerpt is cut on the Mac with `AVAssetExportSession` (time range), uploaded
through the existing presigned object-store flow, and downloaded to a local cache
for playback. Audio-only sources are first class; video is shown when present.

### Clip preparation (on import)

1. Whisper, already vendored, transcribes the excerpt with timestamps; segments
   become `phrases`. Frank can merge, split or fix text before saving.
2. New agent role `shadowing_prep` in `agents/roles/` reads the transcript and
   returns annotations: slang, idioms and phrases worth stealing, each with a
   one-line note on when it is used. Runs through the existing Agent SDK runtime
   on the subscription credential, tool-less, structured output.
3. Any annotation becomes a card with one click. `source_kind` gains the value
   `shadowing` (check constraint and `CardSource` updated together).

### Attempt

`AVPlayer` plays the phrase range, looping, at the chosen speed with pitch-
preserving time stretch (`audioTimePitchAlgorithm = .timeDomain`). The existing
`RecordingCoordinator` records the microphone during playback. The learner can
replay their take next to the original per phrase.

### Scoring (local, no model)

Whisper transcribes the take. Per phrase: words dropped or changed against the
reference text (word-level diff), pace (take duration against original duration,
corrected for playback speed), and the existing `PronunciationDiagnostic`. The
numbers are stored on the attempt so repeating a clip shows progress.

### Coach (model)

New role `shadowing_review`, same pattern as `practice_review`: input is the
per-phrase metrics plus the last attempts on the same clip; output is two or
three concrete fixes and which phrases to loop next. It never grades content.
Registered in the prompt registry with a version, with an eval alongside
`evals/practice_review.py`.

### macOS screens

Three views, built with the Organic primitives and the accessibility-identifier
contract, each new file hand-wired into `project.pbxproj`:

- Library: clips filtered by format and topic family, last score per clip.
- Import: pick file, trim, review phrases, see annotations, save.
- Session: player, phrase list with loop and speed, text toggle, record, per-phrase
  results, coach notes, make-card action on annotations.

## Errors

- Whisper or `shadowing_prep` fails on import: the clip saves with what exists and
  shows a retry; a clip without annotations is still usable.
- Coach quota or auth failure: the attempt keeps its local scores and shows the
  review as unavailable, as free practice does today.
- Take transcript nearly matches nothing: flag probable speaker bleed and remind
  about headphones instead of scoring.

## Testing

- Backend: service and route tests for clips and attempts, the word diff and pace
  math as pure functions with table tests, role contract tests, one eval for
  `shadowing_review`.
- macOS: unit tests for phrase-range playback math and scoring glue. UI tests run
  in CI's `native-ui` job only, never locally.

## Tickets

Filed under milestone M5 with a parent epic. Order is the dependency order.

1. **Epic: Shadowing practice.**
2. **Backend clips**: `shadowing/` package, `ShadowingClip`, migration, CRUD routes,
   presigned upload for the excerpt, contract regeneration.
3. **macOS import and library**: file pick, trim and export, Whisper phrases,
   phrase editor, upload, library view. Depends on 2.
4. **macOS session player**: `AVPlayer` phrase loop, speed, text toggle, recording
   during playback, side-by-side replay. Depends on 3.
5. **Attempts and local scoring**: `ShadowingAttempt`, word diff, pace,
   pronunciation per phrase, results UI, bleed detection. Depends on 4.
6. **Clip preparation role and cards**: `shadowing_prep`, annotations UI,
   `source_kind = shadowing`, one-click card. Depends on 3.
7. **Coach review role**: `shadowing_review`, prompt registration, eval, coach notes
   in the session view. Depends on 5.
8. **Starter clip set**: curate 10 to 15 free-license excerpts across the three
   topic families and both formats, license recorded per clip. Depends on 3.

Later, as separate tickets once clips and history exist:

9. **In your own words**: after a TAM-craft clip the model writes a question about
   it, answered in free practice.
10. **Next clip recommendation** from weak skills.

## Out of scope

Fetching or embedding online video, automatic speaker diarization, pitch-contour
visual comparison, offline-first sync of the clip cache.
