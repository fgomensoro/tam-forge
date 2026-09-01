import SwiftUI

struct RecordingView: View {
    @ObservedObject var coordinator: RecordingCoordinator
    @State private var pendingDiscardID: UUID?

    private struct UploadStatusDescription {
        let title: String
        let symbol: String
        let color: Color
        let accessibilityLabel: String
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                header
                phaseNotice
                recordingControls
                consentSummary
                if let snapshot = coordinator.preflightSnapshot,
                    coordinator.phase.hasCurrentPreflightSnapshot
                {
                    preflightSummary(snapshot)
                }
                captureHealth
                if !coordinator.pendingRecordingIDs.isEmpty { pendingRecovery }
            }
            .padding()
        }
        .accessibilityIdentifier("recordingScreen")
        .confirmationDialog(
            "Discard encrypted recording?",
            isPresented: Binding(
                get: { pendingDiscardID != nil },
                set: { if !$0 { pendingDiscardID = nil } }
            )
        ) {
            Button("Discard permanently", role: .destructive) {
                guard let recordingID = pendingDiscardID else { return }
                pendingDiscardID = nil
                Task { await coordinator.discardPending(recordingID: recordingID, confirmed: true) }
            }
            Button("Cancel", role: .cancel) { pendingDiscardID = nil }
        } message: {
            Text(
                "This crypto-shreds the local key and removes the encrypted spool. It cannot be undone."
            )
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Recording").font(.largeTitle).bold().accessibilityAddTraits(.isHeader)
            Text("Capture microphone and system audio only after you explicitly start.")
                .foregroundStyle(.secondary)
        }
    }

    @ViewBuilder
    private var phaseNotice: some View {
        switch coordinator.phase {
        case .idle:
            Label("Ready to check recording access.", systemImage: "record.circle")
                .foregroundStyle(.secondary)
        case .preflighting:
            ProgressView("Checking access, microphone, display, and disk reserve…")
        case .blocked(let failure):
            stateNotice(title: "Recording is blocked", detail: failure.message, color: .red)
        case .recording:
            stateNotice(
                title: "Recording in progress",
                detail: "Keep TAM Forge open until you stop and seal this recording.", color: .red)
        case .stopping:
            stateNotice(
                title: "Sealing recording",
                detail: "TAM Forge is stopping capture and sealing the local recording.",
                color: .orange)
        case .sealed:
            stateNotice(
                title: "Recording sealed",
                detail: "Capture has stopped. It will not resume automatically.",
                color: .green)
        case .needsAttention(_, let message):
            stateNotice(title: "Recording needs attention", detail: message, color: .orange)
        }
    }

    @ViewBuilder
    private var recordingControls: some View {
        GroupBox("Recording control") {
            switch coordinator.phase {
            case .idle:
                Button("Start recording") { Task { await coordinator.start() } }
                    .buttonStyle(.borderedProminent)
                    .accessibilityIdentifier("recordingStartButton")
                    .accessibilityLabel("Start recording")
            case .preflighting:
                Button("Checking recording access") {}
                    .disabled(true)
                    .accessibilityIdentifier("recordingPreflightingButton")
            case .recording:
                Button("Stop recording") { Task { await coordinator.stop() } }
                    .buttonStyle(.borderedProminent)
                    .tint(.red)
                    .accessibilityIdentifier("recordingStopButton")
                    .accessibilityLabel("Stop recording and seal local capture")
            case .stopping:
                Button("Sealing recording") {}
                    .disabled(true)
                    .accessibilityIdentifier("recordingStoppingButton")
            case .blocked:
                Button("Retry recording checks") { Task { await coordinator.start() } }
                    .accessibilityIdentifier("recordingRetryButton")
                    .accessibilityLabel("Retry recording checks")
            case .sealed:
                Button("Prepare another recording") { coordinator.resetSealedState() }
                    .accessibilityIdentifier("recordingResetSealedButton")
                    .accessibilityLabel("Prepare another recording")
            case .needsAttention:
                Button("Try recording again") { Task { await coordinator.start() } }
                    .accessibilityIdentifier("recordingRetryAfterAttentionButton")
                    .accessibilityLabel("Try recording again after reviewing capture health")
            }
        }
        .accessibilityIdentifier("recordingControls")
    }

    private var consentSummary: some View {
        GroupBox("Preflight and consent") {
            VStack(alignment: .leading, spacing: 8) {
                Text(
                    "Start checks microphone and Screen Recording permission, a shareable display, and disk reserve before capture begins."
                )
                Text(
                    "Audio stays in an encrypted local spool while capture is active. Nothing starts automatically."
                )
                .foregroundStyle(.secondary)
                Label(
                    "Coverage remains provisional until recording is sealed and reviewed.",
                    systemImage: "exclamationmark.triangle"
                )
                .foregroundStyle(.orange)
                .accessibilityIdentifier("recordingProvisionalCoverage")
            }
        }
        .accessibilityIdentifier("recordingConsentSummary")
        .accessibilityLabel(
            "Preflight and consent. Recording starts only after you press Start recording. Coverage remains provisional until sealed and reviewed."
        )
    }

    private func preflightSummary(_ snapshot: RecordingPreflightSnapshot) -> some View {
        GroupBox("Current recording setup") {
            Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 10) {
                GridRow {
                    Text("Microphone").foregroundStyle(.secondary)
                    Text(snapshot.selectedMicrophone.name)
                        .accessibilityIdentifier("recordingSelectedMicrophone")
                }
                GridRow {
                    Text("Route").foregroundStyle(.secondary)
                    Text(routeDescription)
                        .accessibilityIdentifier("recordingRoute")
                }
                GridRow {
                    Text("Displays available").foregroundStyle(.secondary)
                    Text("\(snapshot.displayCount)")
                        .accessibilityIdentifier("recordingDisplayCount")
                }
                GridRow {
                    Text("Disk available").foregroundStyle(.secondary)
                    Text(byteCount(snapshot.availableDiskBytes))
                        .accessibilityIdentifier("recordingAvailableDisk")
                }
                GridRow {
                    Text("Required free reserve").foregroundStyle(.secondary)
                    Text(byteCount(RecordingDiskPolicy.requiredFreeReserveBytes))
                        .accessibilityIdentifier("recordingDiskReserve")
                }
                GridRow {
                    Text("Pending local spools").foregroundStyle(.secondary)
                    Text(byteCount(snapshot.pendingSpoolBytes))
                        .accessibilityIdentifier("recordingPendingSpools")
                }
            }
        }
        .accessibilityIdentifier("recordingPreflightSummary")
        .accessibilityElement(children: .contain)
    }

    private var captureHealth: some View {
        GroupBox("Capture health") {
            VStack(alignment: .leading, spacing: 12) {
                if let startedAt = coordinator.startedAt {
                    HStack {
                        Text("Elapsed").foregroundStyle(.secondary)
                        Text(startedAt, style: .timer).monospacedDigit()
                            .accessibilityIdentifier("recordingElapsedTime")
                    }
                }
                trackHealth(
                    "Microphone", track: coordinator.health.microphone,
                    identifier: "recordingMicrophone")
                trackHealth(
                    "System audio", track: coordinator.health.systemAudio,
                    identifier: "recordingSystemAudio")
            }
        }
        .accessibilityIdentifier("recordingCaptureHealth")
    }

    private var pendingRecovery: some View {
        GroupBox("Pending encrypted recordings") {
            VStack(alignment: .leading, spacing: 10) {
                Text("TAM Forge retained these recordings for recovery.")
                    .foregroundStyle(.secondary)
                Text(
                    "A server audio 201 receipt alone does not delete the local encrypted spool. It stays until transcript-lineage acceptance."
                )
                .font(.caption)
                .foregroundStyle(.secondary)
                ForEach(coordinator.pendingRecordingIDs, id: \.self) { recordingID in
                    VStack(alignment: .leading, spacing: 8) {
                        Text(recordingID.uuidString)
                            .font(.caption)
                            .textSelection(.enabled)
                        uploadStatus(for: recordingID)
                        HStack {
                            if uploadStateAllowsRetry(recordingID) {
                                Button("Retry") {
                                    coordinator.retryUpload(recordingID: recordingID)
                                }
                                .accessibilityLabel("Retry upload for pending encrypted recording")
                            }
                            Spacer()
                            Button("Discard", role: .destructive) { pendingDiscardID = recordingID }
                                .accessibilityLabel("Discard pending encrypted recording")
                        }
                    }
                    .padding(.vertical, 4)
                    .accessibilityElement(children: .contain)
                }
            }
        }
        .accessibilityIdentifier("recordingPendingRecovery")
    }

    @ViewBuilder
    private func uploadStatus(for recordingID: UUID) -> some View {
        let status = uploadStatusDescription(for: coordinator.uploadStates[recordingID] ?? .pending)
        Label(status.title, systemImage: status.symbol)
            .foregroundStyle(status.color)
            .accessibilityIdentifier("recordingUploadStatus")
            .accessibilityLabel(status.accessibilityLabel)
    }

    private func uploadStateAllowsRetry(_ recordingID: UUID) -> Bool {
        guard !coordinator.phase.isActive else { return false }
        return switch coordinator.uploadStates[recordingID] ?? .pending {
        case .uploading:
            false
        case .pending, .waitingForAuthentication, .waitingForNetwork, .waitingForTranscript,
            .needsAttention:
            true
        }
    }

    private func uploadStatusDescription(for state: RecordingUploadState) -> UploadStatusDescription
    {
        switch state {
        case .pending:
            .init(
                title: "Ready to upload",
                symbol: "clock",
                color: .secondary,
                accessibilityLabel: "Upload pending. Retry uploads this encrypted recording."
            )
        case .uploading(let completedParts):
            .init(
                title:
                    "Uploading: \(completedParts) part\(completedParts == 1 ? "" : "s") complete",
                symbol: "arrow.up.circle",
                color: .blue,
                accessibilityLabel:
                    "Uploading encrypted recording. \(completedParts) part\(completedParts == 1 ? "" : "s") complete."
            )
        case .waitingForAuthentication:
            .init(
                title: "Waiting for sign-in",
                symbol: "person.crop.circle.badge.exclamationmark",
                color: .orange,
                accessibilityLabel: "Upload is waiting for authentication. Sign in, then retry."
            )
        case .waitingForNetwork:
            .init(
                title: "Waiting for network",
                symbol: "wifi.exclamationmark",
                color: .orange,
                accessibilityLabel:
                    "Upload is waiting for a network connection. Reconnect, then retry."
            )
        case .waitingForTranscript:
            .init(
                title: "Waiting for transcript acceptance",
                symbol: "text.badge.clock",
                color: .orange,
                accessibilityLabel:
                    "Server audio was accepted, but the local encrypted spool remains until transcript-lineage acceptance. Retry checks its status again."
            )
        case .needsAttention(let message):
            .init(
                title: "Needs attention: \(message)",
                symbol: "exclamationmark.triangle",
                color: .red,
                accessibilityLabel:
                    "Recording upload needs attention. \(message). Retry attempts recovery."
            )
        }
    }

    private func trackHealth(
        _ title: String,
        track: RecordingTrackHealth,
        identifier: String
    ) -> some View {
        let level = Swift.max(0, Swift.min(track.normalizedLevel, 1))
        let percentage = Int((level * 100).rounded())
        let status = track.statusMessage

        return VStack(alignment: .leading, spacing: 5) {
            HStack {
                Text(title).font(.headline)
                Spacer()
                Text("\(percentage)%").monospacedDigit().foregroundStyle(.secondary)
            }
            ProgressView(value: level, total: 1)
            Text(status).font(.caption).foregroundStyle(
                track.warning == nil ? Color.secondary : Color.orange
            )
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("\(identifier)Health")
        .accessibilityLabel("\(title) health")
        .accessibilityValue("Level \(percentage) percent. \(status)")
    }

    private var routeDescription: String {
        coordinator.health.routeDescription.isEmpty
            ? coordinator.preflightSnapshot?.routeDescription ?? "Not available"
            : coordinator.health.routeDescription
    }

    private func stateNotice(title: String, detail: String, color: Color) -> some View {
        Label {
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(.headline)
                Text(detail).font(.subheadline)
            }
        } icon: {
            Image(systemName: "exclamationmark.triangle")
        }
        .foregroundStyle(color)
        .accessibilityIdentifier("recordingPhase")
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(title). \(detail)")
    }

    private func byteCount(_ value: Int64) -> String {
        ByteCountFormatter.string(fromByteCount: value, countStyle: .file)
    }
}

