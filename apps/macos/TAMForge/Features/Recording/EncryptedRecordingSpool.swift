import CryptoKit
import Darwin
import Foundation
import Security

enum RecordingSpoolError: Error, Equatable {
    case missingKey
    case keyStore(OSStatus)
    case invalidRecord
    case unsupportedVersion
    case authenticationFailed
    case payloadHashMismatch
    case recordingLimitReached
    case reservationFailed
    case sealed
}

actor KeychainRecordingKeyStore: RecordingKeyStoring {
    private let service: String

    init(service: String = "com.fgomensoro.tamforge.recording-spool") {
        self.service = service
    }

    func create(recordingID: UUID) async throws -> SymmetricKey {
        let key = SymmetricKey(size: .bits256)
        let data = key.withUnsafeBytes { Data($0) }
        let query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: recordingID.uuidString,
            kSecAttrAccessible: kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
            kSecUseDataProtectionKeychain: true,
            kSecValueData: data,
        ]
        let status = SecItemAdd(query as CFDictionary, nil)
        guard status == errSecSuccess else { throw RecordingSpoolError.keyStore(status) }
        return key
    }

    func load(recordingID: UUID) async throws -> SymmetricKey {
        let query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: recordingID.uuidString,
            kSecUseDataProtectionKeychain: true,
            kSecReturnData: true,
            kSecMatchLimit: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status != errSecItemNotFound else { throw RecordingSpoolError.missingKey }
        guard status == errSecSuccess, let data = item as? Data, data.count == 32 else {
            throw RecordingSpoolError.keyStore(status)
        }
        return SymmetricKey(data: data)
    }

    func delete(recordingID: UUID) async throws {
        let query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: recordingID.uuidString,
            kSecUseDataProtectionKeychain: true,
        ]
        let status = SecItemDelete(query as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw RecordingSpoolError.keyStore(status)
        }
    }
}

struct EncryptedRecordingSpoolFactory: RecordingSpoolCreating {
    let rootURL: URL
    let keyStore: any RecordingKeyStoring
    let reservationBytes: Int64

    init(
        rootURL: URL = EncryptedRecordingSpoolFactory.defaultRootURL(),
        keyStore: any RecordingKeyStoring = KeychainRecordingKeyStore(),
        reservationBytes: Int64 = RecordingDiskPolicy.maximumRecordingBytes
    ) {
        self.rootURL = rootURL
        self.keyStore = keyStore
        self.reservationBytes = reservationBytes
    }

    func create(recordingID: UUID) async throws -> any RecordingSpoolWriting {
        try await EncryptedRecordingSpool.create(
            recordingID: recordingID,
            rootURL: rootURL,
            keyStore: keyStore,
            reservationBytes: reservationBytes
        )
    }

    func pendingRecordingIDs() async -> [UUID] {
        guard let urls = try? FileManager.default.contentsOfDirectory(
            at: rootURL,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: [.skipsHiddenFiles]
        ) else { return [] }
        return urls.compactMap { url in
            guard (try? url.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true,
                  let identifier = UUID(uuidString: url.lastPathComponent)
            else { return nil }
            let contents = (try? FileManager.default.contentsOfDirectory(
                at: url, includingPropertiesForKeys: nil
            )) ?? []
            return contents.contains { ["microphone.tfr", "system-audio.tfr", "state.json"].contains($0.lastPathComponent) }
                ? identifier : nil
        }.sorted { $0.uuidString < $1.uuidString }
    }

    func discard(recordingID: UUID) async throws {
        try await keyStore.delete(recordingID: recordingID)
        let directory = rootURL.appendingPathComponent(recordingID.uuidString, isDirectory: true)
        if FileManager.default.fileExists(atPath: directory.path) {
            try FileManager.default.removeItem(at: directory)
        }
    }

    static func defaultRootURL() -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("TAM Forge/RecordingSpool", isDirectory: true)
    }
}

struct RecoveredSpoolRecord: Equatable, Sendable {
    let recordingID: UUID
    let sequence: Int
    let payload: Data
    let chunk: RecordingPCMChunk
}

