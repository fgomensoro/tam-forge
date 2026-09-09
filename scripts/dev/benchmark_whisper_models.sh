#!/bin/zsh
# Build the Swift benchmark runner with raw swiftc (never xcodebuild) and run
# it once per pinned model over the prepared canonical audio.
#
# Results land under apps/macos/PrivateAudio/benchmark/<base|candidate>/,
# gitignored and holding transcript text; scripts/ci/check_model_benchmark.py
# --build aggregates them into the committed, aggregate-only report.
set -euo pipefail
cd "$(dirname "$0")/../.."

VENDOR_FRAMEWORK="apps/macos/Vendor/whisper.xcframework"
FRAMEWORK_SLICE="$VENDOR_FRAMEWORK/macos-arm64_x86_64"
CANONICAL_DIR="apps/macos/PrivateAudio/canonical"
RESULTS_DIR="apps/macos/PrivateAudio/benchmark"
MANIFEST="config/speech-models.yaml"
RUNNER_SOURCE="scripts/dev/benchmark_whisper_models.swift"

if [[ ! -d "$VENDOR_FRAMEWORK" ]]; then
  echo "benchmark_whisper_models: $VENDOR_FRAMEWORK is missing. Run 'make whisper-framework' first." >&2
  exit 2
fi

canonical_files=("$CANONICAL_DIR"/*.wav(N))
if (( ${#canonical_files[@]} == 0 )); then
  echo "benchmark_whisper_models: no canonical audio in $CANONICAL_DIR. Run scripts/dev/prepare_benchmark_audio.sh first." >&2
  exit 2
fi

if python3 -c 'import yaml' >/dev/null 2>&1; then
  PY=(python3)
else
  # Ephemeral environment with only PyYAML: never sync the whole project
  # just to read two pins.
  PY=(uv run --no-project --with pyyaml python)
fi

pin() {
  "${PY[@]}" -c '
import sys
import yaml

with open(sys.argv[1], encoding="utf-8") as handle:
    document = yaml.safe_load(handle)
print(document["artifacts"][sys.argv[2]][sys.argv[3]])
' "$MANIFEST" "$1" "$2"
}

expand_home() {
  case "$1" in
    "~") print -r -- "$HOME" ;;
    "~/"*) print -r -- "$HOME/${1#\~/}" ;;
    *) print -r -- "$1" ;;
  esac
}

BASE_FILENAME="$(pin transcription_model filename)"
CANDIDATE_FILENAME="$(pin benchmark_model filename)"
MODELS_DIR="$(expand_home "$(pin transcription_model installs_to)")"

BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT

RUNNER="$BUILD_DIR/benchmark_whisper_models"
echo "Building benchmark runner..."
swiftc \
  -parse-as-library \
  -swift-version 6 \
  -target arm64-apple-macosx15.0 \
  -sdk "$(xcrun --show-sdk-path)" \
  -F "$FRAMEWORK_SLICE" \
  -framework whisper \
  -o "$RUNNER" \
  "$RUNNER_SOURCE" \
  apps/macos/TAMForge/Features/Speech/ASRAudioDerivation.swift \
  apps/macos/TAMForge/Features/Speech/AudioQualityObservations.swift \
  apps/macos/TAMForge/Features/Speech/SpeechTranscription.swift \
  apps/macos/TAMForge/Features/Speech/SpeechModelCatalog.swift \
  apps/macos/TAMForge/Features/Speech/WhisperTranscriber.swift \
  apps/macos/TAMForge/Features/Recording/RecordingModels.swift

run_model() {
  local key="$1"
  local filename="$2"
  local output_dir="$RESULTS_DIR/$key"

  if [[ ! -f "$MODELS_DIR/$filename" ]]; then
    echo "benchmark_whisper_models: $filename is not installed in $MODELS_DIR. Run 'make whisper-models' first." >&2
    exit 2
  fi

  mkdir -p "$output_dir"
  echo "Running $key ($filename)..."
  DYLD_FRAMEWORK_PATH="$FRAMEWORK_SLICE" "$RUNNER" "$MODELS_DIR" "$filename" "$CANONICAL_DIR" "$output_dir"

  local results=("$output_dir"/*.json(N))
  echo "$key ($filename): ${#results[@]} passage(s) transcribed, results in $output_dir"
}

run_model base "$BASE_FILENAME"
run_model candidate "$CANDIDATE_FILENAME"
