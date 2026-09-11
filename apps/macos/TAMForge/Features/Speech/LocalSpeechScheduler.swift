import Foundation

// One local transcription at a time, and none when the Mac is under pressure.
//
// The whole point of an 8 GB machine running whisper is that a second job
// would not fit. So the scheduler is a queue with a single slot: sealed
// recordings line up in order, one runs, the next starts when it finishes.
// Before a job is admitted the scheduler asks the resource monitor; a memory
// warning or a serious thermal state defers the job (it stays queued, its
// spool stays on disk, nothing is lost), and a critical memory event aborts
// the running job so the model and audio buffers can be released. The spool
// is never touched by any of this: abort means "try again later", never
// "give up".
//
// The scheduler is a value type with no I/O so its rules are unit-tested
// directly; RecordingCoordinator owns one and drives it from real events.

enum MemoryPressureLevel: Sendable, Equatable {
    case nominal
    case warning
    case critical
}

enum ThermalLevel: Sendable, Equatable {
    case nominal
    case fair
    case serious
    case critical

    init(_ state: ProcessInfo.ThermalState) {
        switch state {
        case .nominal: self = .nominal
        case .fair: self = .fair
        case .serious: self = .serious
        case .critical: self = .critical
        @unknown default: self = .serious
        }
    }
}

struct ResourceState: Sendable, Equatable {
    var memory: MemoryPressureLevel = .nominal
    var thermal: ThermalLevel = .nominal

    static let nominal = ResourceState()
}

/// Where the coordinator learns about memory and thermal pressure. The live
/// implementation listens to the kernel; tests push states by hand.
protocol ResourcePressureMonitoring: Sendable {
    func current() -> ResourceState
    func events() -> AsyncStream<ResourceState>
}

/// Engines that can give their owned memory back before the process is under
/// pressure. WhisperTranscriber frees its model context; a fake records the call.
protocol SpeechMemoryReleasing: Sendable {
    func releaseOwnedMemory() async
}

enum SpeechAdmission: Equatable, Sendable {
    case run(UUID)
    case deferred(String)
    case nothingQueued
    case busy
}

struct LocalSpeechScheduler: Equatable, Sendable {
    private(set) var queue: [UUID] = []
    private(set) var running: UUID?

    var isIdle: Bool { running == nil && queue.isEmpty }

    /// Queues a recording once; a recording already queued or running is not
    /// queued again.
    mutating func enqueue(_ recordingID: UUID) {
        guard running != recordingID, !queue.contains(recordingID) else { return }
        queue.append(recordingID)
    }

    /// Why a new job may not start right now, or nil when it may.
    static func deferralReason(for state: ResourceState) -> String? {
        switch (state.memory, state.thermal) {
        case (.critical, _): "Waiting for memory pressure to clear"
        case (.warning, _): "Waiting for memory pressure to clear"
        case (_, .critical), (_, .serious): "Waiting for the Mac to cool down"
        default: nil
        }
    }

    /// Whether a job that is already running must stop now.
    static func mustAbort(under state: ResourceState) -> Bool {
        state.memory == .critical
    }

    /// Admits the next queued recording into the single slot, or says why not.
    mutating func admit(under state: ResourceState) -> SpeechAdmission {
        guard running == nil else { return .busy }
        guard let next = queue.first else { return .nothingQueued }
        if let reason = Self.deferralReason(for: state) { return .deferred(reason) }
        queue.removeFirst()
        running = next
        return .run(next)
    }

    /// The running job ended (finished, failed, or was aborted). An aborted
    /// job goes back to the front of the queue so it is retried first.
    mutating func finish(_ recordingID: UUID, requeue: Bool = false) {
        guard running == recordingID else { return }
        running = nil
        if requeue { queue.insert(recordingID, at: 0) }
    }

    /// Forget a recording entirely (it was discarded).
    mutating func cancel(_ recordingID: UUID) {
        queue.removeAll { $0 == recordingID }
        if running == recordingID { running = nil }
    }
}

/// Kernel memory-pressure events plus ProcessInfo's thermal state.
final class LiveResourcePressureMonitor: ResourcePressureMonitoring, @unchecked Sendable {
    private let lock = NSLock()
    private var memory: MemoryPressureLevel = .nominal
    private let source: DispatchSourceMemoryPressure
    private var continuations: [UUID: AsyncStream<ResourceState>.Continuation] = [:]

    init() {
        source = DispatchSource.makeMemoryPressureSource(
            eventMask: [.normal, .warning, .critical], queue: .global(qos: .utility)
        )
        source.setEventHandler { [weak self] in
            guard let self else { return }
            let mask = self.source.data
            let level: MemoryPressureLevel = mask.contains(.critical)
                ? .critical : mask.contains(.warning) ? .warning : .nominal
            self.update(memory: level)
        }
        source.activate()
        NotificationCenter.default.addObserver(
            forName: ProcessInfo.thermalStateDidChangeNotification, object: nil, queue: nil
        ) { [weak self] _ in
            self?.broadcast()
        }
    }

    deinit { source.cancel() }

    func current() -> ResourceState {
        lock.lock()
        defer { lock.unlock() }
        return ResourceState(memory: memory, thermal: ThermalLevel(ProcessInfo.processInfo.thermalState))
    }

    func events() -> AsyncStream<ResourceState> {
        AsyncStream { continuation in
            let key = UUID()
            lock.lock()
            continuations[key] = continuation
            lock.unlock()
            continuation.onTermination = { [weak self] _ in
                guard let self else { return }
                self.lock.lock()
                self.continuations[key] = nil
                self.lock.unlock()
            }
        }
    }

    private func update(memory level: MemoryPressureLevel) {
        lock.lock()
        memory = level
        lock.unlock()
        broadcast()
    }

    private func broadcast() {
        let state = current()
        lock.lock()
        let targets = Array(continuations.values)
        lock.unlock()
        for continuation in targets { continuation.yield(state) }
    }
}

extension WhisperTranscriber: SpeechMemoryReleasing {
    func releaseOwnedMemory() {
        release()
    }
}
