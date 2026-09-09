#!/bin/zsh
# Convert every recorded benchmark passage to canonical 48 kHz mono PCM16
# WAV for the whisper.cpp benchmark runner.
#
# Idempotent: a canonical file that is already newer than its source
# recording is left alone. Audio lives only under apps/macos/PrivateAudio,
# which is gitignored, and never enters the repository.
set -euo pipefail
cd "$(dirname "$0")/../.."

AUDIO_DIR="apps/macos/PrivateAudio"
CANONICAL_DIR="$AUDIO_DIR/canonical"
READING_SCRIPT="docs/project/voice-benchmark-script-v1.md"

files=("$AUDIO_DIR"/*.m4a(N))

if (( ${#files[@]} == 0 )); then
  echo "prepare_benchmark_audio: no .m4a recordings found in $AUDIO_DIR. Record the reading script at $READING_SCRIPT with QuickTime Player (see that file for exact steps), save each passage as $AUDIO_DIR/passage-N.m4a, then re-run this script." >&2
  exit 2
fi

mkdir -p "$CANONICAL_DIR"

converted=0
for input in "${files[@]}"; do
  name="$(basename "$input" .m4a)"
  output="$CANONICAL_DIR/$name.wav"

  if [[ -f "$output" && "$output" -nt "$input" ]]; then
    continue
  fi

  afconvert -f WAVE -d LEI16@48000 -c 1 "$input" "$output"
  echo "Converted $input -> $output"
  converted=$((converted + 1))
done

echo "Converted $converted file(s)."
