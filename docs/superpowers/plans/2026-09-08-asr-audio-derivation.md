# ASR Audio Derivation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Derive a deterministic, versioned 16 kHz mono PCM16 stream plus lineage and quality observations from one canonical 48 kHz recording track, in the macOS app, without touching the originals.

**Architecture:** Two pure Swift types under `apps/macos/TAMForge/Features/Speech/`: `AudioQualityObservations` (versioned signal-condition counters with availability flags) and `ASRAudioDeriver` (fixed downmix, Kaiser-windowed-sinc FIR, 3:1 decimation, zero-filled gaps, streaming blocks, lineage). No disk writes, no AVFoundation, no Accelerate.

**Tech Stack:** Swift 6 (strict concurrency), XCTest, CryptoKit SHA-256. Project file is hand-maintained (`project.pbxproj`, no file-system-synchronized groups).

**Spec:** `docs/superpowers/specs/2026-09-08-asr-audio-derivation-design.md`

## Global Constraints

- Canonical input is `RecordingPCMChunk` (48 000 Hz, `pcm_s16le`, interleaved, microphone 1 channel / system_audio 2 channels) from `apps/macos/TAMForge/Features/Recording/RecordingModels.swift`.
- Derivation version string is exactly `tamforge-asr16k-v1`; quality version is exactly `audio-quality-v1`.
- Output sample `n` corresponds to canonical source sample `3n`; gaps are zero-filled, never dropped.
- Deterministic: same chunks in, same bytes out, regardless of chunk boundaries.
- Locally run only `swiftc -parse <file>` and `git diff --check`; XCTest runs in required CI (`macos-native`). Never run `xcodebuild` locally for this ticket.
- Every new Swift file is registered in `apps/macos/TAMForge.xcodeproj/project.pbxproj` in both Sources phases (app target and test host list) following the existing `F3…` entries; new object IDs must be unique 24-hex strings.
- Commit messages in plain prose, ending with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

---

### Task 1: Versioned audio quality observations

**Files:**
- Create: `apps/macos/TAMForge/Features/Speech/AudioQualityObservations.swift`
- Create: `apps/macos/TAMForgeTests/AudioQualityObservationsTests.swift`
- Modify: `apps/macos/TAMForge.xcodeproj/project.pbxproj` (new `Speech` group under `Features`, file refs, build files in both Sources phases, test file under the tests group)

**Interfaces:**
- Produces:
  ```swift
  struct AudioQualityThresholds: Sendable, Equatable {
      static let v1 = AudioQualityThresholds(
          minimumDurationSeconds: 1.0, silencePeak: 16,
          maximumClippedRatio: 0.01, maximumDCOffset: 0.05,
          maximumChannelImbalanceDecibels: 20.0)
      let minimumDurationSeconds: Double
      let silencePeak: Int          // absolute Int16 peak at or below which the track is all-silence
      let maximumClippedRatio: Double
      let maximumDCOffset: Double   // normalised to full scale
      let maximumChannelImbalanceDecibels: Double
  }
  struct AudioQualityObservations: Sendable, Equatable {
      static let version = "audio-quality-v1"
      let version: String
      let sampleRate: Int
      let channelCount: Int
      let sourceSampleCount: Int64
      let durationSeconds: Double
      let peakAbsolute: Int
      let allSilence: Bool
      let clippedRatio: Double
      let dcOffset: Double
      let channelImbalanceDecibels: Double?   // nil for mono
      let discontinuityCount: Int
      let unavailableDimensions: [String]     // sorted, from {"duration","silence","clipping","dc-offset","channel-imbalance"}
  }
  struct AudioQualityAccumulator: Sendable {
      init(sampleRate: Int, channelCount: Int)
      mutating func observe(chunk: RecordingPCMChunk)       // interleaved Int16 little-endian payload
      mutating func noteDiscontinuity()
      func finish(thresholds: AudioQualityThresholds = .v1) -> AudioQualityObservations
  }
  ```

- [ ] **Step 1: Write the failing tests**

