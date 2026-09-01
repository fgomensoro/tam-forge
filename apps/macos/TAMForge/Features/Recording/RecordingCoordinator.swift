import AppKit
import Combine
import Foundation

private enum PendingGapWriteError: Error {
    case nonContiguousGap
}

final class PendingGapWrites: @unchecked Sendable {
    private let lock = NSLock()
    private let maximumIntervals = 12 // Two tracks × six persisted gap reasons.
    private var pending: [String: RecordingGap] = [:]
    private var worker: Task<Void, Error>?
    private var storageFailure: Error?

    var bufferedIntervalCount: Int {
        lock.lock()
        defer { lock.unlock() }
        return pending.count
    }

    // Registration is synchronous. One yielded worker persists bounded batches.
    func register(gap: RecordingGap, spool: any RecordingSpoolWriting) {
        lock.lock()
        defer { lock.unlock() }
        guard storageFailure == nil else { return }
        let key = "\(gap.track.rawValue):\(gap.reason.rawValue)"
        if let existing = pending[key] {
            guard let merged = Self.merge(existing, gap) else {
                storageFailure = PendingGapWriteError.nonContiguousGap
                return
            }
            pending[key] = merged
        } else {
            guard pending.count < maximumIntervals else {
                storageFailure = PendingGapWriteError.nonContiguousGap
                return
            }
            pending[key] = gap
        }
        if worker == nil { startWorkerLocked(spool: spool) }
    }

    func flush() async throws {
        while true {
            let (activeWorker, failure) = lock.withLock { (worker, storageFailure) }
            if let activeWorker {
                try await activeWorker.value
                continue
            }
            if let failure { throw failure }
            return
        }
    }

    private func startWorkerLocked(spool: any RecordingSpoolWriting) {
        worker = Task { [weak self] in
            guard let self else { return }
            try await self.writePending(using: spool)
        }
    }

    private func writePending(using spool: any RecordingSpoolWriting) async throws {
        await Task.yield()
        do {
            while true {
                let batch: [RecordingGap]? = lock.withLock {
                    guard !pending.isEmpty else {
                        // Clear under this lock: a later synchronous registration
                        // starts its worker.
                        worker = nil
                        return nil
                    }
                    let sorted = pending.values.sorted {
                        if $0.track.rawValue != $1.track.rawValue {
                            return $0.track.rawValue < $1.track.rawValue
                        }
                        if $0.sampleStart != $1.sampleStart {
                            return $0.sampleStart < $1.sampleStart
                        }
                        return $0.reason.rawValue < $1.reason.rawValue
                    }
                    pending.removeAll(keepingCapacity: true)
                    return sorted
                }
                guard let batch else { return }
                for gap in batch { try await spool.record(gap: gap) }
            }
        } catch {
            lock.withLock {
                if storageFailure == nil { storageFailure = error }
                worker = nil
            }
            throw error
        }
    }

    // Only touching intervals may be represented by one persisted gap.
    static func merge(_ current: RecordingGap, _ next: RecordingGap) -> RecordingGap? {
        let (currentEnd, currentOverflow) = current.sampleStart
            .addingReportingOverflow(Int64(current.sampleCount))
        let (nextEnd, nextOverflow) = next.sampleStart
            .addingReportingOverflow(Int64(next.sampleCount))
        guard current.track == next.track,
              current.reason == next.reason,
              !currentOverflow,
              !nextOverflow,
              next.sampleStart <= currentEnd,
              current.sampleStart <= nextEnd
        else { return nil }
        let start = Swift.min(current.sampleStart, next.sampleStart)
        let end = Swift.max(currentEnd, nextEnd)
        let (count, countOverflow) = end.subtractingReportingOverflow(start)
        guard !countOverflow, let sampleCount = Int(exactly: count) else { return nil }
        return .init(
            track: current.track,
            sampleStart: start,
            sampleCount: sampleCount,
            reason: current.reason
        )
    }
}

@MainActor
final class RecordingCoordinator: ObservableObject {
    @Published private(set) var phase: RecordingPhase = .idle
    @Published private(set) var preflightSnapshot: RecordingPreflightSnapshot?
    @Published private(set) var health = RecordingHealth()
    @Published private(set) var startedAt: Date?
    @Published private(set) var pendingRecordingIDs: [UUID] = []

    private let preflight: any RecordingPreflighting
    private let source: any RecordingCaptureSource
    private let spoolFactory: any RecordingSpoolCreating
    private var spool: (any RecordingSpoolWriting)?
    private var eventContinuation: AsyncStream<RecordingCaptureEvent>.Continuation?
    private var writerTask: Task<Void, Never>?
    private var pendingGapWrites: PendingGapWrites?
    private var lifecycleTask: Task<Void, Never>?
    private var durationLimitTask: Task<Void, Never>?
    private var accumulatedGaps: [RecordingGap] = []
    private var activeStorageFailure: Error?
    // Terminal coverage loss (a required track never anchored). The unsealed
    // spool must drain and stay recoverable; it can never seal.
    private var fatalCaptureFailure: RecordingCaptureFailure?

