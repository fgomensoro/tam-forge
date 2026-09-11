import CryptoKit
import Darwin
import Foundation

enum RecordingUploadError: Error, Equatable {
    case unsealedSpool
    case missingTimeline
    case invalidCoverage
    case unsupportedConversion
    case fileChanged
    case unauthorized
    case offline
    case conflict
    case invalidResponse
    case server(statusCode: Int)
}

extension RecordingUploadError {
    // The only safe representation of a transcript-submission failure to
    // log: every case here is either content-free or, for `.server`, an
    // Int status code, so this description can never carry transcript
    // text. Any other error type (URLError, a decoding error, ...) logs
    // only its Swift type name, never a message, since this call site
    // cannot audit every error type the network stack might throw.
    static func safeLogDescription(for error: Error) -> String {
        if let uploadError = error as? RecordingUploadError {
            return String(describing: uploadError)
        }
        return "\(type(of: error))"
    }

    // A permanent rejection is a 4xx that means the submitted body itself is
    // invalid and resubmitting the identical payload can never succeed: 400
    // (malformed request), 413 (body too large), and 422 (schema/bounds
    // validation failure -- see `TranscriptTooLarge`/FastAPI validation in
    // `speech/routes.py`). Every other 4xx this call site can see is a
    // timing artifact, not a body problem, and must stay retryable. 404
    // means the recording row does not exist *yet*: `submitTranscript` races
    // the create/upload/seal pass the same `stop()` call started, so a 404
    // here is ordinary and self-heals once that pass catches up on a later
    // worker pass -- treating it as permanent would drop the cached payload
    // with no way to recompute it (`beginTranscription` only runs from
    // `stop()`), reintroducing the never-released spool this feature exists
    // to fix. 409 arrives as `.conflict`, not `.server`, and means "audio is
    // not stored yet," resolved the same way -- already excluded here. A 5xx
    // `.server` case (`TranscriptUnavailable`, or an unexpected server
    // error) is the backend's own distinctly-retryable error and must keep
    // retrying.
    var isPermanentTranscriptRejection: Bool {
        if case let .server(statusCode) = self { return [400, 413, 422].contains(statusCode) }
        return false
    }
}

enum RecordingConversionIdentifier {
    // Unknown local conversion versions can never be declared as v1; upload
    // fails closed instead of guessing lineage.
    static func identifier(for version: Int) throws -> String {
        guard version == 1 else { throw RecordingUploadError.unsupportedConversion }
        return "tamforge-pcm16-v1"
    }
}

enum RecordingPartKeyEncoding {
    // Canonical unpadded base64url for a 32-byte key: exactly 43 characters
    // whose trailing bits round-trip; noncanonical trailing characters are
    // rejected.
    static func isCanonical(_ value: String) -> Bool {
        guard value.count == 43 else { return false }
        let padded = value
            .replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
            + "="
        guard let decoded = Data(base64Encoded: padded), decoded.count == 32 else { return false }
        let reencoded = decoded.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
        return reencoded == value
    }
}

struct RecordingSourceLineagePayload: Codable, Equatable, Sendable {
    let sampleStart: Int64
    let sampleCount: Int
    let sourceSampleRateHz: Int
    let sourceChannelCount: Int
    let deviceID: String
    let route: String
    let presentationTimeStart: Int64
    let presentationTimeEnd: Int64
    let presentationTimeTimescale: Int64
    let conversionVersion: String

    enum CodingKeys: String, CodingKey {
        case sampleStart = "sample_start"
        case sampleCount = "sample_count"
        case sourceSampleRateHz = "source_sample_rate_hz"
        case sourceChannelCount = "source_channel_count"
        case deviceID = "device_id"
        case route
        case presentationTimeStart = "presentation_time_start"
        case presentationTimeEnd = "presentation_time_end"
        case presentationTimeTimescale = "presentation_time_timescale"
        case conversionVersion = "conversion_version"
    }
}

// Builds track lineage from each original authenticated record before upload
// grouping. Only contiguous canonical coverage with identical source metadata
// coalesces; gaps and any source change start a new segment. Lineage covers
// audio only and computes its presentation end from the exact 48 kHz duration.
struct RecordingSourceLineageCoalescer: Sendable {
    private struct PendingSegment {
        var sampleStart: Int64
        var sampleCount: Int
        var sourceSampleRateHz: Int
        var sourceChannelCount: Int
        var deviceID: String
        var route: String
        var presentationTimeStart: Int64
        var conversionVersion: String
    }

    private var segments: [RecordingSourceLineagePayload] = []
    private var pending: PendingSegment?

    mutating func append(record: RecoveredSpoolRecord) throws {
        let chunk = record.chunk
        let conversion = try RecordingConversionIdentifier.identifier(
            for: chunk.source.conversionVersion
        )
        // The server caps lineage identity strings at 256 characters; truncate
        // consistently so a long route can never poison the final seal.
        let deviceID = String(chunk.source.deviceID.prefix(256))
        let route = String(chunk.source.initialRoute.prefix(256))
        guard let rate = Int(exactly: chunk.source.sampleRate.rounded()),
              rate > 0,
              !deviceID.isEmpty,
              !route.isEmpty,
              chunk.source.presentationNanoseconds >= 0
        else { throw RecordingUploadError.invalidCoverage }
        if var current = pending,
           current.sampleStart + Int64(current.sampleCount) == chunk.sampleStart,
           current.sourceSampleRateHz == rate,
           current.sourceChannelCount == chunk.source.channelCount,
           current.deviceID == deviceID,
           current.route == route,
           current.conversionVersion == conversion {
            current.sampleCount += chunk.sampleCount
            pending = current
            return
        }
        flushPending()
        pending = .init(
            sampleStart: chunk.sampleStart,
            sampleCount: chunk.sampleCount,
            sourceSampleRateHz: rate,
            sourceChannelCount: chunk.source.channelCount,
            deviceID: deviceID,
            route: route,
            presentationTimeStart: chunk.source.presentationNanoseconds,
            conversionVersion: conversion
        )
    }