struct RecordingGlobalStatusView: View {
    @ObservedObject var coordinator: RecordingCoordinator

    var body: some View {
        if coordinator.phase.isActive {
            HStack(spacing: 10) {
                Image(systemName: coordinator.phase.globalStatusSymbol)
                    .foregroundStyle(coordinator.phase.globalStatusColor)
                Text(coordinator.phase.globalStatusTitle).font(.headline)
                if let startedAt = coordinator.startedAt {
                    Text(startedAt, style: .timer).monospacedDigit()
                }
                Spacer()
                Text(
                    coordinator.health.routeDescription.isEmpty
                        ? "Recording route pending" : coordinator.health.routeDescription
                )
                .foregroundStyle(.secondary)
                .lineLimit(1)
                if case .recording = coordinator.phase {
                    Button("Stop") { Task { await coordinator.stop() } }
                        .buttonStyle(.borderedProminent)
                        .tint(.red)
                        .accessibilityIdentifier("recordingGlobalStopButton")
                }
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 10)
            .background(.thinMaterial)
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("recordingGlobalStatus")
            .accessibilityLabel(globalAccessibilityLabel)
        }
    }

    private var globalAccessibilityLabel: String {
        var label = coordinator.phase.globalStatusTitle
        if let startedAt = coordinator.startedAt {
            label += ". Recording started \(startedAt.formatted(date: .omitted, time: .shortened))"
        }
        if !coordinator.health.routeDescription.isEmpty {
            label += ". Route \(coordinator.health.routeDescription)"
        }
        return label
    }
}

