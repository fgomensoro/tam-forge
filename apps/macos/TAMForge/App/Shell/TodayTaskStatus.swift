import Foundation

/// The three row states the Organic Today screen draws. `TodayTask.state` is a raw
/// `ActivityState` string; an unrecognised value from a newer server reads as ready
/// rather than silently disappearing from the count.
enum TodayTaskStatus: Equatable {
    case done
    case current
    case ready

    init(rawState: String) {
        switch ActivityState(rawValue: rawState) {
        case .active, .paused, .outputCommitted:
            self = .current
        case .selfReviewComplete, .aiProcessing, .feedbackReady, .demonstrated, .superseded:
            self = .done
        case .ready, .needsWork, .correctionDue, .incomplete, .none:
            self = .ready
        }
    }

    /// The sidebar's "N left" badge: everything that is not finished.
    static func remainingCount(in tasks: [TodayTask]) -> Int {
        tasks.filter { TodayTaskStatus(rawState: $0.state) != .done }.count
    }
}