    mutating func finish() -> [RecordingSourceLineagePayload] {
        flushPending()
        defer { segments.removeAll() }
        return segments
    }

    private mutating func flushPending() {
        guard let current = pending else { return }
        pending = nil
        segments.append(.init(
            sampleStart: current.sampleStart,
            sampleCount: current.sampleCount,
            sourceSampleRateHz: current.sourceSampleRateHz,
            sourceChannelCount: current.sourceChannelCount,
            deviceID: current.deviceID,
            route: current.route,
            presentationTimeStart: current.presentationTimeStart,
            presentationTimeEnd: current.presentationTimeStart
                + Int64(current.sampleCount) * 1_000_000_000
                / Int64(RecordingPCMFormat.canonicalSampleRate),
            presentationTimeTimescale: 1_000_000_000,
            conversionVersion: current.conversionVersion
        ))
    }
}

struct RecordingCanonicalFormatPayload: Codable, Equatable, Sendable {
    let sampleEncoding = "pcm_s16le"
    let sampleRateHz = 48_000
    let channelCount: Int
    let interleaved = true

    enum CodingKeys: String, CodingKey {
        case sampleEncoding = "sample_encoding"
        case sampleRateHz = "sample_rate_hz"
        case channelCount = "channel_count"
        case interleaved
    }
}

struct RecordingTrackDeclarationPayload: Codable, Equatable, Sendable {
    let trackID: String
    let kind: String
    let format: RecordingCanonicalFormatPayload
    let conversionVersion = "tamforge-pcm16-v1"

    enum CodingKeys: String, CodingKey {
        case trackID = "track_id"
        case kind
        case format
        case conversionVersion = "conversion_version"
    }
}

struct RecordingCreatePayload: Codable, Equatable, Sendable {
    let schemaVersion = 1
    let recordingID: String
    let startedAt: String
    let tracks: [RecordingTrackDeclarationPayload]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case recordingID = "recording_id"
        case startedAt = "started_at"
        case tracks
    }
}

struct RecordingPartDescriptorPayload: Codable, Equatable, Sendable {
    let sequence: Int
    let sampleStart: Int64
    let sampleCount: Int
    let byteLength: Int
    let plaintextSHA256: String

    enum CodingKeys: String, CodingKey {
        case sequence
        case sampleStart = "sample_start"
        case sampleCount = "sample_count"
        case byteLength = "byte_length"
        case plaintextSHA256 = "plaintext_sha256"
    }
}

struct RecordingGapPayload: Codable, Equatable, Sendable {
    let sampleStart: Int64
    let sampleCount: Int
    let reason: String

    enum CodingKeys: String, CodingKey {
        case sampleStart = "sample_start"
        case sampleCount = "sample_count"
        case reason
    }
}

struct RecordingTrackManifestPayload: Codable, Equatable, Sendable {
    let trackID: String
    let kind: String
    let format: RecordingCanonicalFormatPayload
    let totalSampleCount: Int64
    let parts: [RecordingPartDescriptorPayload]
    let gaps: [RecordingGapPayload]
    let sourceLineage: [RecordingSourceLineagePayload]
    let pcmSHA256: String
    let timelineSHA256: String
    let conversionVersion = "tamforge-pcm16-v1"

    enum CodingKeys: String, CodingKey {
        case trackID = "track_id"
        case kind
        case format
        case totalSampleCount = "total_sample_count"
        case parts
        case gaps
        case sourceLineage = "source_lineage"
        case pcmSHA256 = "pcm_sha256"
        case timelineSHA256 = "timeline_sha256"
        case conversionVersion = "conversion_version"
    }

    static func make(
        recordingID: UUID,
        track: RecordingTrackKind,
        parts: [RecordingPartDescriptorPayload],
        gaps: [RecordingGapPayload],
        sourceLineage: [RecordingSourceLineagePayload],
        pcmSHA256: String
    ) throws -> Self {
        let orderedParts = parts.sorted {
            ($0.sampleStart, $0.sequence) < ($1.sampleStart, $1.sequence)
        }
        let orderedGaps = gaps.sorted {
            ($0.sampleStart, $0.sampleCount) < ($1.sampleStart, $1.sampleCount)
        }
        let orderedLineage = sourceLineage.sorted {
            ($0.sampleStart, $0.sampleCount) < ($1.sampleStart, $1.sampleCount)
        }
        var segments = orderedParts.map { ($0.sampleStart, $0.sampleStart + Int64($0.sampleCount)) }
        segments.append(
            contentsOf: orderedGaps.map { ($0.sampleStart, $0.sampleStart + Int64($0.sampleCount)) }
        )
        segments.sort { ($0.0, $0.1) < ($1.0, $1.1) }
        var cursor: Int64 = 0
        for segment in segments {
            guard segment.0 == cursor, segment.1 > segment.0 else {
                throw RecordingUploadError.invalidCoverage
            }
            cursor = segment.1
        }
        guard cursor > 0,
            orderedParts.map(\.sequence) == Array(0..<orderedParts.count)
        else { throw RecordingUploadError.invalidCoverage }
        try validateLineageCoverage(parts: orderedParts, lineage: orderedLineage)
        guard orderedLineage.allSatisfy({ $0.conversionVersion == "tamforge-pcm16-v1" }) else {
            throw RecordingUploadError.unsupportedConversion
        }
        let trackID = RecordingTrackIdentity.id(recordingID: recordingID, track: track)
        let timelineHash = try timelineSHA256(
            trackID: trackID.uuidString.lowercased(),
            kind: track.rawValue,
            format: .init(channelCount: track.channelCount),
            totalSampleCount: cursor,
            parts: orderedParts,
            gaps: orderedGaps,
            sourceLineage: orderedLineage
        )
        return .init(
            trackID: trackID.uuidString.lowercased(),
            kind: track.rawValue,
            format: .init(channelCount: track.channelCount),
            totalSampleCount: cursor,
            parts: orderedParts,
            gaps: orderedGaps,
            sourceLineage: orderedLineage,
            pcmSHA256: pcmSHA256,
            timelineSHA256: timelineHash
        )
    }

