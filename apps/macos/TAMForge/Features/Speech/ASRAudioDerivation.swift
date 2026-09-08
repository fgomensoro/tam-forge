import CryptoKit
import Foundation

enum ASRDerivationVersion {
    static let current = "tamforge-asr16k-v1"
}

enum ASRDerivationError: Error, Equatable {
    case unsupportedFormat
    case chunkOutOfOrder(expected: Int64, actual: Int64)
    case trackMismatch
}

struct ASRDerivationLineage: Sendable, Equatable {
    let recordingID: UUID
    let track: RecordingTrackKind
    let derivationVersion: String
    let sourceSampleRate: Int
    let sourceChannelCount: Int
    let sourceSampleCount: Int64
    let outputSampleRate: Int
    let outputSampleCount: Int64
    let zeroFilledGaps: [RecordingGap]
    let sourcePCMSHA256: String
    let derivedPCMSHA256: String
    let quality: AudioQualityObservations
}

struct ASRDerivedBlock: Sendable, Equatable {
    let outputSampleStart: Int64
    let samples: [Int16]
}

// Fixed (L+R)/2 downmix, then a linear-phase Kaiser-windowed-sinc low-pass
// and 3:1 decimation. Output sample n is aligned to source sample 3n by
// compensating the filter's group delay, so ASR timestamps map back exactly.
//
// `history` holds the mono source samples not yet fully consumed, padded at
// both ends with half a filter width of zeros. The invariant is:
// `history[i]` is source sample `historyStartSourceIndex + i` (negative
// indices before real audio starts, or past `expectedSampleStart` once
// `finish()` pads the tail). Output n needs the symmetric window
// `[3n - half, 3n + half]`, i.e. history indices
// `[3n - historyStartSourceIndex - half, 3n - historyStartSourceIndex + half]`.
final class ASRAudioDeriver {
    static let sourceSampleRate = 48_000
    static let outputSampleRate = 16_000
    private static let decimation: Int64 = 3
    private static let taps = 95
    private static let half = Int64((taps - 1) / 2)
    private static let coefficients: [Double] = makeCoefficients()

    private let recordingID: UUID
    private let track: RecordingTrackKind
    private let channelCount: Int
    private var expectedSampleStart: Int64 = 0
    private var history: [Double] = []
    private var historyStartSourceIndex: Int64
    private var outputCount: Int64 = 0
    private var zeroFilledGaps: [RecordingGap] = []
    private var quality: AudioQualityAccumulator
    private var sourceHasher = SHA256()
    private var derivedHasher = SHA256()

    init(recordingID: UUID, track: RecordingTrackKind) {
        self.recordingID = recordingID
        self.track = track
        channelCount = track == .microphone ? 1 : 2
        quality = AudioQualityAccumulator(sampleRate: Self.sourceSampleRate, channelCount: channelCount)
        // Pre-fill half a filter of silence so output sample 0 is centred on source sample 0.
        history = Array(repeating: 0, count: Int(Self.half))
        historyStartSourceIndex = -Self.half
    }

    func append(_ chunk: RecordingPCMChunk) throws -> ASRDerivedBlock? {
        guard chunk.track == track else { throw ASRDerivationError.trackMismatch }
        guard chunk.format.sampleRate == Self.sourceSampleRate,
              chunk.format.channelCount == channelCount,
              chunk.format.sampleEncoding == "pcm_s16le"
        else { throw ASRDerivationError.unsupportedFormat }
        guard chunk.sampleStart >= expectedSampleStart else {
            throw ASRDerivationError.chunkOutOfOrder(expected: expectedSampleStart, actual: chunk.sampleStart)
        }
        if chunk.sampleStart > expectedSampleStart {
            let missing = Int(chunk.sampleStart - expectedSampleStart)
            zeroFilledGaps.append(.init(track: track, sampleStart: expectedSampleStart, sampleCount: missing, reason: .missingAudio))
            quality.noteDiscontinuity()
            history.append(contentsOf: repeatElement(0, count: missing))
            sourceHasher.update(data: Data(count: missing * channelCount * 2))
        }
        quality.observe(chunk: chunk)
        sourceHasher.update(data: chunk.payload)
        chunk.payload.withUnsafeBytes { raw in
            let samples = raw.bindMemory(to: Int16.self)
            var frame = 0
            while frame < chunk.sampleCount {
                var sum = 0.0
                for channel in 0..<channelCount {
                    sum += Double(Int16(littleEndian: samples[frame * channelCount + channel]))
                }
                history.append(sum / Double(channelCount))
                frame += 1
            }
        }
        expectedSampleStart = chunk.sampleStart + Int64(chunk.sampleCount)
        return drain(flush: false)
    }