```swift
import XCTest
@testable import TAMForge

final class AudioQualityObservationsTests: XCTestCase {
    private func chunk(track: RecordingTrackKind, samples: [Int16], sampleStart: Int64 = 0) -> RecordingPCMChunk {
        let channels = track == .microphone ? 1 : 2
        var payload = Data(capacity: samples.count * 2)
        for sample in samples { withUnsafeBytes(of: sample.littleEndian) { payload.append(contentsOf: $0) } }
        return RecordingPCMChunk(
            track: track,
            presentationNanoseconds: 0,
            sampleStart: sampleStart,
            sampleCount: samples.count / channels,
            format: try! RecordingPCMFormat(track: track, channelCount: channels),
            source: .init(sampleRate: 48_000, channelCount: channels, deviceID: "test", initialRoute: "test", conversionVersion: 1, presentationNanoseconds: 0),
            payload: payload
        )
    }

    func testSilentShortTrackIsUnavailableForDurationAndSilence() {
        var accumulator = AudioQualityAccumulator(sampleRate: 48_000, channelCount: 1)
        accumulator.observe(chunk: chunk(track: .microphone, samples: [Int16](repeating: 0, count: 4_800)))
        let observations = accumulator.finish()
        XCTAssertEqual(observations.version, "audio-quality-v1")
        XCTAssertEqual(observations.durationSeconds, 0.1, accuracy: 1e-9)
        XCTAssertTrue(observations.allSilence)
        XCTAssertEqual(observations.unavailableDimensions, ["duration", "silence"])
    }

    func testClippingAndDCOffsetFlipAvailability() {
        var accumulator = AudioQualityAccumulator(sampleRate: 48_000, channelCount: 1)
        let clipped = [Int16](repeating: Int16.max, count: 48_000)   // 1 s, every sample clipped, DC ≈ 1.0
        accumulator.observe(chunk: chunk(track: .microphone, samples: clipped))
        let observations = accumulator.finish()
        XCTAssertEqual(observations.clippedRatio, 1.0, accuracy: 1e-9)
        XCTAssertGreaterThan(observations.dcOffset, 0.9)
        XCTAssertFalse(observations.allSilence)
        XCTAssertEqual(observations.unavailableDimensions, ["clipping", "dc-offset"])
    }

    func testStereoImbalanceIsMeasuredBeforeDownmix() {
        var accumulator = AudioQualityAccumulator(sampleRate: 48_000, channelCount: 2)
        var samples = [Int16]()
        for index in 0..<48_000 { samples.append(index % 2 == 0 ? 8_000 : -8_000); samples.append(0) } // left square wave, right silent
        accumulator.observe(chunk: chunk(track: .systemAudio, samples: samples))
        let observations = accumulator.finish()
        XCTAssertNotNil(observations.channelImbalanceDecibels)
        XCTAssertGreaterThan(observations.channelImbalanceDecibels ?? 0, 20)
        XCTAssertEqual(observations.unavailableDimensions, ["channel-imbalance"])
    }

    func testDiscontinuitiesAreCountedAndCleanAudioIsFullyAvailable() {
        var accumulator = AudioQualityAccumulator(sampleRate: 48_000, channelCount: 1)
        let tone = (0..<48_000).map { Int16(8_000 * sin(2 * Double.pi * 440 * Double($0) / 48_000)) }
        accumulator.observe(chunk: chunk(track: .microphone, samples: tone))
        accumulator.noteDiscontinuity()
        let observations = accumulator.finish()
        XCTAssertEqual(observations.discontinuityCount, 1)
        XCTAssertEqual(observations.unavailableDimensions, [])
        XCTAssertEqual(observations.sourceSampleCount, 48_000)
    }
}
```

- [ ] **Step 2: Run the parse check and record the expected failure**

Run: `swiftc -parse apps/macos/TAMForgeTests/AudioQualityObservationsTests.swift`
Expected: parses. CI (`macos-native`) would fail to compile with `cannot find type 'AudioQualityAccumulator' in scope`; do not run xcodebuild locally. Commit the test alone first so CI records the RED:

```bash
git add apps/macos/TAMForgeTests/AudioQualityObservationsTests.swift apps/macos/TAMForge.xcodeproj/project.pbxproj
git commit -m "test(speech): specify versioned audio quality observations"
```

(Register the test file in `project.pbxproj` in this commit: a `PBXFileReference` with `path = AudioQualityObservationsTests.swift`, a `PBXBuildFile` for it, add it to the tests group children (the group containing `RecordingFeatureTests.swift`) and to the test target Sources phase (the phase listing `RecordingFeatureTests.swift in Sources`).)

- [ ] **Step 3: Implement the accumulator**