    // The canonical timeline hash covers the whole manifest except both
    // digests, exactly like the backend's timeline_hash_input.
    static func timelineSHA256(of manifest: Self) throws -> String {
        try timelineSHA256(
            trackID: manifest.trackID,
            kind: manifest.kind,
            format: manifest.format,
            totalSampleCount: manifest.totalSampleCount,
            parts: manifest.parts,
            gaps: manifest.gaps,
            sourceLineage: manifest.sourceLineage
        )
    }

    private static func timelineSHA256(
        trackID: String,
        kind: String,
        format: RecordingCanonicalFormatPayload,
        totalSampleCount: Int64,
        parts: [RecordingPartDescriptorPayload],
        gaps: [RecordingGapPayload],
        sourceLineage: [RecordingSourceLineagePayload]
    ) throws -> String {
        try RecordingCanonicalJSON.sha256(
            domain: "tamforge.recording.timeline.v1",
            value: RecordingTimelineManifestPayload(
                trackID: trackID,
                kind: kind,
                format: format,
                totalSampleCount: totalSampleCount,
                parts: parts,
                gaps: gaps,
                sourceLineage: sourceLineage,
                conversionVersion: "tamforge-pcm16-v1"
            )
        )
    }

    // Mirrors the server rule: lineage covers every uploaded audio range
    // exactly once, in order, and never overlaps declared gaps.
    private static func validateLineageCoverage(
        parts: [RecordingPartDescriptorPayload],
        lineage: [RecordingSourceLineagePayload]
    ) throws {
        var audioRanges: [(start: Int64, end: Int64)] = []
        for part in parts {
            let end = part.sampleStart + Int64(part.sampleCount)
            if let last = audioRanges.last, part.sampleStart <= last.end {
                audioRanges[audioRanges.count - 1].end = Swift.max(last.end, end)
            } else {
                audioRanges.append((part.sampleStart, end))
            }
        }
        guard !audioRanges.isEmpty else {
            guard lineage.isEmpty else { throw RecordingUploadError.invalidCoverage }
            return
        }
        guard !lineage.isEmpty else { throw RecordingUploadError.invalidCoverage }
        var rangeIndex = 0
        var cursor = audioRanges[0].start
        for segment in lineage {
            guard rangeIndex < audioRanges.count,
                  segment.sampleStart == cursor,
                  segment.sampleCount > 0
            else { throw RecordingUploadError.invalidCoverage }
            let segmentEnd = segment.sampleStart + Int64(segment.sampleCount)
            guard segmentEnd <= audioRanges[rangeIndex].end else {
                throw RecordingUploadError.invalidCoverage
            }
            cursor = segmentEnd
            if cursor == audioRanges[rangeIndex].end {
                rangeIndex += 1
                if rangeIndex < audioRanges.count { cursor = audioRanges[rangeIndex].start }
            }
        }
        guard rangeIndex == audioRanges.count else {
            throw RecordingUploadError.invalidCoverage
        }
    }
}

private struct RecordingTimelineManifestPayload: Codable {
    let trackID: String
    let kind: String
    let format: RecordingCanonicalFormatPayload
    let totalSampleCount: Int64
    let parts: [RecordingPartDescriptorPayload]
    let gaps: [RecordingGapPayload]
    let sourceLineage: [RecordingSourceLineagePayload]
    let conversionVersion: String

    enum CodingKeys: String, CodingKey {
        case trackID = "track_id"
        case kind
        case format
        case totalSampleCount = "total_sample_count"
        case parts
        case gaps
        case sourceLineage = "source_lineage"
        case conversionVersion = "conversion_version"
    }
}

struct RecordingSealPayload: Codable, Equatable, Sendable {
    let schemaVersion = 1
    let recordingID: String
    let startedAt: String
    let endedAt: String
    let coverageStatus: String
    let tracks: [RecordingTrackManifestPayload]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case recordingID = "recording_id"
        case startedAt = "started_at"
        case endedAt = "ended_at"
        case coverageStatus = "coverage_status"
        case tracks
    }
}

// The wire body for POST /recordings/{id}/transcripts. recordingID routes
// the URL only: TranscriptSubmitCommand carries no recording_id field (the
// path already names the recording), so it is deliberately left out of
// CodingKeys and never reaches the JSON body.
struct TranscriptSubmitPayload: Encodable, Equatable, Sendable {
    let recordingID: String
    let schemaVersion = 1
    let track: String
    let segments: [TranscriptSegmentPayload]
    let modelIdentity: TranscriptModelIdentityPayload
    let derivation: TranscriptDerivationPayload

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case track
        case segments
        case modelIdentity = "model_identity"
        case derivation
    }
}