struct RecordingSpoolRecovery: Sendable {
    let records: [RecoveredSpoolRecord]
    let gaps: [RecordingGap]
    let corruptRanges: [RecordingGap]
    let ignoredIncompleteTail: Bool
    let sealed: Bool
    let releaseGates: RecordingReleaseGates
}

actor EncryptedRecordingSpool: RecordingSpoolWriting {
    private static let magic: UInt32 = 0x5446_5231
    private static let version: UInt16 = 1
    private static let headerBytes = 124
    private static let maximumDeviceIDBytes = 512
    private static let maximumRecordBytes =
        headerBytes + maximumDeviceIDBytes
            + RecordingPCMFormat.canonicalSampleRate * 2 * 2 + 28

    private let recordingID: UUID
    private let directoryURL: URL
    private let keyStore: any RecordingKeyStoring
    private let key: SymmetricKey
    private var reservation: SpoolDiskReservation?
    private var sequences: [RecordingTrackKind: Int] = [:]
    private var fileHandles: [RecordingTrackKind: FileHandle] = [:]
    private var storedBytes: Int64 = 0
    private var recordedGaps: [RecordingGap] = []
    private var isSealed = false

    static func create(
        recordingID: UUID,
        rootURL: URL,
        keyStore: any RecordingKeyStoring,
        reservationBytes: Int64 = 0
    ) async throws -> EncryptedRecordingSpool {
        try secureDirectory(rootURL)
        let directory = rootURL.appendingPathComponent(recordingID.uuidString, isDirectory: true)
        try secureDirectory(directory)
        let key = try await keyStore.create(recordingID: recordingID)
        do {
            let reservation = try reservationBytes > 0
                ? SpoolDiskReservation(
                    url: directory.appendingPathComponent(".reserve"),
                    bytes: reservationBytes
                )
                : nil
            return EncryptedRecordingSpool(
                recordingID: recordingID,
                directoryURL: directory,
                keyStore: keyStore,
                key: key,
                reservation: reservation
            )
        } catch {
            try? await keyStore.delete(recordingID: recordingID)
            try? FileManager.default.removeItem(at: directory)
            throw error
        }
    }

    private init(
        recordingID: UUID,
        directoryURL: URL,
        keyStore: any RecordingKeyStoring,
        key: SymmetricKey,
        reservation: SpoolDiskReservation?
    ) {
        self.recordingID = recordingID
        self.directoryURL = directoryURL
        self.keyStore = keyStore
        self.key = key
        self.reservation = reservation
    }

    func append(_ unvalidatedChunk: RecordingPCMChunk) async throws {
        guard !isSealed else { throw RecordingSpoolError.sealed }
        let chunk = try unvalidatedChunk.validated()
        guard chunk.sampleCount <= RecordingPCMFormat.canonicalSampleRate else {
            throw RecordingSpoolError.invalidRecord
        }
        let deviceID = Data(chunk.source.deviceID.utf8)
        guard deviceID.count <= Self.maximumDeviceIDBytes else {
            throw RecordingSpoolError.invalidRecord
        }
        let nextStoredBytes = storedBytes + Int64(chunk.payload.count)
        guard nextStoredBytes <= RecordingDiskPolicy.maximumRecordingBytes else {
            throw RecordingSpoolError.recordingLimitReached
        }
        let sequence = sequences[chunk.track, default: 0]
        let header = try Self.header(
            recordingID: recordingID, sequence: sequence, chunk: chunk, deviceID: deviceID
        )
        var plaintext = deviceID
        plaintext.append(chunk.payload)
        let sealed = try AES.GCM.seal(plaintext, using: key, authenticating: header)
        guard let combined = sealed.combined else { throw RecordingSpoolError.invalidRecord }
        var body = header
        body.append(combined)
        guard body.count <= Self.maximumRecordBytes else { throw RecordingSpoolError.invalidRecord }
        var record = Data()
        record.appendFixedWidth(UInt32(body.count))
        record.append(body)

        let handle = try fileHandle(for: chunk.track)
        try handle.seekToEnd()
        try handle.write(contentsOf: record)
        try handle.synchronize()
        sequences[chunk.track] = sequence + 1
        storedBytes = nextStoredBytes
        try reservation?.shrink(by: Int64(chunk.payload.count))
    }

    func record(gap: RecordingGap) async {
        guard !isSealed else { return }
        recordedGaps.append(gap)
    }

    func seal(gaps: [RecordingGap]) async throws {
        guard !isSealed else { return }
        for handle in fileHandles.values {
            try handle.synchronize()
            try handle.close()
        }
        fileHandles.removeAll()
        try reservation?.release()
        reservation = nil
        let state = RecordingSpoolState(
            schemaVersion: 1,
            recordingID: recordingID,
            sealed: true,
            gaps: recordedGaps + gaps,
            releaseGates: .init(
                audioCreatedOnServer: false, transcriptLineageAccepted: false
            )
        )
        let stateData = try JSONEncoder.recording.encode(state)
        let authenticationKey = Self.stateAuthenticationKey(
            rootKey: key, recordingID: recordingID
        )
        let authentication = Data(HMAC<SHA256>.authenticationCode(
            for: stateData, using: authenticationKey
        ))
        let data = try JSONEncoder.recording.encode(AuthenticatedSpoolState(
            state: state, authentication: authentication
        ))
        let stateURL = directoryURL.appendingPathComponent("state.json")
        try data.write(to: stateURL, options: [.atomic])
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o600], ofItemAtPath: stateURL.path
        )
        isSealed = true
    }

    static func recover(
        recordingID: UUID,
        rootURL: URL,
        keyStore: any RecordingKeyStoring
    ) async throws -> RecordingSpoolRecovery {
        let directory = rootURL.appendingPathComponent(recordingID.uuidString, isDirectory: true)
        try? FileManager.default.removeItem(at: directory.appendingPathComponent(".reserve"))
        let key = try await keyStore.load(recordingID: recordingID)
        let state = try recoverState(directory: directory, recordingID: recordingID, key: key)
        var records: [RecoveredSpoolRecord] = []
        var corrupt: [RecordingGap] = []
        var ignoredTail = false
        for track in RecordingTrackKind.allCases {
            let url = directory.appendingPathComponent(track.fileName)
            guard FileManager.default.fileExists(atPath: url.path) else { continue }
            let result = try recoverTrack(
                url: url,
                expectedRecordingID: recordingID,
                expectedTrack: track,
                key: key
            )
            records.append(contentsOf: result.records)
            corrupt.append(contentsOf: result.corruptRanges)
            ignoredTail = ignoredTail || result.ignoredIncompleteTail
        }
        return .init(
            records: records,
            gaps: state?.gaps ?? [],
            corruptRanges: corrupt,
            ignoredIncompleteTail: ignoredTail,
            sealed: state?.sealed ?? false,
            releaseGates: state?.releaseGates ?? .init(
                audioCreatedOnServer: false, transcriptLineageAccepted: false
            )
        )
    }

    private static func recoverTrack(
        url: URL,
        expectedRecordingID: UUID,
        expectedTrack: RecordingTrackKind,
        key: SymmetricKey
    ) throws -> RecordingSpoolRecovery {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var records: [RecoveredSpoolRecord] = []
        var corrupt: [RecordingGap] = []
        var ignoredTail = false
        var expectedSequence = 0
        while true {
            let lengthData = try handle.read(upToCount: 4) ?? Data()
            if lengthData.isEmpty { break }
            guard lengthData.count == 4, let length = lengthData.fixedWidth(at: 0, as: UInt32.self) else {
                ignoredTail = true
                break
            }
            guard Int(length) >= headerBytes, Int(length) <= maximumRecordBytes else {
                throw RecordingSpoolError.invalidRecord
            }
            let body = try handle.read(upToCount: Int(length)) ?? Data()
            guard body.count == Int(length) else {
                ignoredTail = true
                break
            }
            let headerData = body.prefix(headerBytes)
            let parsed = try parseHeader(Data(headerData))
            guard parsed.recordingID == expectedRecordingID,
                  parsed.track == expectedTrack,
                  parsed.sequence == expectedSequence
            else { throw RecordingSpoolError.invalidRecord }
            expectedSequence += 1
            do {
                let sealed = try AES.GCM.SealedBox(combined: body.dropFirst(headerBytes))
                let plaintext = try AES.GCM.open(sealed, using: key, authenticating: headerData)
                guard plaintext.count == parsed.deviceIDLength + parsed.payloadLength else {
                    throw RecordingSpoolError.invalidRecord
                }
                let deviceData = plaintext.prefix(parsed.deviceIDLength)
                let payload = Data(plaintext.dropFirst(parsed.deviceIDLength))
                guard Data(SHA256.hash(data: payload)) == parsed.payloadHash else {
                    throw RecordingSpoolError.payloadHashMismatch
                }
                guard Data(SHA256.hash(data: deviceData)) == parsed.deviceIDHash,
                      let deviceID = String(data: deviceData, encoding: .utf8)
                else { throw RecordingSpoolError.invalidRecord }
                let format = try RecordingPCMFormat(
                    track: parsed.track, channelCount: parsed.canonicalChannels
                )
                let chunk = RecordingPCMChunk(
                    track: parsed.track,
                    presentationNanoseconds: parsed.presentationNanoseconds,
                    sampleStart: parsed.sampleStart,
                    sampleCount: parsed.sampleCount,
                    format: format,
                    source: .init(
                        sampleRate: Double(parsed.sourceSampleRate),
                        channelCount: parsed.sourceChannels,
                        deviceID: deviceID,
                        presentationNanoseconds: parsed.presentationNanoseconds
                    ),
                    payload: payload
                )
                _ = try chunk.validated()
                records.append(.init(
                    recordingID: parsed.recordingID,
                    sequence: parsed.sequence,
                    payload: payload,
                    chunk: chunk
                ))
            } catch {
                corrupt.append(.init(
                    track: parsed.track,
                    sampleStart: parsed.sampleStart,
                    sampleCount: parsed.sampleCount,
                    reason: .corruptSpoolRecord
                ))
            }
        }
        return .init(
            records: records,
            gaps: [],
            corruptRanges: corrupt,
            ignoredIncompleteTail: ignoredTail,
            sealed: false,
            releaseGates: .init(
                audioCreatedOnServer: false, transcriptLineageAccepted: false
            )
        )
    }

    private static func recoverState(
        directory: URL,
        recordingID: UUID,
        key: SymmetricKey
    ) throws -> RecordingSpoolState? {
        let url = directory.appendingPathComponent("state.json")
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        let envelope = try JSONDecoder().decode(
            AuthenticatedSpoolState.self, from: Data(contentsOf: url)
        )
        guard envelope.state.recordingID == recordingID else {
            throw RecordingSpoolError.invalidRecord
        }
        let stateData = try JSONEncoder.recording.encode(envelope.state)
        let authenticationKey = stateAuthenticationKey(
            rootKey: key, recordingID: recordingID
        )
        guard HMAC<SHA256>.isValidAuthenticationCode(
            envelope.authentication,
            authenticating: stateData,
            using: authenticationKey
        ) else { throw RecordingSpoolError.authenticationFailed }
        return envelope.state
    }

    private static func stateAuthenticationKey(
        rootKey: SymmetricKey,
        recordingID: UUID
    ) -> SymmetricKey {
        HKDF<SHA256>.deriveKey(
            inputKeyMaterial: rootKey,
            salt: Data("tamforge.recording.spool-state.v1".utf8),
            info: Data(recordingID.uuidString.utf8),
            outputByteCount: 32
        )
    }

    private func fileHandle(for track: RecordingTrackKind) throws -> FileHandle {
        if let handle = fileHandles[track] { return handle }
        let url = directoryURL.appendingPathComponent(track.fileName)
        if !FileManager.default.fileExists(atPath: url.path) {
            FileManager.default.createFile(
                atPath: url.path, contents: nil,
                attributes: [.posixPermissions: 0o600]
            )
        }
        let handle = try FileHandle(forWritingTo: url)
        fileHandles[track] = handle
        return handle
    }

    private static func secureDirectory(_ url: URL) throws {
        try FileManager.default.createDirectory(
            at: url,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o700], ofItemAtPath: url.path
        )
    }

    private static func header(
        recordingID: UUID,
        sequence: Int,
        chunk: RecordingPCMChunk,
        deviceID: Data
    ) throws -> Data {
        guard let sequence = UInt32(exactly: sequence),
              let sampleStart = UInt64(exactly: chunk.sampleStart),
              let sampleCount = UInt32(exactly: chunk.sampleCount),
              let payloadLength = UInt32(exactly: chunk.payload.count),
              let sourceRate = UInt32(exactly: Int(chunk.source.sampleRate.rounded())),
              let sourceChannels = UInt16(exactly: chunk.source.channelCount),
              let deviceLength = UInt16(exactly: deviceID.count)
        else { throw RecordingSpoolError.invalidRecord }
        var data = Data()
        data.appendFixedWidth(magic)
        data.appendFixedWidth(version)
        data.append(chunk.track.byteValue)
        data.append(UInt8(chunk.format.channelCount))
        data.appendUUID(recordingID)
        data.appendFixedWidth(sequence)
        data.appendFixedWidth(sampleStart)
        data.appendFixedWidth(sampleCount)
        data.appendFixedWidth(payloadLength)
        data.appendFixedWidth(sourceRate)
        data.appendFixedWidth(sourceChannels)
        data.appendFixedWidth(deviceLength)
        data.appendFixedWidth(UInt64(bitPattern: chunk.presentationNanoseconds))
        data.append(Data(SHA256.hash(data: deviceID)))
        data.append(Data(SHA256.hash(data: chunk.payload)))
        guard data.count == headerBytes else { throw RecordingSpoolError.invalidRecord }
        return data
    }

    private static func parseHeader(_ data: Data) throws -> ParsedSpoolHeader {
        guard data.count == headerBytes,
              data.fixedWidth(at: 0, as: UInt32.self) == magic,
              data.fixedWidth(at: 4, as: UInt16.self) == version,
              let track = RecordingTrackKind(byteValue: data[6]),
              let recordingID = data.uuid(at: 8),
              let sequence = data.fixedWidth(at: 24, as: UInt32.self),
              let sampleStart = data.fixedWidth(at: 28, as: UInt64.self),
              let sampleCount = data.fixedWidth(at: 36, as: UInt32.self),
              let payloadLength = data.fixedWidth(at: 40, as: UInt32.self),
              let sourceRate = data.fixedWidth(at: 44, as: UInt32.self),
              let sourceChannels = data.fixedWidth(at: 48, as: UInt16.self),
              let deviceLength = data.fixedWidth(at: 50, as: UInt16.self),
              let presentation = data.fixedWidth(at: 52, as: UInt64.self)
        else { throw RecordingSpoolError.invalidRecord }
        let channels = Int(data[7])
        guard channels == (track == .microphone ? 1 : 2),
              sampleCount > 0,
              sampleCount <= RecordingPCMFormat.canonicalSampleRate,
              payloadLength == sampleCount * UInt32(channels * RecordingPCMFormat.bytesPerSample),
              Int(deviceLength) <= maximumDeviceIDBytes,
              let boundedSampleStart = Int64(exactly: sampleStart)
        else { throw RecordingSpoolError.invalidRecord }
        return .init(
            recordingID: recordingID,
            track: track,
            canonicalChannels: channels,
            sequence: Int(sequence),
            sampleStart: boundedSampleStart,
            sampleCount: Int(sampleCount),
            payloadLength: Int(payloadLength),
            sourceSampleRate: Int(sourceRate),
            sourceChannels: Int(sourceChannels),
            deviceIDLength: Int(deviceLength),
            presentationNanoseconds: Int64(bitPattern: presentation),
            deviceIDHash: Data(data[60..<92]),
            payloadHash: Data(data[92..<124])
        )
    }
}