```swift
import Foundation

struct AudioQualityThresholds: Sendable, Equatable {
    static let v1 = AudioQualityThresholds(
        minimumDurationSeconds: 1.0,
        silencePeak: 16,
        maximumClippedRatio: 0.01,
        maximumDCOffset: 0.05,
        maximumChannelImbalanceDecibels: 20.0
    )

    let minimumDurationSeconds: Double
    let silencePeak: Int
    let maximumClippedRatio: Double
    let maximumDCOffset: Double
    let maximumChannelImbalanceDecibels: Double
}

// Observable signal conditions only. No calibrated SNR claim; a failed
// threshold marks a dimension unavailable and never lowers a learner score.
struct AudioQualityObservations: Sendable, Equatable {
    static let version = "audio-quality-v1"

    let version: String
    let sampleRate: Int
    let channelCount: Int
    let sourceSampleCount: Int64
    let durationSeconds: Double
    let peakAbsolute: Int
    let allSilence: Bool
    let clippedRatio: Double
    let dcOffset: Double
    let channelImbalanceDecibels: Double?
    let discontinuityCount: Int
    let unavailableDimensions: [String]
}

struct AudioQualityAccumulator: Sendable {
    private let sampleRate: Int
    private let channelCount: Int
    private var frameCount: Int64 = 0
    private var sampleSum: Double = 0
    private var sampleCount: Int64 = 0
    private var clippedCount: Int64 = 0
    private var peak = 0
    private var channelEnergy: [Double]
    private var discontinuityCount = 0

    init(sampleRate: Int, channelCount: Int) {
        self.sampleRate = sampleRate
        self.channelCount = channelCount
        channelEnergy = Array(repeating: 0, count: channelCount)
    }

    mutating func observe(chunk: RecordingPCMChunk) {
        frameCount += Int64(chunk.sampleCount)
        chunk.payload.withUnsafeBytes { raw in
            let samples = raw.bindMemory(to: Int16.self)
            for index in samples.indices {
                let value = Int(Int16(littleEndian: samples[index]))
                let magnitude = abs(value)
                if magnitude >= Int(Int16.max) { clippedCount += 1 }
                if magnitude > peak { peak = magnitude }
                sampleSum += Double(value)
                sampleCount += 1
                let scaled = Double(value) / 32_768
                channelEnergy[index % channelCount] += scaled * scaled
            }
        }
    }

    mutating func noteDiscontinuity() { discontinuityCount += 1 }

    func finish(thresholds: AudioQualityThresholds = .v1) -> AudioQualityObservations {
        let duration = Double(frameCount) / Double(sampleRate)
        let clippedRatio = sampleCount == 0 ? 0 : Double(clippedCount) / Double(sampleCount)
        let dcOffset = sampleCount == 0 ? 0 : abs(sampleSum / Double(sampleCount)) / 32_768
        let allSilence = peak <= thresholds.silencePeak
        var imbalance: Double?
        if channelCount == 2 {
            let floor = 1e-12
            let left = max(channelEnergy[0], floor)
            let right = max(channelEnergy[1], floor)
            imbalance = abs(10 * log10(left / right))
        }
        var unavailable: [String] = []
        if duration < thresholds.minimumDurationSeconds { unavailable.append("duration") }
        if allSilence { unavailable.append("silence") }
        if clippedRatio > thresholds.maximumClippedRatio { unavailable.append("clipping") }
        if dcOffset > thresholds.maximumDCOffset { unavailable.append("dc-offset") }
        if let imbalance, imbalance > thresholds.maximumChannelImbalanceDecibels {
            unavailable.append("channel-imbalance")
        }
        return AudioQualityObservations(
            version: Self.version,
            sampleRate: sampleRate,
            channelCount: channelCount,
            sourceSampleCount: frameCount,
            durationSeconds: duration,
            peakAbsolute: peak,
            allSilence: allSilence,
            clippedRatio: clippedRatio,
            dcOffset: dcOffset,
            channelImbalanceDecibels: imbalance,
            discontinuityCount: discontinuityCount,
            unavailableDimensions: unavailable.sorted()
        )
    }

    private static let version = AudioQualityObservations.version
}
```

Note: `unavailableDimensions` is sorted alphabetically, which is why the silent test expects `["duration", "silence"]` and the clipping test `["clipping", "dc-offset"]`.

- [ ] **Step 4: Register the production file and parse-check**

Add `AudioQualityObservations.swift` to `project.pbxproj`: a new `PBXGroup` `Speech` (path `Speech`, sourceTree `"<group>"`) under the `Features` group children, a `PBXFileReference`, and `PBXBuildFile` entries in both Sources phases that list `RecordingUploader.swift in Sources`.