    init(
        preflight: any RecordingPreflighting = LiveRecordingPreflight(),
        source: any RecordingCaptureSource = ScreenCaptureAudioSource(),
        spoolFactory: any RecordingSpoolCreating = EncryptedRecordingSpoolFactory()
    ) {
        self.preflight = preflight
        self.source = source
        self.spoolFactory = spoolFactory
        lifecycleTask = Task { [weak self] in
            for await _ in NotificationCenter.default.notifications(
                named: NSWorkspace.willSleepNotification
            ) {
                guard !Task.isCancelled else { return }
                await self?.stop(reason: "Mac sleep")
            }
        }
        Task { [weak self] in
            await self?.refreshPendingRecordings()
        }
    }

    deinit {
        lifecycleTask?.cancel()
        durationLimitTask?.cancel()
        writerTask?.cancel()
        eventContinuation?.finish()
    }

    var requiresStopBeforeSignOut: Bool { phase.isActive }

    func start() async {
        guard !phase.isActive else { return }
        phase = .preflighting
        health = RecordingHealth()
        accumulatedGaps.removeAll(keepingCapacity: true)
        activeStorageFailure = nil
        fatalCaptureFailure = nil
        let result = await preflight.run()
        guard case let .ready(snapshot) = result else {
            if case let .blocked(failure) = result { phase = .blocked(failure) }
            return
        }
        preflightSnapshot = snapshot
        health.routeDescription = snapshot.routeDescription

        let recordingID = UUID()
        var createdSpool = false
        do {
            let spool = try await spoolFactory.create(recordingID: recordingID)
            self.spool = spool
            createdSpool = true
            let pendingGapWrites = PendingGapWrites()
            self.pendingGapWrites = pendingGapWrites
            let (stream, continuation) = AsyncStream.makeStream(
                of: RecordingCaptureEvent.self,
                bufferingPolicy: .bufferingOldest(64)
            )
            eventContinuation = continuation
            writerTask = Task { [weak self] in
                for await event in stream {
                    guard !Task.isCancelled else { return }
                    await self?.consume(event)
                }
            }
            try await source.start(
                microphoneID: snapshot.selectedMicrophone.id,
                initialRoute: snapshot.routeDescription,
                receive: { [spool, pendingGapWrites] event in
                    let result = continuation.yield(event)
                    guard case let .dropped(dropped) = result else { return }
                    let gap: RecordingGap?
                    switch dropped {
                    case let .chunk(chunk):
                        gap = .init(
                            track: chunk.track,
                            sampleStart: chunk.sampleStart,
                            sampleCount: chunk.sampleCount,
                            reason: .callbackOverflow
                        )
                    case let .gap(droppedGap):
                        gap = droppedGap
                    case .level, .route, .failure:
                        gap = nil
                    }
                    if let gap { pendingGapWrites.register(gap: gap, spool: spool) }
                }
            )
            startedAt = Date()
            phase = .recording(recordingID)
            durationLimitTask = Task { [weak self] in
                try? await Task.sleep(for: .seconds(RecordingDiskPolicy.maximumDurationSeconds))
                guard !Task.isCancelled else { return }
                await self?.stop(reason: "120-minute recording limit")
            }
        } catch {
            var cleanupFailed = false
            if createdSpool {
                do { try await source.stop() } catch { cleanupFailed = true }
                do { try await finishEventStreamAndPendingGaps() } catch { cleanupFailed = true }
                do { try await spoolFactory.discard(recordingID: recordingID) } catch {
                    cleanupFailed = true
                }
            }
            eventContinuation?.finish()
            eventContinuation = nil
            writerTask = nil
            pendingGapWrites = nil
            spool = nil
            let message = cleanupFailed
                ? "Recording could not start; cleanup needs attention"
                : "Recording could not start"
            phase = .needsAttention(recordingID, message)
        }
    }

    func stop() async { await stop(reason: nil) }

    func stop(reason: String?) async {
        guard case let .recording(recordingID) = phase else { return }
        phase = .stopping(recordingID)
        durationLimitTask?.cancel()
        durationLimitTask = nil
        do {
            try await source.stop()
        } catch {
            try? await finishEventStreamAndPendingGaps()
            await abandonActiveSpool(recordingID: recordingID)
            return
        }
        do {
            try await finishEventStreamAndPendingGaps()
            guard fatalCaptureFailure == nil else {
                await abandonActiveSpool(recordingID: recordingID)
                return
            }
            try await spool?.seal(gaps: [])
            spool = nil
            await refreshPendingRecordings()
            if let reason {
                phase = .needsAttention(recordingID, "Stopped safely: \(reason)")
            } else {
                phase = .sealed(recordingID)
            }
        } catch {
            await abandonActiveSpool(recordingID: recordingID)
        }
    }

