import XCTest

final class LocalSpeechSchedulerTests: XCTestCase {
    private let a = UUID(), b = UUID(), c = UUID()

    func testOneJobRunsAtATimeInArrivalOrder() {
        var scheduler = LocalSpeechScheduler()
        scheduler.enqueue(a)
        scheduler.enqueue(b)
        XCTAssertEqual(scheduler.admit(under: .nominal), .run(a))
        XCTAssertEqual(scheduler.admit(under: .nominal), .busy)
        scheduler.finish(a)
        XCTAssertEqual(scheduler.admit(under: .nominal), .run(b))
        scheduler.finish(b)
        XCTAssertEqual(scheduler.admit(under: .nominal), .nothingQueued)
        XCTAssertTrue(scheduler.isIdle)
    }

    func testARecordingIsQueuedOnce() {
        var scheduler = LocalSpeechScheduler()
        scheduler.enqueue(a)
        scheduler.enqueue(a)
        XCTAssertEqual(scheduler.queue, [a])
        XCTAssertEqual(scheduler.admit(under: .nominal), .run(a))
        scheduler.enqueue(a)
        XCTAssertEqual(scheduler.queue, [])
    }

    func testMemoryWarningAndSeriousThermalDeferNewWorkButDoNotAbortRunningWork() {
        var scheduler = LocalSpeechScheduler()
        scheduler.enqueue(a)
        XCTAssertEqual(
            scheduler.admit(under: ResourceState(memory: .warning)),
            .deferred("Waiting for memory pressure to clear")
        )
        XCTAssertEqual(
            scheduler.admit(under: ResourceState(thermal: .serious)),
            .deferred("Waiting for the Mac to cool down")
        )
        XCTAssertEqual(scheduler.queue, [a])
        XCTAssertFalse(LocalSpeechScheduler.mustAbort(under: ResourceState(memory: .warning)))
        XCTAssertFalse(LocalSpeechScheduler.mustAbort(under: ResourceState(thermal: .critical)))
        XCTAssertEqual(scheduler.admit(under: ResourceState(thermal: .fair)), .run(a))
    }

    func testCriticalMemoryAbortsAndTheAbortedJobRetriesFirst() {
        var scheduler = LocalSpeechScheduler()
        scheduler.enqueue(a)
        scheduler.enqueue(b)
        XCTAssertEqual(scheduler.admit(under: .nominal), .run(a))
        XCTAssertTrue(LocalSpeechScheduler.mustAbort(under: ResourceState(memory: .critical)))
        scheduler.finish(a, requeue: true)
        XCTAssertEqual(scheduler.queue, [a, b])
        XCTAssertEqual(scheduler.admit(under: ResourceState(memory: .critical)), .deferred("Waiting for memory pressure to clear"))
        XCTAssertEqual(scheduler.admit(under: .nominal), .run(a))
    }

    func testCancellingForgetsAQueuedOrRunningRecordingOnly() {
        var scheduler = LocalSpeechScheduler()
        scheduler.enqueue(a)
        scheduler.enqueue(b)
        scheduler.enqueue(c)
        XCTAssertEqual(scheduler.admit(under: .nominal), .run(a))
        scheduler.cancel(b)
        scheduler.cancel(a)
        XCTAssertNil(scheduler.running)
        XCTAssertEqual(scheduler.queue, [c])
        scheduler.finish(a)
        XCTAssertEqual(scheduler.admit(under: .nominal), .run(c))
    }

    func testFinishingSomethingThatIsNotRunningChangesNothing() {
        var scheduler = LocalSpeechScheduler()
        scheduler.enqueue(a)
        scheduler.finish(b)
        XCTAssertEqual(scheduler.queue, [a])
        XCTAssertNil(scheduler.running)
    }
}