Run: `swiftc -parse apps/macos/TAMForge/Features/Speech/AudioQualityObservations.swift && plutil -lint apps/macos/TAMForge.xcodeproj/project.pbxproj && git diff --check`
Expected: parses, `OK`, no whitespace errors.

- [ ] **Step 5: Commit**

```bash
git add apps/macos/TAMForge/Features/Speech/AudioQualityObservations.swift apps/macos/TAMForge.xcodeproj/project.pbxproj
git commit -m "feat(speech): add versioned audio quality observations"
```

### Task 2: Deterministic 16 kHz derivation with lineage

**Files:**
- Create: `apps/macos/TAMForge/Features/Speech/ASRAudioDerivation.swift`
- Create: `apps/macos/TAMForgeTests/ASRAudioDerivationTests.swift`
- Modify: `apps/macos/TAMForge.xcodeproj/project.pbxproj` (register both files exactly like Task 1)

**Interfaces:**
- Consumes: `AudioQualityAccumulator`, `AudioQualityObservations` from Task 1; `RecordingPCMChunk`, `RecordingTrackKind`, `RecordingPCMFormat` from `RecordingModels.swift`.
- Produces:
  ```swift
  enum ASRDerivationVersion { static let current = "tamforge-asr16k-v1" }
  enum ASRDerivationError: Error, Equatable {
      case unsupportedFormat, chunkOutOfOrder(expected: Int64, actual: Int64), trackMismatch
  }
  struct ASRDerivationLineage: Sendable, Equatable {
      let recordingID: UUID
      let track: RecordingTrackKind
      let derivationVersion: String            // "tamforge-asr16k-v1"
      let sourceSampleRate: Int                // 48_000
      let sourceChannelCount: Int
      let sourceSampleCount: Int64             // canonical frames covered, gaps included
      let outputSampleRate: Int                // 16_000
      let outputSampleCount: Int64
      let zeroFilledGaps: [RecordingGap]       // reason .missingAudio, in source samples
      let sourcePCMSHA256: String              // hex of concatenated source payloads (gaps as zeros)
      let derivedPCMSHA256: String             // hex of the whole Int16 little-endian derivative
      let quality: AudioQualityObservations
  }
  struct ASRDerivedBlock: Sendable, Equatable {
      let outputSampleStart: Int64
      let samples: [Int16]                     // 16 kHz mono
  }
  final class ASRAudioDeriver {
      init(recordingID: UUID, track: RecordingTrackKind)
      func append(_ chunk: RecordingPCMChunk) throws -> ASRDerivedBlock?   // nil when fewer than one output sample is ready
      func finish() -> (block: ASRDerivedBlock?, lineage: ASRDerivationLineage)
  }
  ```

- [ ] **Step 1: Write the failing tests**

