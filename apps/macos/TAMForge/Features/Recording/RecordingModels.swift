import CryptoKit
import Foundation

enum RecordingTrackKind: String, Codable, CaseIterable, Sendable {
    case microphone
    case systemAudio = "system_audio"
}

enum RecordingModelError: Error, Equatable {
    case invalidCanonicalFormat
    case invalidSampleRange
    case invalidPayloadLength
}

struct RecordingPCMFormat: Codable, Equatable, Sendable {
    static let canonicalSampleRate = 48_000
    static let bytesPerSample = 2

    let sampleEncoding: String
    let sampleRate: Int
    let channelCount: Int
    let interleaved: Bool

    init(
        track: RecordingTrackKind,
        channelCount: Int,
        sampleRate: Int = canonicalSampleRate
    ) throws {
        let expectedChannels = track == .microphone ? 1 : 2
        guard sampleRate == Self.canonicalSampleRate, channelCount == expectedChannels else {
            throw RecordingModelError.invalidCanonicalFormat
        }
        sampleEncoding = "pcm_s16le"
        self.sampleRate = sampleRate
        self.channelCount = channelCount
        interleaved = true
    }

    init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        let encoding = try values.decode(String.self, forKey: .sampleEncoding)
        let sampleRate = try values.decode(Int.self, forKey: .sampleRate)
        let channelCount = try values.decode(Int.self, forKey: .channelCount)
        let interleaved = try values.decode(Bool.self, forKey: .interleaved)
        guard encoding == "pcm_s16le",
              sampleRate == Self.canonicalSampleRate,
              [1, 2].contains(channelCount),
              interleaved
        else { throw RecordingModelError.invalidCanonicalFormat }
        sampleEncoding = encoding
        self.sampleRate = sampleRate
        self.channelCount = channelCount
        self.interleaved = interleaved
    }

    private enum CodingKeys: String, CodingKey {
        case sampleEncoding
        case sampleRate
        case channelCount
        case interleaved
    }
}

struct RecordingSourceLineage: Codable, Equatable, Sendable {
    let sampleRate: Double
    let channelCount: Int
    let deviceID: String
    let presentationNanoseconds: Int64
}

struct RecordingPCMChunk: Equatable, Sendable {
    let track: RecordingTrackKind
    let presentationNanoseconds: Int64
    var sampleStart: Int64
    let sampleCount: Int
    let format: RecordingPCMFormat
    let source: RecordingSourceLineage
    let payload: Data

    init(
        track: RecordingTrackKind,
        presentationNanoseconds: Int64,
        sampleStart: Int64,
        sampleCount: Int,
        format: RecordingPCMFormat,
        source: RecordingSourceLineage,
        payload: Data
    ) {
        self.track = track
        self.presentationNanoseconds = presentationNanoseconds
        self.sampleStart = sampleStart
        self.sampleCount = sampleCount
        self.format = format
        self.source = source
        self.payload = payload
    }

    func validated() throws -> Self {
        guard sampleStart >= 0, sampleCount > 0 else {
            throw RecordingModelError.invalidSampleRange
        }
        guard payload.count == sampleCount * format.channelCount * RecordingPCMFormat.bytesPerSample else {
            throw RecordingModelError.invalidPayloadLength
        }
        return self
    }
}

enum RecordingGapReason: String, Codable, Sendable {
    case callbackOverflow = "callback_overflow"
    case formatChange = "format_change"
    case routeChange = "route_change"
    case sourceDiscontinuity = "source_discontinuity"
    case missingAudio = "missing_audio"
    case corruptSpoolRecord = "corrupt_spool_record"
}

struct RecordingGap: Codable, Equatable, Sendable {
    let track: RecordingTrackKind
    let sampleStart: Int64
    let sampleCount: Int
    let reason: RecordingGapReason
}

enum RecordingCaptureEvent: Sendable {
    case chunk(RecordingPCMChunk)
    case gap(RecordingGap)
    case level(track: RecordingTrackKind, normalized: Double)
    case route(String)
    case failure(RecordingCaptureFailure)
}

enum RecordingCaptureFailure: Error, Equatable, Sendable {
    case permissionLost
    case sourceUnavailable
    case formatUnsupported
    case callbackOverflow
    case conversionFailed
    case streamStopped
    case silentInput
}

struct RecordingMicrophone: Identifiable, Equatable, Sendable {
    let id: String
    let name: String
}