private struct ParsedSpoolHeader {
    let recordingID: UUID
    let track: RecordingTrackKind
    let canonicalChannels: Int
    let sequence: Int
    let sampleStart: Int64
    let sampleCount: Int
    let payloadLength: Int
    let sourceSampleRate: Int
    let sourceChannels: Int
    let deviceIDLength: Int
    let presentationNanoseconds: Int64
    let deviceIDHash: Data
    let payloadHash: Data
}

private struct RecordingSpoolState: Codable {
    let schemaVersion: Int
    let recordingID: UUID
    let sealed: Bool
    let gaps: [RecordingGap]
    let releaseGates: RecordingReleaseGates
}

private struct AuthenticatedSpoolState: Codable {
    let state: RecordingSpoolState
    let authentication: Data
}

private final class SpoolDiskReservation: @unchecked Sendable {
    private let url: URL
    private var descriptor: Int32
    private var remainingBytes: Int64

    init(url: URL, bytes: Int64) throws {
        guard bytes > 0 else { throw RecordingSpoolError.reservationFailed }
        self.url = url
        remainingBytes = bytes
        descriptor = open(url.path, O_CREAT | O_RDWR, S_IRUSR | S_IWUSR)
        guard descriptor >= 0 else { throw RecordingSpoolError.reservationFailed }
        var allocation = fstore_t(
            fst_flags: UInt32(F_ALLOCATEALL),
            fst_posmode: F_PEOFPOSMODE,
            fst_offset: 0,
            fst_length: bytes,
            fst_bytesalloc: 0
        )
        guard fcntl(descriptor, F_PREALLOCATE, &allocation) != -1,
              ftruncate(descriptor, bytes) == 0
        else {
            close(descriptor)
            descriptor = -1
            try? FileManager.default.removeItem(at: url)
            throw RecordingSpoolError.reservationFailed
        }
    }