```swift
import CryptoKit
import XCTest
@testable import TAMForge

final class ASRAudioDerivationTests: XCTestCase {
    private let recordingID = UUID(uuidString: "11111111-1111-4111-8111-111111111111")!

    private func chunk(track: RecordingTrackKind, samples: [Int16], sampleStart: Int64) -> RecordingPCMChunk {
        let channels = track == .microphone ? 1 : 2
        var payload = Data(capacity: samples.count * 2)
        for sample in samples { withUnsafeBytes(of: sample.littleEndian) { payload.append(contentsOf: $0) } }
        return RecordingPCMChunk(
            track: track, presentationNanoseconds: 0, sampleStart: sampleStart,
            sampleCount: samples.count / channels,
            format: try! RecordingPCMFormat(track: track, channelCount: channels),
            source: .init(sampleRate: 48_000, channelCount: channels, deviceID: "test", initialRoute: "test", conversionVersion: 1, presentationNanoseconds: 0),
            payload: payload)
    }

    private func sine(frequency: Double, seconds: Double, amplitude: Double = 8_000) -> [Int16] {
        (0..<Int(48_000 * seconds)).map { Int16(amplitude * sin(2 * Double.pi * frequency * Double($0) / 48_000)) }
    }

    private func derive(_ chunks: [RecordingPCMChunk], track: RecordingTrackKind) throws -> ([Int16], ASRDerivationLineage) {
        let deriver = ASRAudioDeriver(recordingID: recordingID, track: track)
        var output: [Int16] = []
        for chunk in chunks { if let block = try deriver.append(chunk) { output += block.samples } }
        let (last, lineage) = deriver.finish()
        if let last { output += last.samples }
        return (output, lineage)
    }

    private func zeroCrossings(_ samples: ArraySlice<Int16>) -> Int {
        var count = 0
        var previous = samples.first ?? 0
        for sample in samples.dropFirst() { if (previous < 0) != (sample < 0) { count += 1 }; previous = sample }
        return count
    }

    func testOneKilohertzSineKeepsFrequencyDurationAndVersion() throws {
        let (output, lineage) = try derive([chunk(track: .microphone, samples: sine(frequency: 1_000, seconds: 1), sampleStart: 0)], track: .microphone)
        XCTAssertEqual(output.count, 16_000)
        XCTAssertEqual(lineage.derivationVersion, "tamforge-asr16k-v1")
        XCTAssertEqual(lineage.outputSampleCount, 16_000)
        XCTAssertEqual(lineage.sourceSampleCount, 48_000)
        // 1 kHz has 2 000 zero crossings per second; ignore the FIR warm-up edges.
        XCTAssertEqual(zeroCrossings(output[1_000..<15_000]), 1_750, accuracy: 4)
        XCTAssertGreaterThan(output[1_000..<15_000].map { abs(Int($0)) }.max() ?? 0, 7_000)
    }

    func testStereoDownmixUsesFixedMatrixBeforeRateReduction() throws {
        var stereo: [Int16] = []
        for value in sine(frequency: 440, seconds: 1) { stereo.append(value); stereo.append(0) }
        let (output, lineage) = try derive([chunk(track: .systemAudio, samples: stereo, sampleStart: 0)], track: .systemAudio)
        let peak = output[2_000..<14_000].map { abs(Int($0)) }.max() ?? 0
        XCTAssertEqual(peak, 4_000, accuracy: 120)  // (L + R) / 2 halves a one-sided signal
        XCTAssertEqual(lineage.sourceChannelCount, 2)
        XCTAssertGreaterThan(lineage.quality.channelImbalanceDecibels ?? 0, 20)
    }

    func testGapsAreZeroFilledAndMappedToSourcePositions() throws {
        let tone = sine(frequency: 440, seconds: 0.5)
        let chunks = [
            chunk(track: .microphone, samples: tone, sampleStart: 0),
            chunk(track: .microphone, samples: tone, sampleStart: 48_000),   // 24 000-sample hole
        ]
        let (output, lineage) = try derive(chunks, track: .microphone)
        XCTAssertEqual(output.count, 24_000)
        XCTAssertEqual(lineage.zeroFilledGaps, [RecordingGap(track: .microphone, sampleStart: 24_000, sampleCount: 24_000, reason: .missingAudio)])
        XCTAssertEqual(lineage.quality.discontinuityCount, 1)
        XCTAssertTrue(output[9_000..<15_000].allSatisfy { abs(Int($0)) < 8 })   // hole is silent (after FIR tail)
        XCTAssertGreaterThan(output[17_000..<23_000].map { abs(Int($0)) }.max() ?? 0, 7_000)
    }

    func testChunkBoundariesDoNotChangeOutput() throws {
        let tone = sine(frequency: 700, seconds: 1)
        let whole = try derive([chunk(track: .microphone, samples: tone, sampleStart: 0)], track: .microphone)
        var split: [RecordingPCMChunk] = []
        var start = 0
        for size in [7, 4_800, 1, 12_345, 31_847] {
            split.append(chunk(track: .microphone, samples: Array(tone[start..<start + size]), sampleStart: Int64(start)))
            start += size
        }
        let pieces = try derive(split, track: .microphone)
        XCTAssertEqual(whole.0, pieces.0)
        XCTAssertEqual(whole.1.derivedPCMSHA256, pieces.1.derivedPCMSHA256)
    }

    func testFixedInputProducesFixedHashAndLeavesSourceUntouched() throws {
        let source = chunk(track: .microphone, samples: sine(frequency: 300, seconds: 0.25, amplitude: 12_000), sampleStart: 0)
        let before = source.payload
        let (output, lineage) = try derive([source], track: .microphone)
        var bytes = Data()
        for sample in output { withUnsafeBytes(of: sample.littleEndian) { bytes.append(contentsOf: $0) } }
        XCTAssertEqual(lineage.derivedPCMSHA256, SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined())
        XCTAssertEqual(lineage.sourcePCMSHA256, SHA256.hash(data: before).map { String(format: "%02x", $0) }.joined())
        XCTAssertEqual(source.payload, before)
        XCTAssertEqual(lineage.recordingID, recordingID)
        XCTAssertEqual(lineage.outputSampleRate, 16_000)
        // Pin the bytes: any change to the filter or rounding must bump the version.
        XCTAssertEqual(lineage.derivedPCMSHA256, ASRAudioDerivationTests.pinnedHash300Hz, "update pinnedHash300Hz only together with ASRDerivationVersion")
    }

    static let pinnedHash300Hz = "REPLACE-WITH-HASH-FROM-FIRST-GREEN-CI-RUN"

    func testOutOfOrderOrMismatchedChunksFailClosed() {
        let deriver = ASRAudioDeriver(recordingID: recordingID, track: .microphone)
        _ = try? deriver.append(chunk(track: .microphone, samples: sine(frequency: 440, seconds: 0.1), sampleStart: 4_800))
        XCTAssertThrowsError(try deriver.append(chunk(track: .microphone, samples: sine(frequency: 440, seconds: 0.1), sampleStart: 0))) { error in
            XCTAssertEqual(error as? ASRDerivationError, .chunkOutOfOrder(expected: 9_600, actual: 0))
        }
        XCTAssertThrowsError(try ASRAudioDeriver(recordingID: recordingID, track: .microphone)
            .append(chunk(track: .systemAudio, samples: [0, 0], sampleStart: 0))) { error in
            XCTAssertEqual(error as? ASRDerivationError, .trackMismatch)
        }
    }

    func testEmptyInputYieldsEmptySilentLineage() {
        let deriver = ASRAudioDeriver(recordingID: recordingID, track: .microphone)
        let (block, lineage) = deriver.finish()
        XCTAssertNil(block)
        XCTAssertEqual(lineage.outputSampleCount, 0)
        XCTAssertTrue(lineage.quality.allSilence)
        XCTAssertEqual(lineage.zeroFilledGaps, [])
    }
}
```