    func finish() -> (block: ASRDerivedBlock?, lineage: ASRDerivationLineage) {
        // Pad with the other half filter so the last real samples get a full window.
        history.append(contentsOf: repeatElement(0, count: Int(Self.half)))
        let block = drain(flush: true)
        let lineage = ASRDerivationLineage(
            recordingID: recordingID,
            track: track,
            derivationVersion: ASRDerivationVersion.current,
            sourceSampleRate: Self.sourceSampleRate,
            sourceChannelCount: channelCount,
            sourceSampleCount: expectedSampleStart,
            outputSampleRate: Self.outputSampleRate,
            outputSampleCount: outputCount,
            zeroFilledGaps: zeroFilledGaps,
            sourcePCMSHA256: Self.hex(sourceHasher.finalize()),
            derivedPCMSHA256: Self.hex(derivedHasher.finalize()),
            quality: quality.finish()
        )
        return (block, lineage)
    }

    // Emits every output sample whose full, symmetric filter window
    // `[3n - half, 3n + half]` is already present in `history`. When
    // flushing, stops exactly at `ceil(expectedSampleStart / 3)` outputs so
    // no sample past the real (gap-inclusive) source stream is invented.
    // After producing, trims every history element whose source index is
    // strictly below what the *next* output's window could ever need
    // (`3 * outputCount - half`), which keeps `historyStartSourceIndex`
    // consistent with the `history[i]` invariant documented on the type.
    private func drain(flush: Bool) -> ASRDerivedBlock? {
        let half = Self.half
        let totalOutputs: Int64 = flush
            ? (expectedSampleStart + Self.decimation - 1) / Self.decimation
            : Int64.max
        var produced: [Int16] = []
        let start = outputCount
        while outputCount < totalOutputs {
            let centre = outputCount * Self.decimation - historyStartSourceIndex
            let windowEnd = centre + half
            guard windowEnd < Int64(history.count) else { break }
            var accumulator = 0.0
            for tap in 0..<Self.taps {
                let offset = Int64(tap) - half
                accumulator += Self.coefficients[tap] * history[Int(centre + offset)]
            }
            let rounded = accumulator.rounded(.toNearestOrEven)
            produced.append(Int16(clamping: Int(rounded)))
            outputCount += 1
        }
        // Drop history that no future output window can reach.
        let nextNeededSourceIndex = outputCount * Self.decimation - half
        let trim = min(Int64(history.count), max(0, nextNeededSourceIndex - historyStartSourceIndex))
        if trim > 0 {
            history.removeFirst(Int(trim))
            historyStartSourceIndex += trim
        }
        guard !produced.isEmpty else { return nil }
        var bytes = Data(capacity: produced.count * 2)
        for sample in produced { withUnsafeBytes(of: sample.littleEndian) { bytes.append(contentsOf: $0) } }
        derivedHasher.update(data: bytes)
        return ASRDerivedBlock(outputSampleStart: start, samples: produced)
    }

    private static func makeCoefficients() -> [Double] {
        let cutoff = 7_000.0 / Double(sourceSampleRate)   // normalised (cycles/sample)
        let beta = 6.0
        let middle = Double(taps - 1) / 2
        var raw = (0..<taps).map { index -> Double in
            let n = Double(index) - middle
            let sinc = n == 0 ? 2 * cutoff : sin(2 * .pi * cutoff * n) / (.pi * n)
            let ratio = 2 * n / Double(taps - 1)
            let window = besselI0(beta * (1 - ratio * ratio).squareRoot()) / besselI0(beta)
            return sinc * window
        }
        let gain = raw.reduce(0, +)
        raw = raw.map { $0 / gain }
        return raw
    }

    private static func besselI0(_ x: Double) -> Double {
        var sum = 1.0, term = 1.0
        let half = x / 2
        var k = 1.0
        while term > 1e-12 * sum {
            term *= (half / k) * (half / k)
            sum += term
            k += 1
        }
        return sum
    }

    private static func hex(_ digest: SHA256.Digest) -> String {
        digest.map { String(format: "%02x", $0) }.joined()
    }
}