extension TranscriptSubmitPayload {
    // Maps the local ASR result to the wire shape, normalizing whisper's word
    // timestamps on the way so the body satisfies the server's contract:
    // `TranscriptSegment.validate_words` requires every word contained within
    // its segment's span and chronological (never starting before the
    // previous word in the same segment ends). whisper.cpp's per-token
    // timestamps come from a separate heuristic than its segment timestamps
    // and are not guaranteed to satisfy either -- a token can land outside
    // its segment, or two tokens can overlap -- so without `normalizedWords`
    // below, a real recording could produce a body the server rejects with a
    // 422 (transcript-lineage final review, Important 3). Segment spans and
    // text pass through unchanged; only words -- whisper's
    // questionable-timestamp output -- are touched, and only their
    // timestamps, never their text or probability.
    static func make(recordingID: UUID, result: SpeechTranscriptionResult) -> TranscriptSubmitPayload {
        .init(
            recordingID: recordingID.uuidString.lowercased(),
            track: result.lineage.track.rawValue,
            segments: result.segments.map { segment in
                TranscriptSegmentPayload(
                    text: segment.text,
                    startMilliseconds: segment.startMilliseconds,
                    endMilliseconds: segment.endMilliseconds,
                    words: normalizedWords(
                        segment.words,
                        segmentStart: segment.startMilliseconds,
                        segmentEnd: segment.endMilliseconds
                    )
                )
            },
            modelIdentity: TranscriptModelIdentityPayload(
                runtimeVersion: result.identity.runtimeVersion,
                modelFilename: result.identity.modelFilename,
                modelSHA256: result.identity.modelSHA256,
                metalRequested: result.identity.metalRequested,
                usedBuiltInVAD: result.identity.usedBuiltInVAD,
                language: result.identity.language
            ),
            derivation: TranscriptDerivationPayload(
                derivationVersion: result.lineage.derivationVersion,
                sourceSampleRate: result.lineage.sourceSampleRate,
                sourceChannelCount: result.lineage.sourceChannelCount,
                sourceSampleCount: result.lineage.sourceSampleCount,
                outputSampleRate: result.lineage.outputSampleRate,
                outputSampleCount: result.lineage.outputSampleCount,
                zeroFilledGaps: result.lineage.zeroFilledGaps.map { gap in
                    TranscriptDerivationGapPayload(
                        sampleStart: gap.sampleStart,
                        sampleCount: gap.sampleCount,
                        reason: gap.reason.rawValue
                    )
                },
                sourcePCMSHA256: result.lineage.sourcePCMSHA256,
                derivedPCMSHA256: result.lineage.derivedPCMSHA256,
                quality: TranscriptAudioQualityPayload(
                    version: result.lineage.quality.version,
                    sampleRate: result.lineage.quality.sampleRate,
                    channelCount: result.lineage.quality.channelCount,
                    sourceSampleCount: result.lineage.quality.sourceSampleCount,
                    durationSeconds: result.lineage.quality.durationSeconds,
                    peakAbsolute: result.lineage.quality.peakAbsolute,
                    allSilence: result.lineage.quality.allSilence,
                    clippedRatio: result.lineage.quality.clippedRatio,
                    dcOffset: result.lineage.quality.dcOffset,
                    channelImbalanceDecibels: result.lineage.quality.channelImbalanceDecibels,
                    discontinuityCount: result.lineage.quality.discontinuityCount,
                    unavailableDimensions: result.lineage.quality.unavailableDimensions
                )
            )
        )
    }

    // Clamps each word into [segmentStart, segmentEnd] and forces
    // non-decreasing, non-overlapping spans in a single left-to-right pass,
    // so every word satisfies the server's containment and chronological
    // rules by construction: `start` is raised to `previousEnd` when a raw
    // timestamp would otherwise overlap the prior word, and `end` is raised
    // to match if clamping ever left it behind `start`. Drops tokens whose
    // text decoded empty -- whisper.cpp's own boundary artifact, and the
    // server's `BoundedText` requires at least one character.
    private static func normalizedWords(
        _ words: [SpeechTranscribedWord], segmentStart: Int64, segmentEnd: Int64
    ) -> [TranscriptWordPayload] {
        var payloads: [TranscriptWordPayload] = []
        payloads.reserveCapacity(words.count)
        var previousEnd = segmentStart
        for word in words where !word.text.isEmpty {
            let clampedStart = min(max(segmentStart, word.startMilliseconds), segmentEnd)
            let clampedEnd = max(min(segmentEnd, word.endMilliseconds), segmentStart)
            let start = max(clampedStart, previousEnd)
            let end = max(clampedEnd, start)
            payloads.append(
                TranscriptWordPayload(
                    text: word.text,
                    startMilliseconds: start,
                    endMilliseconds: end,
                    probability: word.probability
                )
            )
            previousEnd = end
        }
        return payloads
    }

    // Stable across retries: recordingID and track never change for a
    // given submission, so resubmitting after a failed or premature
    // attempt is a replay of the same command, not a new one, no matter
    // how many upload-worker passes it takes.
    var idempotencyKey: String { "recording.transcript.\(recordingID).\(track)" }
}