extension RecordingPreflightFailure {
    fileprivate var message: String {
        switch self {
        case .microphonePermissionDenied:
            "Microphone access is denied. Allow it in System Settings before retrying."
        case .microphonePermissionRestricted:
            "Microphone access is restricted on this Mac."
        case .microphonePermissionNotDetermined:
            "Microphone access was not granted. Retry when you are ready to respond to the permission prompt."
        case .microphoneMissing:
            "No connected microphone was found."
        case .microphoneInUse:
            "Selected microphone is in use by another application."
        case .screenRecordingPermissionDenied:
            "Screen Recording access is required to capture system audio."
        case .noShareableDisplay:
            "No shareable display is available for system-audio capture."
        case .insufficientDiskReserve:
            "Disk reserve is too low for a safe recording."
        case .recordingSizeLimitReached:
            "Recording size limit would be exceeded."
        case .globalSpoolLimitReached:
            "Pending local recordings reached their storage limit."
        case .routeUnavailable:
            "Selected audio route is unavailable."
        }
    }
}

extension RecordingTrackHealth {
    fileprivate var statusMessage: String {
        if let warning { return warning.message }
        if gapCount > 0 { return "\(gapCount) coverage gap\(gapCount == 1 ? "" : "s") recorded" }
        return lastSampleEnd == 0 ? "Waiting for audio" : "Receiving audio"
    }
}

