import SwiftUI

/// The spoken attempts of one block: start a recording that carries the activity id,
/// then read back each recording's server state and, once analysed, its speaker turns.
@MainActor
final class SpokenAttemptModel: ObservableObject {
    @Published private(set) var recordings: [RecordingServerStatus] = []
    @Published private(set) var analyses: [UUID: RecordingAnalysis] = [:]
    @Published private(set) var isLoading = false
    @Published private(set) var errorMessage: String?

    let activityID: Int
    let coordinator: RecordingCoordinator
    private let server: any RecordingServerServicing

    init(activityID: Int, coordinator: RecordingCoordinator, server: any RecordingServerServicing) {
        self.activityID = activityID
        self.coordinator = coordinator
        self.server = server
    }

    var canRecord: Bool { !coordinator.phase.isActive }

    func record() async {
        await coordinator.start(activityID: activityID)
    }

    func refresh() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let listed = try await server.recordings(activityID: activityID)
            recordings = listed
            for recording in listed where recording.transcriptLineageAccepted {
                analyses[recording.recordingID] = try await server.analysis(
                    recordingID: recording.recordingID
                )
            }
            errorMessage = nil
        } catch {
            errorMessage = "The recordings for this block could not be loaded."
        }
    }

    func analysis(for recording: RecordingServerStatus) -> RecordingAnalysis {
        analyses[recording.recordingID] ?? .notRequested
    }
}

struct SpokenAttemptPanel: View {
    @ObservedObject var model: SpokenAttemptModel
    @ObservedObject var coordinator: RecordingCoordinator

    init(model: SpokenAttemptModel) {
        self.model = model
        self.coordinator = model.coordinator
    }

    var body: some View {
        GroupBox("Spoken attempt") {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: Organic.Space.p8) {
                    Button("Record this attempt") { Task { await model.record() } }
                        .buttonStyle(.organicPrimary)
                        .disabled(!model.canRecord)
                        .accessibilityIdentifier("spokenAttemptRecord")
                    Spacer(minLength: 0)
                    // Link style keeps both buttons on one row of the 300 pt rail.
                    Button("Refresh") { Task { await model.refresh() } }
                        .buttonStyle(.organicLink)
                        .disabled(model.isLoading)
                        .accessibilityIdentifier("spokenAttemptRefresh")
                }
                if coordinator.phase.isActive {
                    Text("Recording in progress").organic(.small, color: Organic.Color.accent300)
                }
                Text("The recording carries this block's id; the transcript is made on this Mac and the server turns it into speaker turns.")
                    .organic(.caption)
                if model.recordings.isEmpty {
                    Text("No recordings for this block yet.")
                        .organic(.small)
                        .accessibilityIdentifier("spokenAttemptEmpty")
                }
                ForEach(model.recordings, id: \.recordingID) { recording in
                    recordingRow(recording)
                }
                if let message = model.errorMessage {
                    Label(message, systemImage: "exclamationmark.triangle")
                        .organic(.small, color: Organic.Color.warning)
                        .accessibilityIdentifier("spokenAttemptError")
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityIdentifier("spokenAttemptPanel")
        .task { await model.refresh() }
    }

    @ViewBuilder
    private func recordingRow(_ recording: RecordingServerStatus) -> some View {
        let analysis = model.analysis(for: recording)
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: Organic.Space.p8) {
                if let startedAt = recording.startedAt {
                    Text(startedAt, style: .time).organic(.strong)
                }
                Text(recording.state.replacingOccurrences(of: "_", with: " "))
                    .organic(.caption)
                Spacer(minLength: 0)
                Text(statusLabel(analysis))
                    .organic(.caption, color: analysis.status == "needs_attention" ? Organic.Color.warning : Organic.Color.muted)
            }
            ForEach(analysis.turns) { turn in
                HStack(alignment: .top, spacing: Organic.Space.p8) {
                    Text(timestamp(turn.startMS))
                        .font(Organic.Font.tabular(.regular, size: 12))
                        .foregroundStyle(Organic.Color.faint)
                    Text(turn.isLearner ? "You" : "Other")
                        .font(Organic.Font.figtree(.semibold, size: 12))
                        .foregroundStyle(turn.isLearner ? Organic.Color.accent300 : Organic.Color.accent2_300)
                        .frame(width: 44, alignment: .leading)
                    Text(turn.text).organic(.small, color: Organic.Color.body).textSelection(.enabled)
                }
            }
        }
        .padding(Organic.Space.p12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Organic.Color.fill04, in: RoundedRectangle(cornerRadius: Organic.Radius.r20, style: .continuous))
    }

    private func statusLabel(_ analysis: RecordingAnalysis) -> String {
        switch analysis.status {
        case "published": "Transcript ready"
        case "queued", "running": "Transcript in progress"
        case "needs_attention": "Transcript needs attention" + (analysis.failureCategory.map { " (\($0.replacingOccurrences(of: "_", with: " ")))" } ?? "")
        default: "Waiting for the transcript"
        }
    }

    private func timestamp(_ milliseconds: Int) -> String {
        let seconds = milliseconds / 1000
        return String(format: "%d:%02d", seconds / 60, seconds % 60)
    }
}
