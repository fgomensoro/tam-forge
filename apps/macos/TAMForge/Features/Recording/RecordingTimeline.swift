import Foundation

struct RecordingTimelineAcceptance: Equatable, Sendable {
    let chunk: RecordingPCMChunk
    let gap: RecordingGap?
}

enum RecordingTimelineError: Error, Equatable {
    case timestampBeforeOrigin
    case overlappingRange
    case arithmeticOverflow
}

struct RecordingTimelineAssembler: Sendable {
    private var originNanoseconds: Int64?
    private var trackEnds: [RecordingTrackKind: Int64] = [:]

    mutating func accept(_ unplacedChunk: RecordingPCMChunk) throws -> RecordingTimelineAcceptance {
        if originNanoseconds == nil { originNanoseconds = unplacedChunk.presentationNanoseconds }
        guard let originNanoseconds else { throw RecordingTimelineError.arithmeticOverflow }
        let delta = unplacedChunk.presentationNanoseconds - originNanoseconds
        guard delta >= 0 else { throw RecordingTimelineError.timestampBeforeOrigin }
        let (scaled, overflow) = delta.multipliedReportingOverflow(
            by: Int64(RecordingPCMFormat.canonicalSampleRate)
        )
        guard !overflow else { throw RecordingTimelineError.arithmeticOverflow }
        let sampleStart = scaled / 1_000_000_000
        let expectedStart = trackEnds[unplacedChunk.track, default: 0]
        guard sampleStart >= expectedStart else { throw RecordingTimelineError.overlappingRange }

        var chunk = unplacedChunk
        chunk.sampleStart = sampleStart
        _ = try chunk.validated()
        let gap: RecordingGap? = sampleStart == expectedStart ? nil : .init(
            track: chunk.track,
            sampleStart: expectedStart,
            sampleCount: Int(sampleStart - expectedStart),
            reason: .sourceDiscontinuity
        )
        let (end, endOverflow) = sampleStart.addingReportingOverflow(Int64(chunk.sampleCount))
        guard !endOverflow else { throw RecordingTimelineError.arithmeticOverflow }
        trackEnds[chunk.track] = end
        return .init(chunk: chunk, gap: gap)
    }
}

final class BoundedCaptureQueue<Element: Sendable>: @unchecked Sendable {
    private let lock = NSLock()
    private let capacity: Int
    private var elements: [Element] = []

    init(capacity: Int) {
        precondition(capacity > 0)
        self.capacity = capacity
        elements.reserveCapacity(capacity)
    }

    @discardableResult
    func offer(_ element: Element) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard elements.count < capacity else { return false }
        elements.append(element)
        return true
    }

    func drain() -> [Element] {
        lock.lock()
        defer { lock.unlock() }
        let drained = elements
        elements.removeAll(keepingCapacity: true)
        return drained
    }
}