struct RecordingPreflightSnapshot: Equatable, Sendable {
    let selectedMicrophone: RecordingMicrophone
    let availableMicrophones: [RecordingMicrophone]
    let displayCount: Int
    let availableDiskBytes: Int64
    let pendingSpoolBytes: Int64
    let routeDescription: String
    let coverageIsProvisional: Bool

#if DEBUG
    static let fixture = Self(
        selectedMicrophone: .init(id: "test-microphone", name: "Test Microphone"),
        availableMicrophones: [.init(id: "test-microphone", name: "Test Microphone")],
        displayCount: 1,
        availableDiskBytes: 20 * RecordingDiskPolicy.gibibyte,
        pendingSpoolBytes: 0,
        routeDescription: "Test Microphone",
        coverageIsProvisional: true
    )
#endif
}

enum RecordingPreflightFailure: Error, Equatable, Sendable {
    case microphonePermissionDenied
    case microphonePermissionRestricted
    case microphonePermissionNotDetermined
    case microphoneMissing
    case microphoneInUse
    case screenRecordingPermissionDenied
    case noShareableDisplay
    case insufficientDiskReserve
    case recordingSizeLimitReached
    case globalSpoolLimitReached
    case routeUnavailable
}

enum RecordingPreflightResult: Equatable, Sendable {
    case ready(RecordingPreflightSnapshot)
    case blocked(RecordingPreflightFailure)
}

protocol RecordingPreflighting: Sendable {
    func run() async -> RecordingPreflightResult
}

protocol RecordingCaptureSource: Sendable {
    func start(
        microphoneID: String?,
        receive: @escaping @Sendable (RecordingCaptureEvent) -> Void
    ) async throws
    func stop() async throws
}

protocol RecordingSpoolWriting: Sendable {
    func append(_ chunk: RecordingPCMChunk) async throws
    func record(gap: RecordingGap) async
    func seal(gaps: [RecordingGap]) async throws
}

protocol RecordingSpoolCreating: Sendable {
    func create(recordingID: UUID) async throws -> any RecordingSpoolWriting
    func pendingRecordingIDs() async -> [UUID]
    func discard(recordingID: UUID) async throws
}

protocol RecordingKeyStoring: Sendable {
    func create(recordingID: UUID) async throws -> SymmetricKey
    func load(recordingID: UUID) async throws -> SymmetricKey
    func delete(recordingID: UUID) async throws
}

struct RecordingReleaseGates: Codable, Equatable, Sendable {
    var audioCreatedOnServer: Bool
    var transcriptLineageAccepted: Bool

    var mayDeleteLocalSpool: Bool {
        audioCreatedOnServer && transcriptLineageAccepted
    }
}

enum RecordingDiskPolicy {
    static let gibibyte: Int64 = 1_073_741_824
    static let maximumDurationSeconds = 120 * 60
    static let maximumRecordingBytes = Int64(2.5 * Double(gibibyte))
    static let maximumGlobalBytes = 5 * gibibyte
    static let requiredFreeReserveBytes = 8 * gibibyte

    static func failure(
        availableBytes: Int64,
        pendingGlobalBytes: Int64,
        proposedRecordingBytes: Int64
    ) -> RecordingPreflightFailure? {
        guard proposedRecordingBytes <= maximumRecordingBytes else {
            return .recordingSizeLimitReached
        }
        guard pendingGlobalBytes + proposedRecordingBytes <= maximumGlobalBytes else {
            return .globalSpoolLimitReached
        }
        guard availableBytes - proposedRecordingBytes >= requiredFreeReserveBytes else {
            return .insufficientDiskReserve
        }
        return nil
    }
}

enum RecordingPhase: Equatable, Sendable {
    case idle
    case preflighting
    case blocked(RecordingPreflightFailure)
    case recording(UUID)
    case stopping(UUID)
    case sealed(UUID)
    case needsAttention(UUID?, String)

    var isActive: Bool {
        switch self {
        case .preflighting, .recording, .stopping:
            true
        case .idle, .blocked, .sealed, .needsAttention:
            false
        }
    }
}

struct RecordingTrackHealth: Equatable, Sendable {
    var normalizedLevel = 0.0
    var lastSampleEnd: Int64 = 0
    var gapCount = 0
    var warning: RecordingCaptureFailure?
    var consecutiveSilentBuffers = 0
}

struct RecordingHealth: Equatable, Sendable {
    var microphone = RecordingTrackHealth()
    var systemAudio = RecordingTrackHealth()
    var routeDescription = ""

    subscript(track: RecordingTrackKind) -> RecordingTrackHealth {
        get { track == .microphone ? microphone : systemAudio }
        set {
            if track == .microphone { microphone = newValue }
            else { systemAudio = newValue }
        }
    }
}
