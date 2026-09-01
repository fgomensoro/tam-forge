import CryptoKit
import Darwin
import Foundation

enum RecordingUploadError: Error, Equatable {
    case unsealedSpool
    case missingTimeline
    case invalidCoverage
    case fileChanged
    case unauthorized
    case offline
    case conflict
    case invalidResponse
    case server(statusCode: Int)
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
        case pcmSHA256 = "pcm_sha256"
        case timelineSHA256 = "timeline_sha256"
        case conversionVersion = "conversion_version"
    }

    static func make(
        recordingID: UUID,
        track: RecordingTrackKind,
        parts: [RecordingPartDescriptorPayload],
        gaps: [RecordingGapPayload],
        pcmSHA256: String
    ) throws -> Self {
        let orderedParts = parts.sorted {
            ($0.sampleStart, $0.sequence) < ($1.sampleStart, $1.sequence)
        }
        let orderedGaps = gaps.sorted {
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
        let trackID = RecordingTrackIdentity.id(recordingID: recordingID, track: track)
        let timeline = RecordingTimelineManifestPayload(
            trackID: trackID.uuidString.lowercased(),
            kind: track.rawValue,
            format: .init(channelCount: track.channelCount),
            totalSampleCount: cursor,
            parts: orderedParts,
            gaps: orderedGaps,
            conversionVersion: "tamforge-pcm16-v1"
        )
        let timelineHash = try RecordingCanonicalJSON.sha256(
            domain: "tamforge.recording.timeline.v1",
            value: timeline
        )
        return .init(
            trackID: trackID.uuidString.lowercased(),
            kind: track.rawValue,
            format: .init(channelCount: track.channelCount),
            totalSampleCount: cursor,
            parts: orderedParts,
            gaps: orderedGaps,
            pcmSHA256: pcmSHA256,
            timelineSHA256: timelineHash
        )
    }
}

private struct RecordingTimelineManifestPayload: Codable {
    let trackID: String
    let kind: String
    let format: RecordingCanonicalFormatPayload
    let totalSampleCount: Int64
    let parts: [RecordingPartDescriptorPayload]
    let gaps: [RecordingGapPayload]
    let conversionVersion: String

    enum CodingKeys: String, CodingKey {
        case trackID = "track_id"
        case kind
        case format
        case totalSampleCount = "total_sample_count"
        case parts
        case gaps
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
            [.posixPermissions: 0o600],
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
            partKeyBase64URL: partKey.data.base64URL,
            fileURL: fileURL,
            fileIdentity: try .read(from: fileURL)
        )
    }
}

struct RecordingUploadFileIdentity: Codable, Equatable, Sendable {
    let device: UInt64
    let inode: UInt64
    let byteCount: Int64

    static func read(from url: URL) throws -> Self {
        var metadata = Darwin.stat()
        guard Darwin.lstat(url.path, &metadata) == 0,
            metadata.st_mode & S_IFMT == S_IFREG
        else { throw RecordingUploadError.fileChanged }
        return .init(
            device: UInt64(metadata.st_dev),
            inode: UInt64(metadata.st_ino),
            byteCount: metadata.st_size
        )
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
        return try encoder.encode(value)
    }

    static func sha256<Value: Encodable>(domain: String, value: Value) throws -> String {
        var data = Data(domain.utf8)
        data.append(0)
        data.append(try encode(value))
        return data.sha256Hex
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