// Bridges a recording's just-computed local transcript from the
// coordinator (the only place transcription happens, and the only place
// that can rebuild this payload) to the upload pipeline's retry pass (a
// separate actor with no visibility into transcription state). An entry
// is removed once its recording's spool is released or discarded, so this
// never grows unbounded across a long-running session.
//
// Every entry is also written through to an encrypted file inside its own
// recording's spool directory, because the process can end between a
// transcript being computed and the server accepting it. Nothing
// recomputes a transcript on a later launch, so an in-memory-only entry
// would leave the next pass's retry branch with nothing to resubmit and
// strand that recording's spool on disk for the life of the machine. The
// file is sealed under the same per-recording key as the audio records
// beside it and lives inside the directory discard() deletes, so
// releasing or discarding a recording destroys its transcript text along
// with its audio. A nil spoolFactory keeps the cache purely in memory,
// which is only ever useful to a test that is not exercising durability.
actor RecordingTranscriptCache {
    private static let fileName = "transcript-payload.tfe"

    private let spoolFactory: EncryptedRecordingSpoolFactory?
    private var payloads: [UUID: TranscriptSubmitPayload] = [:]

    init(spoolFactory: EncryptedRecordingSpoolFactory? = nil) {
        self.spoolFactory = spoolFactory
    }

    // A durable write that fails is never worth failing the caller over:
    // the in-memory entry still serves this process, and a recording whose
    // directory has already gone (released, discarded) has nothing left to
    // submit anyway.
    func store(_ payload: TranscriptSubmitPayload, recordingID: UUID) async {
        payloads[recordingID] = payload
        try? await persist(payload, recordingID: recordingID)
    }

    func payload(for recordingID: UUID) async -> TranscriptSubmitPayload? {
        if let cached = payloads[recordingID] { return cached }
        guard let recovered = try? await recover(recordingID: recordingID) else { return nil }
        payloads[recordingID] = recovered
        return recovered
    }

    // The one path that drops a payload while its spool may still be
    // present, so the durable copy has to go too rather than be read back
    // on the next launch and resubmitted after the caller decided to stop.
    func remove(recordingID: UUID) {
        payloads.removeValue(forKey: recordingID)
        guard let url = fileURL(recordingID: recordingID) else { return }
        try? FileManager.default.removeItem(at: url)
    }

    private func persist(_ payload: TranscriptSubmitPayload, recordingID: UUID) async throws {
        guard let spoolFactory, let url = fileURL(recordingID: recordingID) else { return }
        let key = try await spoolFactory.keyStore.load(recordingID: recordingID)
        let plaintext = try RecordingCanonicalJSON.encode(StoredTranscriptPayload(payload))
        let sealed = try AES.GCM.seal(
            plaintext,
            using: key,
            authenticating: Self.authenticatedData(recordingID: recordingID)
        )
        guard let combined = sealed.combined else { throw RecordingUploadError.invalidResponse }
        try combined.write(to: url, options: [.atomic])
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o600],
            ofItemAtPath: url.path
        )
    }

    private func recover(recordingID: UUID) async throws -> TranscriptSubmitPayload {
        guard let spoolFactory, let url = fileURL(recordingID: recordingID) else {
            throw RecordingUploadError.invalidResponse
        }
        let key = try await spoolFactory.keyStore.load(recordingID: recordingID)
        let sealed = try AES.GCM.SealedBox(combined: try Data(contentsOf: url))
        let plaintext = try AES.GCM.open(
            sealed,
            using: key,
            authenticating: Self.authenticatedData(recordingID: recordingID)
        )
        let stored = try JSONDecoder().decode(StoredTranscriptPayload.self, from: plaintext)
        guard stored.schemaVersion == 1 else { throw RecordingUploadError.invalidResponse }
        return stored.payload
    }

    private func fileURL(recordingID: UUID) -> URL? {
        spoolFactory?.rootURL
            .appendingPathComponent(recordingID.uuidString, isDirectory: true)
            .appendingPathComponent(Self.fileName)
    }

    // Domain-separated and bound to the recording, so one recording's
    // stored transcript can never open as another's even though every
    // recording's key comes from the same store.
    private static func authenticatedData(recordingID: UUID) -> Data {
        Data(
            "tamforge.recording.transcript-payload.v1|\(recordingID.uuidString.lowercased())".utf8
        )
    }
}

// The durable form of a submit payload. TranscriptSubmitPayload is
// encode-only, and its wire body deliberately omits recording_id because
// the URL path already names the recording, so the stored form carries the
// id explicitly and rebuilds the payload on the way back.
private struct StoredTranscriptPayload: Codable {
    let schemaVersion: Int
    let recordingID: String
    let track: String
    let segments: [TranscriptSegmentPayload]
    let modelIdentity: TranscriptModelIdentityPayload
    let derivation: TranscriptDerivationPayload

    init(_ payload: TranscriptSubmitPayload) {
        schemaVersion = payload.schemaVersion
        recordingID = payload.recordingID
        track = payload.track
        segments = payload.segments
        modelIdentity = payload.modelIdentity
        derivation = payload.derivation
    }

    var payload: TranscriptSubmitPayload {
        .init(
            recordingID: recordingID,
            track: track,
            segments: segments,
            modelIdentity: modelIdentity,
            derivation: derivation
        )
    }

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case recordingID = "recording_id"
        case track
        case segments
        case modelIdentity = "model_identity"
        case derivation
    }
}

struct TranscriptSegmentPayload: Codable, Equatable, Sendable {
    let text: String
    let startMilliseconds: Int64
    let endMilliseconds: Int64
    let words: [TranscriptWordPayload]

    enum CodingKeys: String, CodingKey {
        case text
        case startMilliseconds = "start_ms"
        case endMilliseconds = "end_ms"
        case words
    }
}

struct TranscriptWordPayload: Codable, Equatable, Sendable {
    let text: String
    let startMilliseconds: Int64
    let endMilliseconds: Int64
    let probability: Double

    enum CodingKeys: String, CodingKey {
        case text
        case startMilliseconds = "start_ms"
        case endMilliseconds = "end_ms"
        case probability
    }
}

struct TranscriptModelIdentityPayload: Codable, Equatable, Sendable {
    let runtimeVersion: String
    let modelFilename: String
    let modelSHA256: String
    let metalRequested: Bool
    let usedBuiltInVAD: Bool
    let language: String

