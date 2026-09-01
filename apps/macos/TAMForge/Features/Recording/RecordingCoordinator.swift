import AppKit
import Combine
import Foundation

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
    private var lifecycleTask: Task<Void, Never>?
    private var durationLimitTask: Task<Void, Never>?
    private var accumulatedGaps: [RecordingGap] = []

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
        let result = await preflight.run()
        guard case let .ready(snapshot) = result else {
            if case let .blocked(failure) = result { phase = .blocked(failure) }
            return
        }
        preflightSnapshot = snapshot
        health.routeDescription = snapshot.routeDescription

        let recordingID = UUID()
        do {
            let spool = try await spoolFactory.create(recordingID: recordingID)
            self.spool = spool
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
                receive: { [spool] event in
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
                    if let gap { Task { await spool.record(gap: gap) } }
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
            eventContinuation?.finish()
            eventContinuation = nil
            writerTask?.cancel()
            writerTask = nil
            phase = .needsAttention(recordingID, "Recording could not start")
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
            eventContinuation?.finish()
            eventContinuation = nil
            await writerTask?.value
            writerTask = nil
            try await spool?.seal(gaps: [])
            spool = nil
            await refreshPendingRecordings()
            if let reason {
                phase = .needsAttention(recordingID, "Stopped safely: \(reason)")
            } else {
                phase = .sealed(recordingID)
            }
        } catch {
            phase = .needsAttention(recordingID, "Recording needs recovery")
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
                await failActiveRecording(message: "Encrypted spool write failed")
            }
        case let .gap(gap):
            accumulatedGaps.append(gap)
            await spool?.record(gap: gap)
            var track = health[gap.track]
            track.gapCount += 1
            health[gap.track] = track
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
            if failure != .callbackOverflow { await failActiveRecording(message: "Capture interrupted") }
        }
    }

    private func failActiveRecording(message: String) async {
        guard case let .recording(recordingID) = phase else { return }
        try? await source.stop()
        eventContinuation?.finish()
        eventContinuation = nil
        writerTask?.cancel()
        writerTask = nil
        durationLimitTask?.cancel()
        durationLimitTask = nil
        try? await spool?.seal(gaps: [])
        spool = nil
        phase = .needsAttention(recordingID, message)
    }

    private func refreshPendingRecordings() async {
        pendingRecordingIDs = await spoolFactory.pendingRecordingIDs()
    }
}
