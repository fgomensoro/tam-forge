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

enum RecordingSpoolCorruptionReason: Equatable, Sendable {
    case malformedLength
    case malformedHeader
    case identityMismatch
    case sequenceMismatch
    case malformedState
    case malformedGapJournal
}

struct RecordingSpoolUnrecoverableCorruption: Equatable, Sendable {
    let track: RecordingTrackKind?
    let byteOffset: Int64?
    let reason: RecordingSpoolCorruptionReason
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
    let unrecoverableCorruptions: [RecordingSpoolUnrecoverableCorruption]
    let ignoredIncompleteTail: Bool
    let sealed: Bool
    let releaseGates: RecordingReleaseGates
}

actor EncryptedRecordingSpool: RecordingSpoolWriting {
    private static let magic: UInt32 = 0x5446_5231
    private static let version: UInt16 = 3
    private static let metadataHeaderBytes = 160
    private static let metadataAuthenticationBytes = 32
    private static let headerBytes = metadataHeaderBytes + metadataAuthenticationBytes
    private static let maximumDeviceIDBytes = 512
    private static let maximumRouteBytes = 512
    private static let maximumGapJournalRecordBytes = 4_096
    private static let gapJournalFileName = "gaps.tfj"
    private static let maximumRecordBytes =
        headerBytes + maximumDeviceIDBytes + maximumRouteBytes
            + RecordingPCMFormat.canonicalSampleRate * 2 * 2 + 28

    private let recordingID: UUID
    private let directoryURL: URL
    private let keyStore: any RecordingKeyStoring
    private let key: SymmetricKey
    private var reservation: SpoolDiskReservation?
    private var sequences: [RecordingTrackKind: Int] = [:]
    private var fileHandles: [RecordingTrackKind: FileHandle] = [:]
    private var gapJournalHandle: FileHandle?
    private var storedBytes: Int64 = 0
    private var gapJournalCount = 0
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
            let spool = EncryptedRecordingSpool(
                recordingID: recordingID,
                directoryURL: directory,
                keyStore: keyStore,
                key: key,
                reservation: reservation
            )
            try await spool.persistState(sealed: false, gapJournalCount: 0)
            return spool
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
        let route = Data(chunk.source.initialRoute.utf8)
        guard deviceID.count <= Self.maximumDeviceIDBytes, route.count <= Self.maximumRouteBytes else {
            throw RecordingSpoolError.invalidRecord
        }
        let nextStoredBytes = storedBytes + Int64(chunk.payload.count)
        guard nextStoredBytes <= RecordingDiskPolicy.maximumRecordingBytes else {
            throw RecordingSpoolError.recordingLimitReached
        }
        let sequence = sequences[chunk.track, default: 0]
        let header = try Self.header(
            recordingID: recordingID,
            sequence: sequence,
            chunk: chunk,
            deviceID: deviceID,
            key: key
        )
        var plaintext = deviceID
        plaintext.append(route)
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

    func record(gap: RecordingGap) async throws {
        guard !isSealed else { return }
        try appendGapJournalRecord(gap: gap, sequence: gapJournalCount)
        gapJournalCount += 1
    }

    func seal(gaps: [RecordingGap]) async throws {
        guard !isSealed else { return }
        for gap in gaps {
            try appendGapJournalRecord(gap: gap, sequence: gapJournalCount)
            gapJournalCount += 1
        }
        for handle in fileHandles.values {
            try handle.synchronize()
            try handle.close()
        }
        fileHandles.removeAll()
        try gapJournalHandle?.synchronize()
        try gapJournalHandle?.close()
        gapJournalHandle = nil
        try reservation?.release()
        reservation = nil
        try persistState(sealed: true, gapJournalCount: gapJournalCount)
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
        let stateResult = recoverState(directory: directory, recordingID: recordingID, key: key)
        let journalResult = recoverGapJournal(
            directory: directory, recordingID: recordingID, key: key
        )
        var records: [RecoveredSpoolRecord] = []
        var corrupt: [RecordingGap] = []
        var unrecoverable = stateResult.unrecoverableCorruption.map { [$0] } ?? []
        unrecoverable.append(contentsOf: journalResult.unrecoverableCorruptions)
        if let state = stateResult.state,
           state.sealed,
           state.gapJournalCount != journalResult.gaps.count {
            unrecoverable.append(.init(
                track: nil, byteOffset: nil, reason: .malformedGapJournal
            ))
        }
        var ignoredTail = journalResult.ignoredIncompleteTail
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
            unrecoverable.append(contentsOf: result.unrecoverableCorruptions)
            ignoredTail = ignoredTail || result.ignoredIncompleteTail
        }
        return .init(
            records: records,
            gaps: journalResult.gaps,
            corruptRanges: corrupt,
            unrecoverableCorruptions: unrecoverable,
            ignoredIncompleteTail: ignoredTail,
            sealed: stateResult.state?.sealed ?? false,
            releaseGates: stateResult.state?.releaseGates ?? .init(
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
        var unrecoverable: [RecordingSpoolUnrecoverableCorruption] = []
        var ignoredTail = false
        var expectedSequence = 0
        var byteOffset: Int64 = 0
        while true {
            let lengthData = try handle.read(upToCount: 4) ?? Data()
            if lengthData.isEmpty { break }
            guard lengthData.count == 4, let length = lengthData.fixedWidth(at: 0, as: UInt32.self) else {
                ignoredTail = true
                break
            }
            guard Int(length) >= headerBytes, Int(length) <= maximumRecordBytes else {
                unrecoverable.append(.init(
                    track: expectedTrack, byteOffset: byteOffset, reason: .malformedLength
                ))
                break
            }
            let body = try handle.read(upToCount: Int(length)) ?? Data()
            guard body.count == Int(length) else {
                ignoredTail = true
                break
            }
            let headerData = body.prefix(headerBytes)
            guard authenticateRecoverableMetadata(
                Data(headerData), key: key, recordingID: expectedRecordingID
            ) else {
                unrecoverable.append(.init(
                    track: expectedTrack, byteOffset: byteOffset, reason: .malformedHeader
                ))
                break
            }
            let parsed: ParsedSpoolHeader
            do {
                parsed = try parseHeader(Data(headerData))
            } catch {
                if let gap = fixedCorruptRange(
                    headerData: Data(headerData),
                    bodyLength: Int(length),
                    expectedRecordingID: expectedRecordingID,
                    expectedTrack: expectedTrack,
                    expectedSequence: expectedSequence
                ) {
                    corrupt.append(gap)
                    expectedSequence += 1
                    byteOffset += 4 + Int64(length)
                    continue
                }
                unrecoverable.append(.init(
                    track: expectedTrack, byteOffset: byteOffset, reason: .malformedHeader
                ))
                break
            }
            guard parsed.recordingID == expectedRecordingID, parsed.track == expectedTrack else {
                unrecoverable.append(.init(
                    track: expectedTrack, byteOffset: byteOffset, reason: .identityMismatch
                ))
                break
            }
            guard parsed.sequence == expectedSequence else {
                unrecoverable.append(.init(
                    track: expectedTrack, byteOffset: byteOffset, reason: .sequenceMismatch
                ))
                break
            }
            guard Int(length) == headerBytes + parsed.deviceIDLength + parsed.routeLength
                + parsed.payloadLength + 28
            else {
                unrecoverable.append(.init(
                    track: expectedTrack, byteOffset: byteOffset, reason: .malformedLength
                ))
                break
            }
            expectedSequence += 1
            byteOffset += 4 + Int64(length)
            do {
                let sealed = try AES.GCM.SealedBox(combined: body.dropFirst(headerBytes))
                let plaintext = try AES.GCM.open(sealed, using: key, authenticating: headerData)
                guard plaintext.count == parsed.deviceIDLength + parsed.routeLength + parsed.payloadLength else {
                    throw RecordingSpoolError.invalidRecord
                }
                let deviceData = plaintext.prefix(parsed.deviceIDLength)
                let routeStart = parsed.deviceIDLength
                let routeEnd = routeStart + parsed.routeLength
                let routeData = plaintext[routeStart..<routeEnd]
                let payload = Data(plaintext.dropFirst(routeEnd))
                guard Data(SHA256.hash(data: payload)) == parsed.payloadHash else {
                    throw RecordingSpoolError.payloadHashMismatch
                }
                guard Data(SHA256.hash(data: deviceData)) == parsed.deviceIDHash,
                      Data(SHA256.hash(data: routeData)) == parsed.routeHash,
                      let deviceID = String(data: deviceData, encoding: .utf8),
                      let initialRoute = String(data: routeData, encoding: .utf8)
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
                        initialRoute: initialRoute,
                        conversionVersion: parsed.conversionVersion,
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
            unrecoverableCorruptions: unrecoverable,
            ignoredIncompleteTail: ignoredTail,
            sealed: false,
            releaseGates: .init(
                audioCreatedOnServer: false, transcriptLineageAccepted: false
            )
        )
    }

    private static func fixedCorruptRange(
        headerData: Data,
        bodyLength: Int,
        expectedRecordingID: UUID,
        expectedTrack: RecordingTrackKind,
        expectedSequence: Int
    ) -> RecordingGap? {
        guard headerData.count == headerBytes,
              headerData.fixedWidth(at: 0, as: UInt32.self) == magic,
              headerData.fixedWidth(at: 4, as: UInt16.self) == version,
              headerData[6] == expectedTrack.byteValue,
              headerData[7] == (expectedTrack == .microphone ? 1 : 2),
              headerData.uuid(at: 8) == expectedRecordingID,
              headerData.fixedWidth(at: 24, as: UInt32.self) == UInt32(exactly: expectedSequence),
              let sampleStart = headerData.fixedWidth(at: 28, as: UInt64.self),
              let boundedSampleStart = Int64(exactly: sampleStart),
              let sampleCount = headerData.fixedWidth(at: 36, as: UInt32.self),
              sampleCount > 0,
              sampleCount <= RecordingPCMFormat.canonicalSampleRate,
              let payloadLength = headerData.fixedWidth(at: 40, as: UInt32.self),
              payloadLength == sampleCount * UInt32(
                Int(headerData[7]) * RecordingPCMFormat.bytesPerSample
              ),
              let deviceLength = headerData.fixedWidth(at: 50, as: UInt16.self),
              let routeLength = headerData.fixedWidth(at: 54, as: UInt16.self),
              Int(deviceLength) <= maximumDeviceIDBytes,
              Int(routeLength) <= maximumRouteBytes,
              bodyLength == headerBytes + Int(deviceLength) + Int(routeLength)
                + Int(payloadLength) + 28,
              let boundedSampleCount = Int(exactly: sampleCount)
        else { return nil }
        return .init(
            track: expectedTrack,
            sampleStart: boundedSampleStart,
            sampleCount: boundedSampleCount,
            reason: .corruptSpoolRecord
        )
    }

    private static func recoverState(
        directory: URL,
        recordingID: UUID,
        key: SymmetricKey
    ) -> RecoveredSpoolState {
        let url = directory.appendingPathComponent("state.json")
        guard FileManager.default.fileExists(atPath: url.path) else { return .init(state: nil) }
        do {
            let envelope = try JSONDecoder().decode(
                AuthenticatedSpoolState.self, from: Data(contentsOf: url)
            )
            guard envelope.state.schemaVersion == 2,
                  envelope.state.recordingID == recordingID,
                  envelope.state.gapJournalCount >= 0
            else {
                return .init(state: nil, unrecoverableCorruption: .init(
                    track: nil, byteOffset: nil, reason: .malformedState
                ))
            }
            let stateData = try JSONEncoder.recording.encode(envelope.state)
            let authenticationKey = stateAuthenticationKey(
                rootKey: key, recordingID: recordingID
            )
            guard HMAC<SHA256>.isValidAuthenticationCode(
                envelope.authentication,
                authenticating: stateData,
                using: authenticationKey
            ) else {
                return .init(state: nil, unrecoverableCorruption: .init(
                    track: nil, byteOffset: nil, reason: .malformedState
                ))
            }
            return .init(state: envelope.state)
        } catch {
            return .init(state: nil, unrecoverableCorruption: .init(
                track: nil, byteOffset: nil, reason: .malformedState
            ))
        }
    }

    private func persistState(sealed: Bool, gapJournalCount: Int) throws {
        let state = RecordingSpoolState(
            schemaVersion: 2,
            recordingID: recordingID,
            sealed: sealed,
            gapJournalCount: gapJournalCount,
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
    }

    private func appendGapJournalRecord(gap: RecordingGap, sequence: Int) throws {
        let entry = RecordingGapJournalEntry(
            recordingID: recordingID,
            sequence: sequence,
            gap: gap
        )
        let entryData = try JSONEncoder.recording.encode(entry)
        let authentication = Data(HMAC<SHA256>.authenticationCode(
            for: entryData,
            using: Self.gapJournalAuthenticationKey(rootKey: key, recordingID: recordingID)
        ))
        let body = try JSONEncoder.recording.encode(AuthenticatedGapJournalEntry(
            entry: entry,
            authentication: authentication
        ))
        guard body.count <= Self.maximumGapJournalRecordBytes,
              let length = UInt32(exactly: body.count)
        else { throw RecordingSpoolError.invalidRecord }
        var record = Data()
        record.appendFixedWidth(length)
        record.append(body)
        let handle = try gapJournalFileHandle()
        try handle.seekToEnd()
        try handle.write(contentsOf: record)
        try handle.synchronize()
    }

    private func gapJournalFileHandle() throws -> FileHandle {
        if let gapJournalHandle { return gapJournalHandle }
        let url = directoryURL.appendingPathComponent(Self.gapJournalFileName)
        if !FileManager.default.fileExists(atPath: url.path) {
            FileManager.default.createFile(
                atPath: url.path,
                contents: nil,
                attributes: [.posixPermissions: 0o600]
            )
        }
        let handle = try FileHandle(forWritingTo: url)
        gapJournalHandle = handle
        return handle
    }

    private static func recoverGapJournal(
        directory: URL,
        recordingID: UUID,
        key: SymmetricKey
    ) -> RecoveredGapJournal {
        let url = directory.appendingPathComponent(gapJournalFileName)
        guard FileManager.default.fileExists(atPath: url.path) else { return .init() }
        do {
            let handle = try FileHandle(forReadingFrom: url)
            defer { try? handle.close() }
            var gaps: [RecordingGap] = []
            var expectedSequence = 0
            var ignoredIncompleteTail = false
            while true {
                let lengthData = try handle.read(upToCount: 4) ?? Data()
                if lengthData.isEmpty { break }
                guard lengthData.count == 4,
                      let length = lengthData.fixedWidth(at: 0, as: UInt32.self),
                      length > 0,
                      Int(length) <= maximumGapJournalRecordBytes
                else {
                    if lengthData.count < 4 { ignoredIncompleteTail = true }
                    else {
                        return .init(
                            gaps: gaps,
                            unrecoverableCorruptions: [.init(
                                track: nil, byteOffset: nil, reason: .malformedGapJournal
                            )],
                            ignoredIncompleteTail: ignoredIncompleteTail
                        )
                    }
                    break
                }
                let body = try handle.read(upToCount: Int(length)) ?? Data()
                guard body.count == Int(length) else {
                    ignoredIncompleteTail = true
                    break
                }
                let envelope: AuthenticatedGapJournalEntry
                do {
                    envelope = try JSONDecoder().decode(
                        AuthenticatedGapJournalEntry.self, from: body
                    )
                } catch {
                    return .init(
                        gaps: gaps,
                        unrecoverableCorruptions: [.init(
                            track: nil, byteOffset: nil, reason: .malformedGapJournal
                        )],
                        ignoredIncompleteTail: ignoredIncompleteTail
                    )
                }
                guard envelope.entry.recordingID == recordingID,
                      envelope.entry.sequence == expectedSequence,
                      envelope.entry.gap.sampleStart >= 0,
                      envelope.entry.gap.sampleCount > 0
                else {
                    return .init(
                        gaps: gaps,
                        unrecoverableCorruptions: [.init(
                            track: nil, byteOffset: nil, reason: .malformedGapJournal
                        )],
                        ignoredIncompleteTail: ignoredIncompleteTail
                    )
                }
                let entryData = try JSONEncoder.recording.encode(envelope.entry)
                guard HMAC<SHA256>.isValidAuthenticationCode(
                    envelope.authentication,
                    authenticating: entryData,
                    using: gapJournalAuthenticationKey(rootKey: key, recordingID: recordingID)
                ) else {
                    return .init(
                        gaps: gaps,
                        unrecoverableCorruptions: [.init(
                            track: nil, byteOffset: nil, reason: .malformedGapJournal
                        )],
                        ignoredIncompleteTail: ignoredIncompleteTail
                    )
                }
                gaps.append(envelope.entry.gap)
                expectedSequence += 1
            }
            return .init(gaps: gaps, ignoredIncompleteTail: ignoredIncompleteTail)
        } catch {
            return .init(unrecoverableCorruptions: [.init(
                track: nil, byteOffset: nil, reason: .malformedGapJournal
            )])
        }
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

    private static func gapJournalAuthenticationKey(
        rootKey: SymmetricKey,
        recordingID: UUID
    ) -> SymmetricKey {
        HKDF<SHA256>.deriveKey(
            inputKeyMaterial: rootKey,
            salt: Data("tamforge.recording.spool-gap-journal.v1".utf8),
            info: Data(recordingID.uuidString.utf8),
            outputByteCount: 32
        )
    }

    private static func recordMetadataAuthenticationKey(
        rootKey: SymmetricKey,
        recordingID: UUID
    ) -> SymmetricKey {
        HKDF<SHA256>.deriveKey(
            inputKeyMaterial: rootKey,
            salt: Data("tamforge.recording.spool-record-metadata.v1".utf8),
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
        deviceID: Data,
        key: SymmetricKey
    ) throws -> Data {
        let route = Data(chunk.source.initialRoute.utf8)
        guard let sequence = UInt32(exactly: sequence),
              let sampleStart = UInt64(exactly: chunk.sampleStart),
              let sampleCount = UInt32(exactly: chunk.sampleCount),
              let payloadLength = UInt32(exactly: chunk.payload.count),
              let sourceRate = UInt32(exactly: Int(chunk.source.sampleRate.rounded())),
              let sourceChannels = UInt16(exactly: chunk.source.channelCount),
              let deviceLength = UInt16(exactly: deviceID.count),
              let conversionVersion = UInt16(exactly: chunk.source.conversionVersion),
              let routeLength = UInt16(exactly: route.count),
              route.count <= maximumRouteBytes
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
        data.appendFixedWidth(conversionVersion)
        data.appendFixedWidth(routeLength)
        data.appendFixedWidth(UInt64(bitPattern: chunk.presentationNanoseconds))
        data.append(Data(SHA256.hash(data: deviceID)))
        data.append(Data(SHA256.hash(data: route)))
        data.append(Data(SHA256.hash(data: chunk.payload)))
        guard data.count == metadataHeaderBytes else { throw RecordingSpoolError.invalidRecord }
        data.append(Data(HMAC<SHA256>.authenticationCode(
            for: data,
            using: recordMetadataAuthenticationKey(rootKey: key, recordingID: recordingID)
        )))
        guard data.count == headerBytes else { throw RecordingSpoolError.invalidRecord }
        return data
    }

    // AES-GCM authenticates AAD only when open succeeds. This tag keeps the
    // recoverable range trustworthy when ciphertext is corrupt, but rejects
    // header bit-rot and tampering before recovery can emit a gap.
    private static func authenticateRecoverableMetadata(
        _ data: Data,
        key: SymmetricKey,
        recordingID: UUID
    ) -> Bool {
        guard data.count == headerBytes else { return false }
        return HMAC<SHA256>.isValidAuthenticationCode(
            Data(data[metadataHeaderBytes..<headerBytes]),
            authenticating: Data(data[..<metadataHeaderBytes]),
            using: recordMetadataAuthenticationKey(rootKey: key, recordingID: recordingID)
        )
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
              let conversionVersion = data.fixedWidth(at: 52, as: UInt16.self),
              let routeLength = data.fixedWidth(at: 54, as: UInt16.self),
              let presentation = data.fixedWidth(at: 56, as: UInt64.self)
        else { throw RecordingSpoolError.invalidRecord }
        let channels = Int(data[7])
        guard channels == (track == .microphone ? 1 : 2),
              sampleCount > 0,
              sampleCount <= RecordingPCMFormat.canonicalSampleRate,
              payloadLength == sampleCount * UInt32(channels * RecordingPCMFormat.bytesPerSample),
              sourceRate > 0,
              sourceChannels > 0,
              conversionVersion > 0,
              Int(deviceLength) <= maximumDeviceIDBytes,
              Int(routeLength) <= maximumRouteBytes,
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
            conversionVersion: Int(conversionVersion),
            routeLength: Int(routeLength),
            presentationNanoseconds: Int64(bitPattern: presentation),
            deviceIDHash: Data(data[64..<96]),
            routeHash: Data(data[96..<128]),
            payloadHash: Data(data[128..<160])
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
    let conversionVersion: Int
    let routeLength: Int
    let presentationNanoseconds: Int64
    let deviceIDHash: Data
    let routeHash: Data
    let payloadHash: Data
}

private struct RecordingSpoolState: Codable {
    let schemaVersion: Int
    let recordingID: UUID
    let sealed: Bool
    let gapJournalCount: Int
    let releaseGates: RecordingReleaseGates
}

private struct AuthenticatedSpoolState: Codable {
    let state: RecordingSpoolState
    let authentication: Data
}

private struct RecordingGapJournalEntry: Codable {
    let recordingID: UUID
    let sequence: Int
    let gap: RecordingGap
}

private struct AuthenticatedGapJournalEntry: Codable {
    let entry: RecordingGapJournalEntry
    let authentication: Data
}

private struct RecoveredGapJournal {
    let gaps: [RecordingGap]
    let unrecoverableCorruptions: [RecordingSpoolUnrecoverableCorruption]
    let ignoredIncompleteTail: Bool

    init(
        gaps: [RecordingGap] = [],
        unrecoverableCorruptions: [RecordingSpoolUnrecoverableCorruption] = [],
        ignoredIncompleteTail: Bool = false
    ) {
        self.gaps = gaps
        self.unrecoverableCorruptions = unrecoverableCorruptions
        self.ignoredIncompleteTail = ignoredIncompleteTail
    }
}

private struct RecoveredSpoolState {
    let state: RecordingSpoolState?
    let unrecoverableCorruption: RecordingSpoolUnrecoverableCorruption?

    init(
        state: RecordingSpoolState?,
        unrecoverableCorruption: RecordingSpoolUnrecoverableCorruption? = nil
    ) {
        self.state = state
        self.unrecoverableCorruption = unrecoverableCorruption
    }
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