The pinned-hash test is intentionally RED until the first green CI run of the implementation prints the real hash; the implementer replaces `pinnedHash300Hz` from the CI log of that run (the `XCTAssertEqual` failure message contains the actual value), then pushes again.

- [ ] **Step 2: Parse-check and commit the RED test**

Run: `swiftc -parse apps/macos/TAMForgeTests/ASRAudioDerivationTests.swift`
Expected: parses; CI compile fails with `cannot find 'ASRAudioDeriver' in scope`.

```bash
git add apps/macos/TAMForgeTests/ASRAudioDerivationTests.swift apps/macos/TAMForge.xcodeproj/project.pbxproj
git commit -m "test(speech): specify deterministic 16 kHz ASR derivation"
```

- [ ] **Step 3: Implement the deriver**

```swift
import CryptoKit
import Foundation

enum ASRDerivationVersion {
    static let current = "tamforge-asr16k-v1"
}

enum ASRDerivationError: Error, Equatable {
    case unsupportedFormat
    case chunkOutOfOrder(expected: Int64, actual: Int64)
    case trackMismatch
}

struct ASRDerivationLineage: Sendable, Equatable {
    let recordingID: UUID
    let track: RecordingTrackKind
    let derivationVersion: String
    let sourceSampleRate: Int
    let sourceChannelCount: Int
    let sourceSampleCount: Int64
    let outputSampleRate: Int
    let outputSampleCount: Int64
    let zeroFilledGaps: [RecordingGap]
    let sourcePCMSHA256: String
    let derivedPCMSHA256: String
    let quality: AudioQualityObservations
}

struct ASRDerivedBlock: Sendable, Equatable {
    let outputSampleStart: Int64
    let samples: [Int16]
}

// Fixed (L+R)/2 downmix, then a linear-phase Kaiser-windowed-sinc low-pass
// and 3:1 decimation. Output sample n is aligned to source sample 3n by
// compensating the filter's group delay, so ASR timestamps map back exactly.
final class ASRAudioDeriver {
    static let sourceSampleRate = 48_000
    static let outputSampleRate = 16_000
    private static let decimation = 3
    private static let taps = 95
    private static let coefficients: [Double] = makeCoefficients()

    private let recordingID: UUID
    private let track: RecordingTrackKind
    private let channelCount: Int
    private var expectedSampleStart: Int64 = 0
    private var history: [Double] = []          // mono source samples not yet fully consumed
    private var consumedSourceSamples: Int64 = 0 // source samples already turned into output
    private var outputCount: Int64 = 0
    private var zeroFilledGaps: [RecordingGap] = []
    private var quality: AudioQualityAccumulator
    private var sourceHasher = SHA256()
    private var derivedHasher = SHA256()

    init(recordingID: UUID, track: RecordingTrackKind) {
        self.recordingID = recordingID
        self.track = track
        channelCount = track == .microphone ? 1 : 2
        quality = AudioQualityAccumulator(sampleRate: Self.sourceSampleRate, channelCount: channelCount)
        // Pre-fill half a filter of silence so output sample 0 is centred on source sample 0.
        history = Array(repeating: 0, count: (Self.taps - 1) / 2)
    }

    func append(_ chunk: RecordingPCMChunk) throws -> ASRDerivedBlock? {
        guard chunk.track == track else { throw ASRDerivationError.trackMismatch }
        guard chunk.format.sampleRate == Self.sourceSampleRate,
              chunk.format.channelCount == channelCount,
              chunk.format.sampleEncoding == "pcm_s16le"
        else { throw ASRDerivationError.unsupportedFormat }
        guard chunk.sampleStart >= expectedSampleStart else {
            throw ASRDerivationError.chunkOutOfOrder(expected: expectedSampleStart, actual: chunk.sampleStart)
        }
        if chunk.sampleStart > expectedSampleStart {
            let missing = Int(chunk.sampleStart - expectedSampleStart)
            zeroFilledGaps.append(.init(track: track, sampleStart: expectedSampleStart, sampleCount: missing, reason: .missingAudio))
            quality.noteDiscontinuity()
            history.append(contentsOf: repeatElement(0, count: missing))
            sourceHasher.update(data: Data(count: missing * channelCount * 2))
        }
        quality.observe(chunk: chunk)
        sourceHasher.update(data: chunk.payload)
        chunk.payload.withUnsafeBytes { raw in
            let samples = raw.bindMemory(to: Int16.self)
            var frame = 0
            while frame < chunk.sampleCount {
                var sum = 0.0
                for channel in 0..<channelCount {
                    sum += Double(Int16(littleEndian: samples[frame * channelCount + channel]))
                }
                history.append(sum / Double(channelCount))
                frame += 1
            }
        }
        expectedSampleStart = chunk.sampleStart + Int64(chunk.sampleCount)
        return drain(flush: false)
    }

    func finish() -> (block: ASRDerivedBlock?, lineage: ASRDerivationLineage) {
        // Pad with the other half filter so the last real samples get a full window.
        history.append(contentsOf: repeatElement(0, count: (Self.taps - 1) / 2))
        let block = drain(flush: true)
        let lineage = ASRDerivationLineage(
            recordingID: recordingID,
            track: track,
            derivationVersion: ASRDerivationVersion.current,
            sourceSampleRate: Self.sourceSampleRate,
            sourceChannelCount: channelCount,
            sourceSampleCount: expectedSampleStart,
            outputSampleRate: Self.outputSampleRate,
            outputSampleCount: outputCount,
            zeroFilledGaps: zeroFilledGaps,
            sourcePCMSHA256: Self.hex(sourceHasher.finalize()),
            derivedPCMSHA256: Self.hex(derivedHasher.finalize()),
            quality: quality.finish()
        )
        return (block, lineage)
    }

    // Emit every output sample whose full filter window is available. When
    // flushing, stop exactly at ceil(sourceSamples / 3) outputs so gaps at the
    // end are not invented and output n always maps to source 3n.
    private func drain(flush: Bool) -> ASRDerivedBlock? {
        let half = (Self.taps - 1) / 2
        let totalOutputs = flush
            ? Int64((expectedSampleStart + Int64(Self.decimation) - 1) / Int64(Self.decimation))
            : Int64.max
        var produced: [Int16] = []
        let start = outputCount
        while outputCount < totalOutputs {
            let centre = Int(outputCount * Int64(Self.decimation) - consumedSourceSamples) + half
            guard centre + half < history.count else { break }
            var accumulator = 0.0
            for tap in 0..<Self.taps {
                accumulator += Self.coefficients[tap] * history[centre + half - tap]
            }
            let rounded = (accumulator).rounded(.toNearestOrEven)
            produced.append(Int16(clamping: Int(rounded)))
            outputCount += 1
        }
        // Drop history that no future output window can reach.
        let keep = Int(outputCount * Int64(Self.decimation) - consumedSourceSamples)
        if keep > 0 {
            history.removeFirst(min(keep, history.count))
            consumedSourceSamples += Int64(min(keep, history.count + keep))
        }
        guard !produced.isEmpty else { return nil }
        var bytes = Data(capacity: produced.count * 2)
        for sample in produced { withUnsafeBytes(of: sample.littleEndian) { bytes.append(contentsOf: $0) } }
        derivedHasher.update(data: bytes)
        return ASRDerivedBlock(outputSampleStart: start, samples: produced)
    }

    private static func makeCoefficients() -> [Double] {
        let cutoff = 7_000.0 / Double(sourceSampleRate)   // normalised (cycles/sample)
        let beta = 6.0
        let middle = Double(taps - 1) / 2
        var raw = (0..<taps).map { index -> Double in
            let n = Double(index) - middle
            let sinc = n == 0 ? 2 * cutoff : sin(2 * .pi * cutoff * n) / (.pi * n)
            let ratio = 2 * n / Double(taps - 1)
            let window = besselI0(beta * (1 - ratio * ratio).squareRoot()) / besselI0(beta)
            return sinc * window
        }
        let gain = raw.reduce(0, +)
        raw = raw.map { $0 / gain }
        return raw
    }

    private static func besselI0(_ x: Double) -> Double {
        var sum = 1.0, term = 1.0
        let half = x / 2
        var k = 1.0
        while term > 1e-12 * sum {
            term *= (half / k) * (half / k)
            sum += term
            k += 1
        }
        return sum
    }

    private static func hex(_ digest: SHA256.Digest) -> String {
        digest.map { String(format: "%02x", $0) }.joined()
    }
}
```