extension RecordingCaptureFailure {
    fileprivate var message: String {
        switch self {
        case .permissionLost:
            "Audio permission was lost"
        case .sourceUnavailable:
            "Audio source is unavailable"
        case .formatUnsupported:
            "Audio format is unsupported"
        case .callbackOverflow:
            "Capture callbacks were delayed; coverage gap recorded"
        case .conversionFailed:
            "Audio conversion failed"
        case .streamStopped:
            "Capture stream stopped"
        case .silentInput:
            "No audio signal detected"
        case .requiredTracksMissing:
            "A required audio track never produced data"
        }
    }
}

extension RecordingPhase {
    fileprivate var hasCurrentPreflightSnapshot: Bool {
        if case .blocked = self { return false }
        return true
    }

    fileprivate var globalStatusTitle: String {
        switch self {
        case .preflighting:
            "Preparing recording"
        case .recording:
            "Recording in progress"
        case .stopping:
            "Sealing recording"
        case .idle, .blocked, .sealed, .needsAttention:
            "Recording inactive"
        }
    }

    fileprivate var globalStatusSymbol: String {
        switch self {
        case .recording:
            "record.circle.fill"
        case .preflighting, .stopping:
            "hourglass"
        case .idle, .blocked, .sealed, .needsAttention:
            "record.circle"
        }
    }

    fileprivate var globalStatusColor: Color {
        switch self {
        case .recording:
            .red
        case .preflighting, .stopping:
            .orange
        case .idle, .blocked, .sealed, .needsAttention:
            .secondary
        }
    }
}
