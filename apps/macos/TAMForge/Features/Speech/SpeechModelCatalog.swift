import Foundation

// Resolves installed model paths under Application Support so the UI and
// tests can tell "no model" from "transcription failed". Fetching models
// into this directory is scripts/dev/fetch_whisper_models.sh's job (issue
// #42 Task 1); this type never downloads anything.
struct SpeechModelCatalog: Sendable {
    static let transcriptionModelFilename = "ggml-small.en-q5_1.bin"
    static let vadModelFilename = "ggml-silero-v5.1.2.bin"
    // Pinned in config/speech-models.yaml; recorded here (never hashed at
    // runtime, which would be expensive) so WhisperTranscriber can report it
    // as part of SpeechRuntimeIdentity. scripts/ci/tests/test_speech_models_manifest.py
    // (issue #42 Task 4) asserts this stays equal to the manifest's pin.
    static let transcriptionModelSHA256 = "bfdff4894dcb76bbf647d56263ea2a96645423f1669176f4844a1bf8e478ad30"

    let directory: URL

    init(directory: URL = SpeechModelCatalog.defaultDirectory) {
        self.directory = directory
    }

    static var defaultDirectory: URL {
        let applicationSupport = FileManager.default.urls(
            for: .applicationSupportDirectory, in: .userDomainMask
        )[0]
        return applicationSupport
            .appendingPathComponent("TAM Forge", isDirectory: true)
            .appendingPathComponent("Models", isDirectory: true)
    }

    var transcriptionModelURL: URL? {
        url(forFilename: Self.transcriptionModelFilename)
    }

    var vadModelURL: URL? {
        url(forFilename: Self.vadModelFilename)
    }

    func requireTranscriptionModel() throws -> URL {
        guard let url = transcriptionModelURL else {
            throw SpeechTranscriptionError.modelUnavailable(
                "Transcription model \(Self.transcriptionModelFilename) is not installed"
            )
        }
        return url
    }

    private func url(forFilename filename: String) -> URL? {
        let candidate = directory.appendingPathComponent(filename, isDirectory: false)
        return FileManager.default.fileExists(atPath: candidate.path) ? candidate : nil
    }
}