Implementer notes:
- The `drain` bookkeeping must satisfy: `history[i]` is source sample `consumedSourceSamples - half + i` (the initial half-filter of zeros represents negative indices). Verify with `testChunkBoundariesDoNotChangeOutput`; if the trimming arithmetic is off, prefer keeping a simpler invariant (never trim more than `history.count - taps`) over cleverness.
- `Int16(clamping:)` after `.toNearestOrEven` rounding keeps determinism; never use `Float`.
- `sourcePCMSHA256` hashes payload bytes plus zero bytes for gaps, in order, so it equals the SHA-256 of the single payload in the fixed-hash test.

- [ ] **Step 4: Register the production file, parse-check, commit, push, read the pinned hash from CI**

Run: `swiftc -parse apps/macos/TAMForge/Features/Speech/ASRAudioDerivation.swift && plutil -lint apps/macos/TAMForge.xcodeproj/project.pbxproj && git diff --check`
Expected: parses, `OK`, clean.

```bash
git add apps/macos/TAMForge/Features/Speech/ASRAudioDerivation.swift apps/macos/TAMForge.xcodeproj/project.pbxproj
git commit -m "feat(speech): derive deterministic 16 kHz ASR audio with lineage"
git push -u origin codex/issue-41-asr-audio-derivation
```