    enum CodingKeys: String, CodingKey {
        case runtimeVersion = "runtime_version"
        case modelFilename = "model_filename"
        case modelSHA256 = "model_sha256"
        case metalRequested = "metal_requested"
        case usedBuiltInVAD = "used_builtin_vad"
        case language
    }
}

struct TranscriptDerivationPayload: Codable, Equatable, Sendable {
    let derivationVersion: String
    let sourceSampleRate: Int
    let sourceChannelCount: Int
    let sourceSampleCount: Int64
    let outputSampleRate: Int
    let outputSampleCount: Int64
    let zeroFilledGaps: [TranscriptDerivationGapPayload]
    let sourcePCMSHA256: String
    let derivedPCMSHA256: String
    let quality: TranscriptAudioQualityPayload

    enum CodingKeys: String, CodingKey {
        case derivationVersion = "derivation_version"
        case sourceSampleRate = "source_sample_rate"
        case sourceChannelCount = "source_channel_count"
        case sourceSampleCount = "source_sample_count"
        case outputSampleRate = "output_sample_rate"
        case outputSampleCount = "output_sample_count"
        case zeroFilledGaps = "zero_filled_gaps"
        case sourcePCMSHA256 = "source_pcm_sha256"
        case derivedPCMSHA256 = "derived_pcm_sha256"
        case quality
    }
}

struct TranscriptDerivationGapPayload: Codable, Equatable, Sendable {
    let sampleStart: Int64
    let sampleCount: Int
    let reason: String

    enum CodingKeys: String, CodingKey {
        case sampleStart = "sample_start"
        case sampleCount = "sample_count"
        case reason
    }
}

struct TranscriptAudioQualityPayload: Codable, Equatable, Sendable {
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

    enum CodingKeys: String, CodingKey {
        case version
        case sampleRate = "sample_rate"
        case channelCount = "channel_count"
        case sourceSampleCount = "source_sample_count"
        case durationSeconds = "duration_seconds"
        case peakAbsolute = "peak_absolute"
        case allSilence = "all_silence"
        case clippedRatio = "clipped_ratio"
        case dcOffset = "dc_offset"
        case channelImbalanceDecibels = "channel_imbalance_decibels"
        case discontinuityCount = "discontinuity_count"
        case unavailableDimensions = "unavailable_dimensions"
    }
}

struct RecordingPartAADPayload: Codable, Equatable, Sendable {
    let schemaVersion = 1
    let recordingID: String
    let trackID: String
    let trackKind: String
    let format: RecordingCanonicalFormatPayload
    let sequence: Int
    let sampleStart: Int64
    let sampleCount: Int
    let byteLength: Int
    let ciphertextByteLength: Int
    let plaintextSHA256: String
    let nonceBase64URL: String
    let encryptionVersion = "aes-256-gcm-hkdf-sha256-v1"

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case recordingID = "recording_id"
        case trackID = "track_id"
        case trackKind = "track_kind"
        case format
        case sequence
        case sampleStart = "sample_start"
        case sampleCount = "sample_count"
        case byteLength = "byte_length"
        case ciphertextByteLength = "ciphertext_byte_length"
        case plaintextSHA256 = "plaintext_sha256"
        case nonceBase64URL = "nonce_base64url"
        case encryptionVersion = "encryption_version"
    }
}

struct RecordingPartContractPayload: Codable, Equatable, Sendable {
    let schemaVersion = 1
    let recordingID: String
    let trackID: String
    let trackKind: String
    let format: RecordingCanonicalFormatPayload
    let sequence: Int
    let sampleStart: Int64
    let sampleCount: Int
    let byteLength: Int
    let ciphertextByteLength: Int
    let plaintextSHA256: String
    let ciphertextSHA256: String
    let nonceBase64URL: String
    let encryptionVersion = "aes-256-gcm-hkdf-sha256-v1"

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case recordingID = "recording_id"
        case trackID = "track_id"
        case trackKind = "track_kind"
        case format
        case sequence
        case sampleStart = "sample_start"
        case sampleCount = "sample_count"
        case byteLength = "byte_length"
        case ciphertextByteLength = "ciphertext_byte_length"
        case plaintextSHA256 = "plaintext_sha256"
        case ciphertextSHA256 = "ciphertext_sha256"
        case nonceBase64URL = "nonce_base64url"
        case encryptionVersion = "encryption_version"
    }
}

struct RecordingPreparedPart: Sendable {
    let recordingID: UUID
    let trackID: UUID
    let track: RecordingTrackKind
    let sequence: Int
    let sampleStart: Int64
    let sampleCount: Int
    let plaintextLength: Int
    let ciphertextLength: Int
    let plaintextSHA256: String
    let ciphertextSHA256: String
    let nonceBase64URL: String
    let partKeyBase64URL: String
    let fileURL: URL
    let fileIdentity: RecordingUploadFileIdentity

    var identity: String {
        "\(track.rawValue):\(sequence):\(plaintextSHA256)"
    }

    var idempotencyKey: String {
        "recording.part.\(trackID.uuidString.lowercased()).\(sequence).\(plaintextSHA256.prefix(16))"
    }

    var headers: [String: String] {
        [
            "Idempotency-Key": idempotencyKey,
            "X-TAM-Recording-Schema": "1",
            "X-TAM-Track-Kind": track.rawValue,
            "X-TAM-Sample-Encoding": "pcm_s16le",
            "X-TAM-Sample-Rate": "48000",
            "X-TAM-Channel-Count": String(track.channelCount),
            "X-TAM-Part-Sequence": String(sequence),
            "X-TAM-Sample-Start": String(sampleStart),
            "X-TAM-Sample-Count": String(sampleCount),
            "X-TAM-Plaintext-Length": String(plaintextLength),
            "X-TAM-Ciphertext-Length": String(ciphertextLength),
            "X-TAM-Plaintext-SHA256": plaintextSHA256,
            "X-TAM-Ciphertext-SHA256": ciphertextSHA256,
            "X-TAM-Part-Nonce": nonceBase64URL,
            "X-TAM-Part-Key": partKeyBase64URL,
            "X-TAM-Part-Encryption": "aes-256-gcm-hkdf-sha256-v1",
        ]
    }

