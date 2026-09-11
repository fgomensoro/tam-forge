import Foundation

// The seam RecordingCoordinator reads sealed audio through, so
// transcription depends on an abstraction rather than the concrete
// encrypted spool. EncryptedRecordingSpoolFactory is the only production
// conformance; tests fake the whole protocol.
protocol RecordingAudioReading: Sendable {
    /// Canonical chunks of one track from a sealed recording, in spool
    /// order, streamed so the caller never holds the whole track at once.
    func sealedChunks(
        recordingID: UUID, track: RecordingTrackKind
    ) async throws -> AsyncThrowingStream<RecordingPCMChunk, any Error>
}

extension EncryptedRecordingSpoolFactory: RecordingAudioReading {
    func sealedChunks(
        recordingID: UUID, track: RecordingTrackKind
    ) async throws -> AsyncThrowingStream<RecordingPCMChunk, any Error> {
        try await EncryptedRecordingSpool.streamTrack(
            recordingID: recordingID, rootURL: rootURL, keyStore: keyStore, track: track
        )
    }
}