Wait for the `macos-native` job. Expected: every `ASRAudioDerivationTests` case green except `testFixedInputProducesFixedHashAndLeavesSourceUntouched`, whose failure message prints the actual `derivedPCMSHA256`. Copy that 64-hex value into `pinnedHash300Hz`, parse-check, commit `test(speech): pin the v1 derivation hash`, push, and confirm `macos-native` is fully green.

### Task 3: Issue and handoff notes

**Files:**
- Modify: `docs/superpowers/specs/2026-09-08-asr-audio-derivation-design.md` (add the "Verification" pointer to the pinned-hash rule)
- Comment on GitHub issue #41 (not a file): state that derivation is Mac-side per the 2026-08-28 spec, that verification is `xcodebuild … -only-testing:TAMForgeTests/ASRAudioDerivationTests` (plus `AudioQualityObservationsTests`), and that pytest paths in the issue body are superseded.

- [ ] **Step 1: Add the pinned-hash rule to the spec's Testing section**

Append: "The v1 derivative hash of the 300 Hz fixture is pinned in `ASRAudioDerivationTests.pinnedHash300Hz`; any filter or rounding change must bump `ASRDerivationVersion.current` and re-pin."

- [ ] **Step 2: Commit and post the issue comment**

```bash
git add docs/superpowers/specs/2026-09-08-asr-audio-derivation-design.md
git commit -m "docs(speech): pin the derivation hash rule"
gh issue comment 41 --repo fgomensoro/tam-forge --body "Derivation runs on the Mac (spec 2026-08-28 §7.1, owner decision 2026-09-08). Verification: xcodebuild … -only-testing:TAMForgeTests/ASRAudioDerivationTests -only-testing:TAMForgeTests/AudioQualityObservationsTests test (required CI). The pytest paths in this issue are superseded; see docs/superpowers/specs/2026-09-08-asr-audio-derivation-design.md."
```
