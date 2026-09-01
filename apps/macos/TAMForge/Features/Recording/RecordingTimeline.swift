import Foundation

struct RecordingTimelineAcceptance: Equatable, Sendable {
    let chunk: RecordingPCMChunk
    let gap: RecordingGap?
}

enum RecordingTimelineError: Error, Equatable {
    case timestampBeforeOrigin
    case overlappingRange
    case invalidDroppedSourceRange
    case arithmeticOverflow
}

struct RecordingTimelineAssembler: Sendable {
    private var originNanoseconds: Int64?
    private var trackEnds: [RecordingTrackKind: Int64] = [:]

    mutating func accept(_ unplacedChunk: RecordingPCMChunk) throws -> RecordingTimelineAcceptance {
        if originNanoseconds == nil { originNanoseconds = unplacedChunk.presentationNanoseconds }
        let sampleStart = try canonicalSampleStart(for: unplacedChunk.presentationNanoseconds)
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

    mutating func accept(droppedSourceRange range: RecordingDroppedSourceRange) throws -> [RecordingGap] {
        guard let interval = RecordingDroppedSourceInterval(range: range) else {
            throw RecordingTimelineError.invalidDroppedSourceRange
        }
        return try accept(droppedSourceInterval: interval)
    }

    // Track cursors advance once to the end of a coalesced dropped source interval.
    // This preserves a pre-existing timestamp hole as source discontinuity and
    // prevents resumed audio from repeating either range.
    mutating func accept(droppedSourceInterval interval: RecordingDroppedSourceInterval) throws -> [RecordingGap] {
        if originNanoseconds == nil { originNanoseconds = interval.startPresentationNanoseconds }
        let sourceStart = try canonicalSampleStart(for: interval.startPresentationNanoseconds)
        let sourceEnd = try canonicalSampleStart(for: interval.endPresentationNanoseconds)
        guard sourceEnd >= sourceStart else { throw RecordingTimelineError.invalidDroppedSourceRange }
        let expectedStart = trackEnds[interval.track, default: 0]
        guard sourceEnd > expectedStart else { return [] }
        var gaps: [RecordingGap] = []
        if expectedStart < sourceStart {
            gaps.append(.init(
                track: interval.track,
                sampleStart: expectedStart,
                sampleCount: try boundedSampleCount(from: expectedStart, to: sourceStart),
                reason: .sourceDiscontinuity
            ))
        }
        let callbackStart = Swift.max(expectedStart, sourceStart)
        if callbackStart < sourceEnd {
            gaps.append(.init(
                track: interval.track,
                sampleStart: callbackStart,
                sampleCount: try boundedSampleCount(from: callbackStart, to: sourceEnd),
                reason: .callbackOverflow
            ))
        }
        trackEnds[interval.track] = sourceEnd
        return gaps
    }

    private func canonicalSampleStart(for presentationNanoseconds: Int64) throws -> Int64 {
        guard let originNanoseconds else { throw RecordingTimelineError.arithmeticOverflow }
        let delta = presentationNanoseconds - originNanoseconds
        guard delta >= 0 else { throw RecordingTimelineError.timestampBeforeOrigin }
        let (scaled, overflow) = delta.multipliedReportingOverflow(
            by: Int64(RecordingPCMFormat.canonicalSampleRate)
        )
        guard !overflow else { throw RecordingTimelineError.arithmeticOverflow }
        return scaled / 1_000_000_000
    }

    private func boundedSampleCount(from start: Int64, to end: Int64) throws -> Int {
        let (count, overflow) = end.subtractingReportingOverflow(start)
        guard !overflow, let boundedCount = Int(exactly: count) else {
            throw RecordingTimelineError.arithmeticOverflow
        }
        return boundedCount
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
