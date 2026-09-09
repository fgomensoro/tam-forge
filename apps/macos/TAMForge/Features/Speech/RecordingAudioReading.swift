import Foundation

// The seam RecordingCoordinator reads sealed audio through, so
// transcription depends on an abstraction rather than the concrete
// encrypted spool. EncryptedRecordingSpoolFactory is the only production
// conformance; tests fake the whole protocol.
protocol RecordingAudioReading: Sendable {
    /// Ordered canonical chunks of one track from a sealed recording.
    func sealedChunks(recordingID: UUID, track: RecordingTrackKind) async throws -> [RecordingPCMChunk]
}

extension EncryptedRecordingSpoolFactory: RecordingAudioReading {
    func sealedChunks(recordingID: UUID, track: RecordingTrackKind) async throws -> [RecordingPCMChunk] {
        let recovery = try await EncryptedRecordingSpool.recover(
            recordingID: recordingID, rootURL: rootURL, keyStore: keyStore
        )
        return recovery.records
            .map(\.chunk)
            .filter { $0.track == track }
            .sorted { $0.sampleStart < $1.sampleStart }
    }
}
