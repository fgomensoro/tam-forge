import Foundation

struct AudioQualityThresholds: Sendable, Equatable {
    static let v1 = AudioQualityThresholds(
        minimumDurationSeconds: 1.0,
        silencePeak: 16,
        maximumClippedRatio: 0.01,
        maximumDCOffset: 0.05,
        maximumChannelImbalanceDecibels: 20.0
    )

    let minimumDurationSeconds: Double
    let silencePeak: Int
    let maximumClippedRatio: Double
    let maximumDCOffset: Double
    let maximumChannelImbalanceDecibels: Double
}

// Observable signal conditions only. No calibrated SNR claim; a failed
// threshold marks a dimension unavailable and never lowers a learner score.
struct AudioQualityObservations: Sendable, Equatable {
    static let version = "audio-quality-v1"

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
}

struct AudioQualityAccumulator: Sendable {
    private let sampleRate: Int
    private let channelCount: Int
    private var frameCount: Int64 = 0
    private var sampleSum: Double = 0
    private var sampleCount: Int64 = 0
    private var clippedCount: Int64 = 0
    private var peak = 0
    private var channelEnergy: [Double]
    private var discontinuityCount = 0

    init(sampleRate: Int, channelCount: Int) {
        self.sampleRate = sampleRate
        self.channelCount = channelCount
        channelEnergy = Array(repeating: 0, count: channelCount)
    }

    mutating func observe(chunk: RecordingPCMChunk) {
        frameCount += Int64(chunk.sampleCount)
        chunk.payload.withUnsafeBytes { raw in
            let samples = raw.bindMemory(to: Int16.self)
            for index in samples.indices {
                let value = Int(Int16(littleEndian: samples[index]))
                let magnitude = abs(value)
                if magnitude >= Int(Int16.max) { clippedCount += 1 }
                if magnitude > peak { peak = magnitude }
                sampleSum += Double(value)
                sampleCount += 1
                let scaled = Double(value) / 32_768
                channelEnergy[index % channelCount] += scaled * scaled
            }
        }
    }

    mutating func noteDiscontinuity() { discontinuityCount += 1 }

    func finish(thresholds: AudioQualityThresholds = .v1) -> AudioQualityObservations {
        let duration = Double(frameCount) / Double(sampleRate)
        let clippedRatio = sampleCount == 0 ? 0 : Double(clippedCount) / Double(sampleCount)
        let dcOffset = sampleCount == 0 ? 0 : abs(sampleSum / Double(sampleCount)) / 32_768
        let allSilence = peak <= thresholds.silencePeak
        var imbalance: Double?
        if channelCount == 2 {
            let floor = 1e-12
            let left = max(channelEnergy[0], floor)
            let right = max(channelEnergy[1], floor)
            imbalance = abs(10 * log10(left / right))
        }
        var unavailable: [String] = []
        if duration < thresholds.minimumDurationSeconds { unavailable.append("duration") }
        if allSilence { unavailable.append("silence") }
        if clippedRatio > thresholds.maximumClippedRatio { unavailable.append("clipping") }
        if dcOffset > thresholds.maximumDCOffset { unavailable.append("dc-offset") }
        if let imbalance, imbalance > thresholds.maximumChannelImbalanceDecibels {
            unavailable.append("channel-imbalance")
        }
        return AudioQualityObservations(
            version: Self.version,
            sampleRate: sampleRate,
            channelCount: channelCount,
            sourceSampleCount: frameCount,
            durationSeconds: duration,
            peakAbsolute: peak,
            allSilence: allSilence,
            clippedRatio: clippedRatio,
            dcOffset: dcOffset,
            channelImbalanceDecibels: imbalance,
            discontinuityCount: discontinuityCount,
            unavailableDimensions: unavailable.sorted()
        )
    }

    private static let version = AudioQualityObservations.version
}
