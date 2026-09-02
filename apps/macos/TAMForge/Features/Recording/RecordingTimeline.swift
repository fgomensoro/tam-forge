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

    mutating func accept(
        droppedSourceRange range: RecordingDroppedSourceRange,
        reason: RecordingGapReason = .callbackOverflow
    ) throws -> [RecordingGap] {
        guard let interval = RecordingDroppedSourceInterval(range: range) else {
            throw RecordingTimelineError.invalidDroppedSourceRange
        }
        return try accept(droppedSourceInterval: interval, reason: reason)
    }

    // Track cursors advance once to the end of a coalesced dropped source interval.
    // This preserves a pre-existing timestamp hole as source discontinuity and
    // prevents resumed audio from repeating either range.
    mutating func accept(
        droppedSourceInterval interval: RecordingDroppedSourceInterval,
        reason: RecordingGapReason = .callbackOverflow
    ) throws -> [RecordingGap] {
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
                reason: reason
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

struct RecordingCapturePipeline: Sendable {
    // Startup keeps at most one canonical second of audio, one second of
    // presentation span, and a fixed event count per track while waiting for
    // both required tracks to provide a timeline anchor.
    private static let maximumStartupAudioSamplesPerTrack = RecordingPCMFormat.canonicalSampleRate
    private static let maximumStartupSpanNanoseconds: Int64 = 1_000_000_000
    private static let maximumStartupInputsPerTrack = 256

    private var timeline = RecordingTimelineAssembler()
    private var accumulator = RecordingChunkAccumulator()
    private var levelThrottle = RecordingLevelThrottle()
    // nil means both anchors arrived and the gate is open.
    private var startupInputs: [StartupInput]? = []
    private var startupUsageByTrack: [RecordingTrackKind: StartupTrackUsage] = [:]
    private var startupFailed = false

    mutating func accept(
        _ chunk: RecordingPCMChunk,
        normalizedLevel: Double
    ) throws -> [RecordingCaptureEvent] {
        try gated(
            .chunk(chunk, normalizedLevel: normalizedLevel),
            track: chunk.track,
            anchor: chunk.presentationNanoseconds,
            audioSamples: chunk.sampleCount
        )
    }

    mutating func acceptDroppedSourceInterval(
        _ interval: RecordingDroppedSourceInterval,
        reason: RecordingGapReason
    ) throws -> [RecordingCaptureEvent] {
        try gated(
            .droppedInterval(interval, reason: reason),
            track: interval.track,
            anchor: interval.startPresentationNanoseconds,
            audioSamples: 0
        )
    }

    mutating func acceptFailure(
        droppedSourceRange range: RecordingDroppedSourceRange,
        reason: RecordingGapReason,
        failure: RecordingCaptureFailure
    ) throws -> [RecordingCaptureEvent] {
        guard let interval = RecordingDroppedSourceInterval(range: range) else {
            throw RecordingTimelineError.invalidDroppedSourceRange
        }
        return try acceptFailure(
            droppedSourceInterval: interval, reason: reason, failure: failure
        )
    }

    mutating func acceptFailure(
        droppedSourceInterval interval: RecordingDroppedSourceInterval,
        reason: RecordingGapReason,
        failure: RecordingCaptureFailure
    ) throws -> [RecordingCaptureEvent] {
        try gated(
            .failure(interval, reason: reason, failure: failure),
            track: interval.track,
            anchor: interval.startPresentationNanoseconds,
            audioSamples: 0
        )
    }

    mutating func finish() -> [RecordingCaptureEvent] {
        guard !startupFailed else { return [] }
        guard startupInputs == nil else {
            failStartup()
            return [.failure(.requiredTracksMissing)]
        }
        return accumulator.finish().map { .chunk($0) }
    }

    private enum StartupInputKind {
        case chunk(RecordingPCMChunk, normalizedLevel: Double)
        case droppedInterval(RecordingDroppedSourceInterval, reason: RecordingGapReason)
        case failure(
            RecordingDroppedSourceInterval,
            reason: RecordingGapReason,
            failure: RecordingCaptureFailure
        )
    }

    private struct StartupInput {
        let anchor: Int64
        let insertionIndex: Int
        let kind: StartupInputKind
    }

    private struct StartupTrackUsage {
        var inputCount = 0
        var audioSamples = 0
        var minimumAnchor: Int64
        var maximumAnchor: Int64
    }

    private mutating func gated(
        _ kind: StartupInputKind,
        track: RecordingTrackKind,
        anchor: Int64,
        audioSamples: Int
    ) throws -> [RecordingCaptureEvent] {
        guard !startupFailed else { return [] }
        guard var inputs = startupInputs else {
            return try process(kind)
        }
        var usage = startupUsageByTrack[track]
            ?? StartupTrackUsage(minimumAnchor: anchor, maximumAnchor: anchor)
        usage.minimumAnchor = Swift.min(usage.minimumAnchor, anchor)
        usage.maximumAnchor = Swift.max(usage.maximumAnchor, anchor)
        usage.inputCount += 1
        usage.audioSamples += audioSamples
        let (span, spanOverflow) = usage.maximumAnchor
            .subtractingReportingOverflow(usage.minimumAnchor)
        guard !spanOverflow,
              span <= Self.maximumStartupSpanNanoseconds,
              usage.inputCount <= Self.maximumStartupInputsPerTrack,
              usage.audioSamples <= Self.maximumStartupAudioSamplesPerTrack
        else {
            failStartup()
            return [.failure(.requiredTracksMissing)]
        }
        inputs.append(.init(anchor: anchor, insertionIndex: inputs.count, kind: kind))
        startupUsageByTrack[track] = usage
        guard startupUsageByTrack.count == RecordingTrackKind.allCases.count else {
            startupInputs = inputs
            return []
        }
        // Both tracks anchored: the minimum buffered anchor replayed first
        // initializes the shared origin independent of callback order.
        startupInputs = nil
        startupUsageByTrack = [:]
        let ordered = inputs.sorted {
            if $0.anchor != $1.anchor { return $0.anchor < $1.anchor }
            return $0.insertionIndex < $1.insertionIndex
        }
        var events: [RecordingCaptureEvent] = []
        for input in ordered {
            events.append(contentsOf: try process(input.kind))
        }
        return events
    }

    private mutating func failStartup() {
        startupFailed = true
        startupInputs = nil
        startupUsageByTrack = [:]
    }

    private mutating func process(
        _ kind: StartupInputKind
    ) throws -> [RecordingCaptureEvent] {
        switch kind {
        case let .chunk(chunk, normalizedLevel):
            return try process(chunk, normalizedLevel: normalizedLevel)
        case let .droppedInterval(interval, reason):
            return try process(droppedSourceInterval: interval, reason: reason)
        case let .failure(interval, reason, failure):
            var events = try process(droppedSourceInterval: interval, reason: reason)
            events.append(.failure(failure))
            return events
        }
    }

    private mutating func process(
        _ chunk: RecordingPCMChunk,
        normalizedLevel: Double
    ) throws -> [RecordingCaptureEvent] {
        let accepted = try timeline.accept(chunk)
        var events: [RecordingCaptureEvent] = []
        if let gap = accepted.gap {
            events.append(contentsOf: accumulator.flush(track: chunk.track).map {
                .chunk($0)
            })
            events.append(.gap(gap))
        }
        events.append(contentsOf: try accumulator.accept(accepted.chunk).map {
            .chunk($0)
        })
        if levelThrottle.shouldEmit(for: accepted.chunk) {
            events.append(.level(track: chunk.track, normalized: normalizedLevel))
        }
        return events
    }

    private mutating func process(
        droppedSourceInterval interval: RecordingDroppedSourceInterval,
        reason: RecordingGapReason
    ) throws -> [RecordingCaptureEvent] {
        var events = accumulator.flush(track: interval.track).map {
            RecordingCaptureEvent.chunk($0)
        }
        events.append(contentsOf: try timeline.accept(
            droppedSourceInterval: interval, reason: reason
        ).map { .gap($0) })
        return events
    }
}

private struct RecordingChunkAccumulator: Sendable {
    private var pendingByTrack: [RecordingTrackKind: RecordingPCMChunk] = [:]

    mutating func accept(_ unvalidatedChunk: RecordingPCMChunk) throws -> [RecordingPCMChunk] {
        let chunk = try unvalidatedChunk.validated()
        var emitted: [RecordingPCMChunk] = []
        if let pending = pendingByTrack[chunk.track], !canMerge(pending, chunk) {
            emitted.append(pending)
            pendingByTrack[chunk.track] = nil
        }
        if let pending = pendingByTrack[chunk.track] {
            pendingByTrack[chunk.track] = try merge(pending, chunk)
        } else {
            pendingByTrack[chunk.track] = chunk
        }
        while let pending = pendingByTrack[chunk.track],
              pending.sampleCount >= RecordingPCMFormat.canonicalSampleRate {
            let count = RecordingPCMFormat.canonicalSampleRate
            emitted.append(try slice(pending, offset: 0, count: count))
            if pending.sampleCount == count {
                pendingByTrack[chunk.track] = nil
            } else {
                pendingByTrack[chunk.track] = try slice(
                    pending, offset: count, count: pending.sampleCount - count
                )
            }
        }
        return emitted
    }

    mutating func flush(track: RecordingTrackKind) -> [RecordingPCMChunk] {
        guard let pending = pendingByTrack.removeValue(forKey: track) else { return [] }
        return [pending]
    }

    mutating func finish() -> [RecordingPCMChunk] {
        let pending = pendingByTrack.values.sorted {
            if $0.sampleStart != $1.sampleStart { return $0.sampleStart < $1.sampleStart }
            return $0.track.rawValue < $1.track.rawValue
        }
        pendingByTrack.removeAll(keepingCapacity: true)
        return pending
    }

    private func canMerge(_ current: RecordingPCMChunk, _ next: RecordingPCMChunk) -> Bool {
        let (currentEnd, overflow) = current.sampleStart.addingReportingOverflow(
            Int64(current.sampleCount)
        )
        return !overflow
            && current.track == next.track
            && currentEnd == next.sampleStart
            && current.format == next.format
            && current.source.sampleRate == next.source.sampleRate
            && current.source.channelCount == next.source.channelCount
            && current.source.deviceID == next.source.deviceID
            && current.source.initialRoute == next.source.initialRoute
            && current.source.conversionVersion == next.source.conversionVersion
    }

    private func merge(
        _ current: RecordingPCMChunk,
        _ next: RecordingPCMChunk
    ) throws -> RecordingPCMChunk {
        let (sampleCount, overflow) = current.sampleCount.addingReportingOverflow(next.sampleCount)
        guard !overflow else { throw RecordingTimelineError.arithmeticOverflow }
        var payload = current.payload
        payload.append(next.payload)
        return .init(
            track: current.track,
            presentationNanoseconds: current.presentationNanoseconds,
            sampleStart: current.sampleStart,
            sampleCount: sampleCount,
            format: current.format,
            source: current.source,
            payload: payload
        )
    }

    private func slice(
        _ chunk: RecordingPCMChunk,
        offset: Int,
        count: Int
    ) throws -> RecordingPCMChunk {
        let bytesPerFrame = chunk.format.channelCount * RecordingPCMFormat.bytesPerSample
        let byteStart = offset * bytesPerFrame
        let byteEnd = byteStart + count * bytesPerFrame
        let (scaledOffset, scaledOverflow) = Int64(offset).multipliedReportingOverflow(
            by: 1_000_000_000
        )
        guard !scaledOverflow else { throw RecordingTimelineError.arithmeticOverflow }
        let nanosecondOffset = scaledOffset / Int64(RecordingPCMFormat.canonicalSampleRate)
        let (presentation, presentationOverflow) = chunk.presentationNanoseconds
            .addingReportingOverflow(nanosecondOffset)
        let (sourcePresentation, sourceOverflow) = chunk.source.presentationNanoseconds
            .addingReportingOverflow(nanosecondOffset)
        let (sampleStart, sampleOverflow) = chunk.sampleStart.addingReportingOverflow(Int64(offset))
        guard !presentationOverflow, !sourceOverflow, !sampleOverflow else {
            throw RecordingTimelineError.arithmeticOverflow
        }
        return .init(
            track: chunk.track,
            presentationNanoseconds: presentation,
            sampleStart: sampleStart,
            sampleCount: count,
            format: chunk.format,
            source: .init(
                sampleRate: chunk.source.sampleRate,
                channelCount: chunk.source.channelCount,
                deviceID: chunk.source.deviceID,
                initialRoute: chunk.source.initialRoute,
                conversionVersion: chunk.source.conversionVersion,
                presentationNanoseconds: sourcePresentation
            ),
            payload: chunk.payload.subdata(in: byteStart..<byteEnd)
        )
    }
}

private struct RecordingLevelThrottle: Sendable {
    private static let intervalSamples = RecordingPCMFormat.canonicalSampleRate / 10
    private var lastEmissionByTrack: [RecordingTrackKind: Int64] = [:]

    mutating func shouldEmit(for chunk: RecordingPCMChunk) -> Bool {
        guard let lastEmission = lastEmissionByTrack[chunk.track] else {
            lastEmissionByTrack[chunk.track] = chunk.sampleStart
            return true
        }
        let (distance, overflow) = chunk.sampleStart.subtractingReportingOverflow(lastEmission)
        guard !overflow, distance >= Int64(Self.intervalSamples) else { return false }
        lastEmissionByTrack[chunk.track] = chunk.sampleStart
        return true
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
