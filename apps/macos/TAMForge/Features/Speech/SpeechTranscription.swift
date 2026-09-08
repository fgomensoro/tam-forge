import Foundation

// The seam every transcription engine implements: the real whisper.cpp
// adapter (WhisperTranscriber, issue #42 Task 3) and FakeSpeechEngine in
// tests. Keeping this file free of `import whisper` is what lets unit
// tests run without the vendored framework.

struct SpeechTranscriptionRequest: Sendable, Equatable {
    let samples: [Int16]            // 16 kHz mono, the whole derived stream
    let lineage: ASRDerivationLineage
}

extension SpeechTranscriptionRequest {
    // Shared by every engine so "unsupported audio" is rejected identically
    // whether the caller is the fake used in tests or WhisperTranscriber.
    func validate() throws {
        guard lineage.outputSampleRate == 16_000 else {
            throw SpeechTranscriptionError.unsupportedSampleRate(lineage.outputSampleRate)
        }
        guard !samples.isEmpty else {
            throw SpeechTranscriptionError.emptyAudio
        }
    }
}

struct SpeechTranscribedWord: Sendable, Equatable {
    let text: String
    let startMilliseconds: Int64    // relative to the derived stream
    let endMilliseconds: Int64
    let probability: Double
}

struct SpeechTranscribedSegment: Sendable, Equatable {
    let text: String
    let startMilliseconds: Int64
    let endMilliseconds: Int64
    let words: [SpeechTranscribedWord]
}

struct SpeechRuntimeIdentity: Sendable, Equatable {
    let runtimeVersion: String      // whisper.cpp release, e.g. "b4938"
    let modelFilename: String
    let modelSHA256: String
    let usedMetal: Bool
    let usedBuiltInVAD: Bool
    let language: String            // always "en"
}

struct SpeechTranscriptionResult: Sendable, Equatable {
    let segments: [SpeechTranscribedSegment]
    let identity: SpeechRuntimeIdentity
    let lineage: ASRDerivationLineage

    var text: String {
        segments.map(\.text).joined(separator: " ").trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

enum SpeechTranscriptionError: Error, Equatable {
    case modelUnavailable(String)   // human-readable reason, no paths
    case unsupportedSampleRate(Int)
    case emptyAudio
    case cancelled
    case runtimeFailure(code: Int32)
}

protocol SpeechTranscribing: Sendable {
    func transcribe(_ request: SpeechTranscriptionRequest) async throws -> SpeechTranscriptionResult
}
