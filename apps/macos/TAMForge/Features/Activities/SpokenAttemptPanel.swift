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
                HStack {
                    Button("Record this attempt") { Task { await model.record() } }
                        .buttonStyle(.borderedProminent)
                        .disabled(!model.canRecord)
                        .accessibilityIdentifier("spokenAttemptRecord")
                    if coordinator.phase.isActive {
                        Text(coordinator.phase.isActive ? "Recording in progress" : "").foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button("Refresh") { Task { await model.refresh() } }
                        .disabled(model.isLoading)
                        .accessibilityIdentifier("spokenAttemptRefresh")
                }
                Text("The recording carries this block's id; the transcript is made on this Mac and the server turns it into speaker turns.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if model.recordings.isEmpty {
                    Text("No recordings for this block yet.")
                        .foregroundStyle(.secondary)
                        .accessibilityIdentifier("spokenAttemptEmpty")
                }
                ForEach(model.recordings, id: \.recordingID) { recording in
                    recordingRow(recording)
                }
                if let message = model.errorMessage {
                    Label(message, systemImage: "exclamationmark.triangle")
                        .foregroundStyle(.orange)
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
            HStack {
                if let startedAt = recording.startedAt {
                    Text(startedAt, style: .time).font(.subheadline.weight(.medium))
                }
                Text(recording.state.replacingOccurrences(of: "_", with: " "))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                Text(statusLabel(analysis))
                    .font(.caption)
                    .foregroundStyle(analysis.status == "needs_attention" ? .orange : .secondary)
            }
            ForEach(analysis.turns) { turn in
                HStack(alignment: .top, spacing: 8) {
                    Text(timestamp(turn.startMS))
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                    Text(turn.isLearner ? "You" : "Other")
                        .font(.caption.weight(.semibold))
                        .frame(width: 44, alignment: .leading)
                    Text(turn.text).textSelection(.enabled)
                }
            }
        }
        .padding(8)
        .background(.quaternary, in: RoundedRectangle(cornerRadius: 6))
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