    deinit {
        if descriptor >= 0 { close(descriptor) }
    }

    func shrink(by consumedBytes: Int64) throws {
        guard consumedBytes >= 0 else { throw RecordingSpoolError.reservationFailed }
        remainingBytes = Swift.max(0, remainingBytes - consumedBytes)
        guard ftruncate(descriptor, remainingBytes) == 0 else {
            throw RecordingSpoolError.reservationFailed
        }
    }

    func release() throws {
        if descriptor >= 0 {
            guard close(descriptor) == 0 else { throw RecordingSpoolError.reservationFailed }
            descriptor = -1
        }
        if FileManager.default.fileExists(atPath: url.path) {
            try FileManager.default.removeItem(at: url)
        }
    }
}

private extension RecordingTrackKind {
    var byteValue: UInt8 { self == .microphone ? 1 : 2 }
    init?(byteValue: UInt8) {
        switch byteValue {
        case 1: self = .microphone
        case 2: self = .systemAudio
        default: return nil
        }
    }
    var fileName: String { self == .microphone ? "microphone.tfr" : "system-audio.tfr" }
}

private extension JSONEncoder {
    static var recording: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return encoder
    }
}

private extension Data {
    mutating func appendFixedWidth<T: FixedWidthInteger>(_ value: T) {
        var bigEndian = value.bigEndian
        Swift.withUnsafeBytes(of: &bigEndian) { append(contentsOf: $0) }
    }

    func fixedWidth<T: FixedWidthInteger>(at offset: Int, as type: T.Type) -> T? {
        guard offset >= 0, offset + MemoryLayout<T>.size <= count else { return nil }
        return self[offset..<(offset + MemoryLayout<T>.size)].withUnsafeBytes {
            T(bigEndian: $0.loadUnaligned(as: T.self))
        }
    }

    mutating func appendUUID(_ uuid: UUID) {
        var bytes = uuid.uuid
        Swift.withUnsafeBytes(of: &bytes) { append(contentsOf: $0) }
    }

    func uuid(at offset: Int) -> UUID? {
        guard offset >= 0, offset + 16 <= count else { return nil }
        let bytes = self[offset..<(offset + 16)]
        let tuple: uuid_t = bytes.withUnsafeBytes { $0.loadUnaligned(as: uuid_t.self) }
        return UUID(uuid: tuple)
    }
}