    func verifyFileIdentity() throws {
        guard try RecordingUploadFileIdentity.read(from: fileURL) == fileIdentity else {
            throw RecordingUploadError.fileChanged
        }
    }
}

struct RecordingUploadPartBuilder: Sendable {
    func prepare(
        record: RecoveredSpoolRecord,
        uploadSequence: Int,
        rootKey: SymmetricKey,
        directoryURL: URL
    ) throws -> RecordingPreparedPart {
        let recordingID = record.recordingID
        let track = record.chunk.track
        let trackID = RecordingTrackIdentity.id(recordingID: recordingID, track: track)
        let plaintextHash = record.payload.sha256Hex
        let info = Data(
            "\(recordingID.uuidString.lowercased())|\(track.rawValue)|\(uploadSequence)|\(plaintextHash)"
                .utf8
        )
        let material = HKDF<SHA256>.deriveKey(
            inputKeyMaterial: rootKey,
            salt: Data("tamforge.recording.upload-part.v1".utf8),
            info: info,
            outputByteCount: 44
        ).data
        let partKey = SymmetricKey(data: material.prefix(32))
        let partKeyValue = partKey.data.base64URL
        guard RecordingPartKeyEncoding.isCanonical(partKeyValue) else {
            throw RecordingUploadError.invalidResponse
        }
        let nonceData = Data(material.suffix(12))
        let nonce = try AES.GCM.Nonce(data: nonceData)
        let nonceValue = nonceData.base64URL
        let aadPayload = RecordingPartAADPayload(
            recordingID: recordingID.uuidString.lowercased(),
            trackID: trackID.uuidString.lowercased(),
            trackKind: track.rawValue,
            format: .init(channelCount: track.channelCount),
            sequence: uploadSequence,
            sampleStart: record.chunk.sampleStart,
            sampleCount: record.chunk.sampleCount,
            byteLength: record.payload.count,
            ciphertextByteLength: record.payload.count + 16,
            plaintextSHA256: plaintextHash,
            nonceBase64URL: nonceValue
        )
        var aad = Data("tamforge.recording.part-aad.v1\0".utf8)
        aad.append(try RecordingCanonicalJSON.encode(aadPayload))
        let box = try AES.GCM.seal(
            record.payload,
            using: partKey,
            nonce: nonce,
            authenticating: aad
        )
        var ciphertext = box.ciphertext
        ciphertext.append(box.tag)
        let uploadDirectory = directoryURL.appendingPathComponent(".upload", isDirectory: true)
        try FileManager.default.createDirectory(
            at: uploadDirectory,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        let fileURL = uploadDirectory.appendingPathComponent(
            "\(track.rawValue)-\(uploadSequence)-\(plaintextHash).part"
        )
        try ciphertext.write(to: fileURL, options: [.atomic])
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o400],
            ofItemAtPath: fileURL.path
        )
        return .init(
            recordingID: recordingID,
            trackID: trackID,
            track: track,
            sequence: uploadSequence,
            sampleStart: record.chunk.sampleStart,
            sampleCount: record.chunk.sampleCount,
            plaintextLength: record.payload.count,
            ciphertextLength: ciphertext.count,
            plaintextSHA256: plaintextHash,
            ciphertextSHA256: ciphertext.sha256Hex,
            nonceBase64URL: nonceValue,
            partKeyBase64URL: partKeyValue,
            fileURL: fileURL,
            fileIdentity: try .read(from: fileURL)
        )
    }
}

struct RecordingUploadPartGrouper {
    static let maximumSampleCount = RecordingPCMFormat.canonicalSampleRate * 60

    private let maximumSampleCount: Int
    private var pending: RecoveredSpoolRecord?

    init(maximumSampleCount: Int = Self.maximumSampleCount) {
        self.maximumSampleCount = maximumSampleCount
    }

    mutating func append(_ record: RecoveredSpoolRecord) -> RecoveredSpoolRecord? {
        guard let current = pending else {
            pending = record
            return nil
        }
        let combinedSamples = current.chunk.sampleCount + record.chunk.sampleCount
        guard current.recordingID == record.recordingID,
            current.chunk.track == record.chunk.track,
            current.chunk.format == record.chunk.format,
            record.chunk.sampleStart
                == current.chunk.sampleStart + Int64(current.chunk.sampleCount),
            combinedSamples <= maximumSampleCount
        else {
            pending = record
            return current
        }

        var payload = current.payload
        payload.append(record.payload)
        pending = .init(
            recordingID: current.recordingID,
            sequence: current.sequence,
            payload: payload,
            chunk: .init(
                track: current.chunk.track,
                presentationNanoseconds: current.chunk.presentationNanoseconds,
                sampleStart: current.chunk.sampleStart,
                sampleCount: combinedSamples,
                format: current.chunk.format,
                source: current.chunk.source,
                payload: payload
            )
        )
        return nil
    }

    mutating func finish() -> RecoveredSpoolRecord? {
        defer { pending = nil }
        return pending
    }
}

struct RecordingUploadFileIdentity: Codable, Equatable, Sendable {
    let device: UInt64
    let inode: UInt64
    let byteCount: Int64
    let ciphertextSHA256: String

