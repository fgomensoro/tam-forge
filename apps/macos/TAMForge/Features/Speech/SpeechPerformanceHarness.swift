import Darwin
import Foundation

// The 8 GB memory gates from the native redesign spec (section 7.3) as data,
// plus the pure arithmetic that turns a series of footprint samples into a
// verdict. Nothing here touches whisper or the spool: the measured run lives
// in SpeechPerformanceHarnessTests (opt-in, needs the pinned model) and only
// feeds numbers in, so the verdict logic itself is covered by ordinary CI
// unit tests and can never drift from the artifact it renders.

enum ProcessMemory {
    /// The physical footprint the kernel charges to this process, the same
    /// number Activity Monitor and `footprint(1)` report. Zero when the
    /// kernel refuses the query, which the caller must treat as "unmeasured",
    /// never as "no memory".
    static func physicalFootprintBytes() -> UInt64 {
        // libproc's `rusage_info_t *` parameter is really a pointer to the
        // struct itself (the typedef is `void *`), so the struct's own address
        // is rebound rather than passing a pointer to a pointer.
        var info = rusage_info_v4()
        let status = withUnsafeMutablePointer(to: &info) { pointer -> Int32 in
            pointer.withMemoryRebound(to: rusage_info_t?.self, capacity: 1) {
                proc_pid_rusage(getpid(), RUSAGE_INFO_V4, $0)
            }
        }
        return status == 0 ? info.ri_phys_footprint : 0
    }

    /// Asks malloc to hand freed pages back to the kernel. Large freed blocks
    /// stay charged to the footprint until malloc decides to return them;
    /// this makes that decision now, so a measurement after it shows what the
    /// process still owns rather than what malloc is keeping warm.
    static func returnFreedPages() {
        malloc_zone_pressure_relief(nil, 0)
    }
}

struct MemorySample: Codable, Equatable, Sendable {
    let audioSeconds: Double
    let footprintBytes: UInt64
}

/// Section 7.3 initial gates, in bytes. Release gates, not promises about
/// undocumented macOS cache behaviour.
struct SpeechPerformanceGates: Codable, Equatable, Sendable {
    static let mebibyte: UInt64 = 1_048_576

    let recordingP95Bytes: UInt64
    let transcriptionPeakBytes: UInt64
    let cleanupReturnWithinBytes: UInt64
    let cleanupReturnWithinSeconds: Double
    /// Below this the growth is noise, not a leak: 60 minutes at this slope is
    /// under one 4 KiB page per audio second.
    let maximumGrowthBytesPerAudioMinute: Double

    static let initial = SpeechPerformanceGates(
        recordingP95Bytes: 300 * mebibyte,
        transcriptionPeakBytes: 1_536 * mebibyte,
        cleanupReturnWithinBytes: 100 * mebibyte,
        cleanupReturnWithinSeconds: 30,
        maximumGrowthBytesPerAudioMinute: 256 * 1_024
    )
}

/// Least-squares fit of footprint against audio duration. The slope is the
/// number that catches duration-linked growth: a leak proportional to the
/// audio recorded shows up as a positive slope no matter how the samples
/// jitter around it.
struct MemoryGrowthAnalysis: Codable, Equatable, Sendable {
    let sampleCount: Int
    let baselineBytes: UInt64
    let p95Bytes: UInt64
    let peakBytes: UInt64
    let slopeBytesPerAudioMinute: Double

    init(baselineBytes: UInt64, samples: [MemorySample]) {
        self.baselineBytes = baselineBytes
        sampleCount = samples.count
        let sorted = samples.map(\.footprintBytes).sorted()
        peakBytes = sorted.last ?? baselineBytes
        p95Bytes = Self.percentile95(sorted) ?? baselineBytes
        slopeBytesPerAudioMinute = Self.slope(samples) * 60
    }

    func exceedsGrowth(_ gates: SpeechPerformanceGates) -> Bool {
        slopeBytesPerAudioMinute > gates.maximumGrowthBytesPerAudioMinute
    }

    /// Nearest-rank 95th percentile over an ascending series.
    static func percentile95(_ ascending: [UInt64]) -> UInt64? {
        guard !ascending.isEmpty else { return nil }
        let rank = Int((0.95 * Double(ascending.count)).rounded(.up))
        return ascending[max(0, min(ascending.count - 1, rank - 1))]
    }

    /// Bytes per audio second. Fewer than two distinct x values give no slope.
    static func slope(_ samples: [MemorySample]) -> Double {
        guard samples.count >= 2 else { return 0 }
        let n = Double(samples.count)
        let meanX = samples.reduce(0) { $0 + $1.audioSeconds } / n
        let meanY = samples.reduce(0.0) { $0 + Double($1.footprintBytes) } / n
        var numerator = 0.0
        var denominator = 0.0
        for sample in samples {
            let dx = sample.audioSeconds - meanX
            numerator += dx * (Double(sample.footprintBytes) - meanY)
            denominator += dx * dx
        }
        return denominator == 0 ? 0 : numerator / denominator
    }
}

/// Two transcriptions of the same audio submitted at once. The engine is an
/// actor whose transcribe body never suspends, so the pair must take about
/// the sum of two solo runs, not the maximum. `serialized` is the observed
/// fact; the ratio is kept so a reader can judge the margin.
struct OneJobObservation: Codable, Equatable, Sendable {
    let soloSeconds: Double
    let concurrentPairSeconds: Double