    func resetSealedState() {
        guard case .sealed = phase else { return }
        phase = .idle
        startedAt = nil
        preflightSnapshot = nil
    }

    func discardPending(recordingID: UUID, confirmed: Bool) async {
        guard confirmed, !phase.isActive else { return }
        do {
            try await spoolFactory.discard(recordingID: recordingID)
            await refreshPendingRecordings()
        } catch {
            phase = .needsAttention(recordingID, "Encrypted spool could not be discarded")
        }
    }

    private func consume(_ event: RecordingCaptureEvent) async {
        switch event {
        case let .chunk(chunk):
            do {
                try await spool?.append(chunk)
                var track = health[chunk.track]
                track.lastSampleEnd = chunk.sampleStart + Int64(chunk.sampleCount)
                health[chunk.track] = track
            } catch {
                if activeStorageFailure == nil { activeStorageFailure = error }
                await failActiveRecording(message: "Encrypted spool write failed")
            }
        case let .gap(gap):
            do {
                try await spool?.record(gap: gap)
                accumulatedGaps.append(gap)
                var track = health[gap.track]
                track.gapCount += 1
                health[gap.track] = track
            } catch {
                if activeStorageFailure == nil { activeStorageFailure = error }
                await failActiveRecording(message: "Encrypted gap write failed")
            }
        case let .level(track, normalized):
            var value = health[track]
            value.normalizedLevel = normalized
            if normalized <= 0.001 {
                value.consecutiveSilentBuffers += 1
                if value.consecutiveSilentBuffers >= 20 { value.warning = .silentInput }
            } else {
                value.consecutiveSilentBuffers = 0
                if value.warning == .silentInput { value.warning = nil }
            }
            health[track] = value
        case let .route(route):
            health.routeDescription = route
        case let .failure(failure):
            for trackKind in RecordingTrackKind.allCases {
                var track = health[trackKind]
                track.warning = failure
                health[trackKind] = track
            }
            if failure == .requiredTracksMissing { fatalCaptureFailure = failure }
            if failure != .callbackOverflow {
                let message = failure == .requiredTracksMissing
                    ? "Recording never received both required audio tracks"
                    : "Capture interrupted"
                await failActiveRecording(message: message)
            }
        }
    }

    private func failActiveRecording(message: String) async {
        guard case let .recording(recordingID) = phase else { return }
        phase = .stopping(recordingID)
        let writer = writerTask
        let sourceStopped: Bool
        do {
            try await source.stop()
            sourceStopped = true
        } catch {
            sourceStopped = false
        }
        eventContinuation?.finish()
        eventContinuation = nil
        durationLimitTask?.cancel()
        durationLimitTask = nil
        Task { [weak self, writer] in
            await writer?.value
            await self?.finishFailedRecording(
                recordingID: recordingID,
                message: message,
                sourceStopped: sourceStopped
            )
        }
    }

    private func finishFailedRecording(
        recordingID: UUID,
        message: String,
        sourceStopped: Bool
    ) async {
        writerTask = nil
        do {
            try await pendingGapWrites?.flush()
            pendingGapWrites = nil
            guard activeStorageFailure == nil else {
                await abandonActiveSpool(recordingID: recordingID)
                return
            }
            guard sourceStopped else {
                await abandonActiveSpool(recordingID: recordingID)
                return
            }
            guard fatalCaptureFailure == nil else {
                await abandonActiveSpool(recordingID: recordingID)
                return
            }
            try await spool?.seal(gaps: [])
            spool = nil
            await refreshPendingRecordings()
            phase = .needsAttention(recordingID, message)
        } catch {
            await abandonActiveSpool(recordingID: recordingID)
        }
    }

    private func finishEventStreamAndPendingGaps() async throws {
        eventContinuation?.finish()
        eventContinuation = nil
        await writerTask?.value
        writerTask = nil
        let writes = pendingGapWrites
        pendingGapWrites = nil
        try await writes?.flush()
        if let activeStorageFailure { throw activeStorageFailure }
    }

    // Drop live handles only after all registered writes have settled. The
    // authenticated state, journal, media files, and key remain for recovery.
    private func abandonActiveSpool(recordingID: UUID) async {
        eventContinuation?.finish()
        eventContinuation = nil
        writerTask = nil
        pendingGapWrites = nil
        spool = nil
        await refreshPendingRecordings()
        phase = .needsAttention(recordingID, "Recording needs recovery")
    }

    private func refreshPendingRecordings() async {
        pendingRecordingIDs = await spoolFactory.pendingRecordingIDs()
    }
}