    static func read(from url: URL) throws -> Self {
        let descriptor = Darwin.open(url.path, O_RDONLY | O_NOFOLLOW)
        guard descriptor >= 0 else { throw RecordingUploadError.fileChanged }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? handle.close() }
        var metadata = Darwin.stat()
        guard Darwin.fstat(descriptor, &metadata) == 0,
            metadata.st_mode & S_IFMT == S_IFREG,
            metadata.st_mode & (S_IWUSR | S_IWGRP | S_IWOTH) == 0
        else { throw RecordingUploadError.fileChanged }
        return .init(
            device: UInt64(metadata.st_dev),
            inode: UInt64(metadata.st_ino),
            byteCount: metadata.st_size,
            ciphertextSHA256: try sha256(handle: handle)
        )
    }

    private static func sha256(handle: FileHandle) throws -> String {
        var hasher = SHA256()
        while true {
            let chunk = try handle.readOwnedBytes(upTo: 1_048_576)
            guard !chunk.isEmpty else { break }
            hasher.update(data: chunk)
        }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }
}

struct RecordingUploadJournalState: Codable, Equatable, Sendable {
    var schemaVersion = 1
    var createAccepted = false
    var completedParts: [String] = []
    var inFlightPart: String?
    var inFlightFileIdentity: RecordingUploadFileIdentity?
    var retryCount = 0
    var sealAccepted = false
}

actor RecordingUploadJournal {
    private let fileURL: URL
    private var state: RecordingUploadJournalState

    init(directoryURL: URL) throws {
        fileURL = directoryURL.appendingPathComponent("upload-journal.json")
        if FileManager.default.fileExists(atPath: fileURL.path) {
            let data = try Data(contentsOf: fileURL)
            state = try JSONDecoder().decode(RecordingUploadJournalState.self, from: data)
            guard state.schemaVersion == 1 else { throw RecordingUploadError.invalidResponse }
            state.inFlightPart = nil
            state.inFlightFileIdentity = nil
        } else {
            state = .init()
        }
    }

    func snapshot() -> RecordingUploadJournalState { state }

    func markCreateAccepted() throws {
        state.createAccepted = true
        try persist()
    }

    func begin(part: RecordingPreparedPart) throws {
        state.inFlightPart = part.identity
        state.inFlightFileIdentity = part.fileIdentity
        try persist()
    }

    func complete(part: RecordingPreparedPart) throws {
        if !state.completedParts.contains(part.identity) {
            state.completedParts.append(part.identity)
            state.completedParts.sort()
        }
        state.inFlightPart = nil
        state.inFlightFileIdentity = nil
        try persist()
    }

    func markFailure() throws {
        state.retryCount += 1
        state.inFlightPart = nil
        state.inFlightFileIdentity = nil
        try persist()
    }

    func markSealAccepted() throws {
        state.sealAccepted = true
        try persist()
    }

    private func persist() throws {
        let data = try RecordingCanonicalJSON.encode(state)
        try data.write(to: fileURL, options: [.atomic])
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o600],
            ofItemAtPath: fileURL.path
        )
    }
}

enum RecordingTrackIdentity {
    static func id(recordingID: UUID, track: RecordingTrackKind) -> UUID {
        let digest = Array(
            SHA256.hash(
                data: Data(
                    "tamforge.recording.track.v1|\(recordingID.uuidString.lowercased())|\(track.rawValue)"
                        .utf8)
            ))
        var bytes = Array(digest.prefix(16))
        bytes[6] = (bytes[6] & 0x0f) | 0x50
        bytes[8] = (bytes[8] & 0x3f) | 0x80
        return UUID(
            uuid: (
                bytes[0], bytes[1], bytes[2], bytes[3],
                bytes[4], bytes[5], bytes[6], bytes[7],
                bytes[8], bytes[9], bytes[10], bytes[11],
                bytes[12], bytes[13], bytes[14], bytes[15]
            ))
    }
}

enum RecordingCanonicalJSON {
    static func encode<Value: Encodable>(_ value: Value) throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return try asciiEscaped(encoder.encode(value))
    }

    static func sha256<Value: Encodable>(domain: String, value: Value) throws -> String {
        var data = Data(domain.utf8)
        data.append(0)
        data.append(try encode(value))
        return data.sha256Hex
    }

    // Match Python json.dumps(ensure_ascii=True): every scalar above 0x7f in a
    // JSON string becomes a lowercase \uXXXX escape (surrogate pairs beyond
    // the BMP), so both sides hash identical canonical bytes.
    private static func asciiEscaped(_ encoded: Data) throws -> Data {
        guard encoded.contains(where: { $0 > 0x7f }) else { return encoded }
        guard let text = String(data: encoded, encoding: .utf8) else {
            throw RecordingUploadError.invalidResponse
        }
        var output = String()
        output.reserveCapacity(text.unicodeScalars.count)
        for scalar in text.unicodeScalars {
            if scalar.value <= 0x7f {
                output.unicodeScalars.append(scalar)
            } else if scalar.value > 0xffff {
                let value = scalar.value - 0x10000
                output += String(
                    format: "\\u%04x\\u%04x",
                    0xd800 + (value >> 10),
                    0xdc00 + (value & 0x3ff)
                )
            } else {
                output += String(format: "\\u%04x", scalar.value)
            }
        }
        return Data(output.utf8)
    }
}

extension RecordingTrackKind {
    fileprivate var channelCount: Int { self == .microphone ? 1 : 2 }
}

extension Data {
    fileprivate var sha256Hex: String {
        SHA256.hash(data: self).map { String(format: "%02x", $0) }.joined()
    }

    fileprivate var base64URL: String {
        base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}

extension SymmetricKey {
    fileprivate var data: Data { withUnsafeBytes { Data($0) } }
}