    var ratio: Double { soloSeconds > 0 ? concurrentPairSeconds / soloSeconds : 0 }
    /// Parallel execution would land near 1.0; a serialized pair near 2.0.
    var serialized: Bool { ratio >= 1.6 }
}

struct CleanupObservation: Codable, Equatable, Sendable {
    /// Footprint immediately before the transcription job, the number the
    /// spec's cleanup gate is relative to.
    let baselineBytes: UInt64
    let settledBytes: UInt64
    let settledAfterSeconds: Double
    /// Footprint after the settle window once malloc was asked to return
    /// freed pages; the gap to `settledBytes` is memory malloc kept warm,
    /// not memory the job still owned.
    let afterReturningFreedPagesBytes: UInt64
    /// What the first job in the process left behind after its own release:
    /// the runtime's one-time cost (Metal library, pipelines, ggml device
    /// context), measured by a warm-up job so it is reported, not hidden in
    /// the gate.
    let runtimeResidualBytes: Int64

    var deltaFromBaselineBytes: Int64 { Int64(settledBytes) - Int64(baselineBytes) }

    var deltaAfterReturningFreedPagesBytes: Int64 {
        Int64(afterReturningFreedPagesBytes) - Int64(baselineBytes)
    }

    /// The gate is judged on what the process owns after freed pages are
    /// returned, inside the time budget.
    func returned(within gates: SpeechPerformanceGates) -> Bool {
        settledAfterSeconds <= gates.cleanupReturnWithinSeconds
            && min(deltaFromBaselineBytes, deltaAfterReturningFreedPagesBytes)
                <= Int64(gates.cleanupReturnWithinBytes)
    }
}

struct SpeechPerformanceReport: Codable, Equatable, Sendable {
    struct Machine: Codable, Equatable, Sendable {
        let profile: String
        let chip: String
        let memoryBytes: UInt64
        let osVersion: String
    }

    struct Verdicts: Codable, Equatable, Sendable {
        let recordingP95WithinGate: Bool
        let noDurationLinkedGrowth: Bool
        let transcriptionPeakWithinGate: Bool
        let oneJobAtATime: Bool
        let cleanupReturnedToBaseline: Bool

        var allPassed: Bool {
            recordingP95WithinGate && noDurationLinkedGrowth && transcriptionPeakWithinGate
                && oneJobAtATime && cleanupReturnedToBaseline
        }
    }

    let schemaVersion: Int
    let recordedAt: String
    let audioMinutes: Int
    let audioSource: String
    let machine: Machine
    let gates: SpeechPerformanceGates
    let recording: MemoryGrowthAnalysis
    let recordingSamples: [MemorySample]
    let transcriptionPeakBytes: UInt64
    let transcriptionSeconds: Double
    let oneJob: OneJobObservation
    let cleanup: CleanupObservation
    let verdicts: Verdicts

    init(
        recordedAt: Date,
        audioMinutes: Int,
        audioSource: String,
        machine: Machine,
        gates: SpeechPerformanceGates,
        recording: MemoryGrowthAnalysis,
        recordingSamples: [MemorySample],
        transcriptionPeakBytes: UInt64,
        transcriptionSeconds: Double,
        oneJob: OneJobObservation,
        cleanup: CleanupObservation
    ) {
        schemaVersion = 1
        self.recordedAt = ISO8601DateFormatter().string(from: recordedAt)
        self.audioMinutes = audioMinutes
        self.audioSource = audioSource
        self.machine = machine
        self.gates = gates
        self.recording = recording
        self.recordingSamples = recordingSamples
        self.transcriptionPeakBytes = transcriptionPeakBytes
        self.transcriptionSeconds = transcriptionSeconds
        self.oneJob = oneJob
        self.cleanup = cleanup
        verdicts = Verdicts(
            recordingP95WithinGate: recording.p95Bytes <= gates.recordingP95Bytes,
            noDurationLinkedGrowth: !recording.exceedsGrowth(gates),
            transcriptionPeakWithinGate: transcriptionPeakBytes <= gates.transcriptionPeakBytes,
            oneJobAtATime: oneJob.serialized,
            cleanupReturnedToBaseline: cleanup.returned(within: gates)
        )
    }

    /// Sorted keys so two runs diff line by line.
    func render() throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        return try encoder.encode(self)
    }

    static func currentMachine() -> Machine {
        var size = 0
        sysctlbyname("machdep.cpu.brand_string", nil, &size, nil, 0)
        var buffer = [CChar](repeating: 0, count: max(size, 1))
        sysctlbyname("machdep.cpu.brand_string", &buffer, &size, nil, 0)
        let chip = String(cString: buffer)
        let memory = ProcessInfo.processInfo.physicalMemory
        let version = ProcessInfo.processInfo.operatingSystemVersion
        let os = "\(version.majorVersion).\(version.minorVersion).\(version.patchVersion)"
        let slug = chip.lowercased().replacingOccurrences(of: " ", with: "-")
        let gib = memory / 1_073_741_824
        return Machine(
            profile: "\(slug)-\(gib)gb-macos-\(os.replacingOccurrences(of: ".", with: "-"))",
            chip: chip,
            memoryBytes: memory,
            osVersion: os
        )
    }
}
