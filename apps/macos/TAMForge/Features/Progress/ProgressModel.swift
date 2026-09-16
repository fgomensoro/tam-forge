import Foundation

/// The Progress section: the skills against their targets, the weeks' minutes, the latest
/// reviewer assessments and interviews. One read; nothing here is edited.
@MainActor
final class ProgressModel: ObservableObject {
    @Published private(set) var report: ProgressReport = .empty
    @Published private(set) var isLoading = false
    @Published private(set) var errorMessage: String?
    @Published private(set) var hasLoaded = false

    private let api: any ProgressAPI

    init(api: any ProgressAPI) {
        self.api = api
    }

    var skillsOnTarget: Int {
        report.skills.filter { skill in
            guard let latest = skill.latestLevel else { return false }
            return latest >= skill.monthOneTarget
        }.count
    }

    /// The last eight weeks with a study day, oldest first, for the minutes chart.
    var recentWeeks: [ProgressWeek] { Array(report.weeks.suffix(8)) }

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            report = try await api.read()
            errorMessage = nil
            hasLoaded = true
        } catch let error as ProgressAPIError {
            if error != .cancelled { errorMessage = error.message }
        } catch {
            errorMessage = ProgressAPIError.network.message
        }
    }
}
