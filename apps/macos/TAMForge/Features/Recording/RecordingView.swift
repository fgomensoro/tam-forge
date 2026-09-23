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

    /// One dot in a preflight row. `passed` is nil while the check has not run
    /// yet, so the row never claims a result the coordinator did not report.
    private struct PreflightItem: Identifiable {
        let id: String
        let title: String
        let passed: Bool?
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Organic.Space.p24) {
                if isRecording {
                    liveRecording
                } else {
                    OrganicPageHeader(
                        title: "Recording",
                        subtitle: "Capture microphone and system audio only after you explicitly start."
                    )
                    phaseNotice
                    recordingControls
                }
                transcriptSection
                consentSummary
                if let snapshot = coordinator.preflightSnapshot,
                    coordinator.phase.hasCurrentPreflightSnapshot
                {
                    preflightSummary(snapshot)
                }
                captureHealth
                if !coordinator.pendingRecordingIDs.isEmpty { pendingRecovery }
            }
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

    private var isRecording: Bool {
        if case .recording = coordinator.phase { return true }
        return false
    }

    // MARK: - Live recording

    /// The handoff's recording screen: a centred column, max 640, with the
    /// phase tag, the 260 pt ring and clock, the headline, the controls and the
    /// preflight row. The ring is static, so reduce motion has nothing to turn off.
    private var liveRecording: some View {
        VStack(spacing: Organic.Space.p28) {
            phaseNotice
            recordingRing
            VStack(spacing: 6) {
                Text("Encrypted locally. Transcribing on-device.")
                    .font(Organic.Font.figtree(.semibold, size: 26))
                    .tracking(-0.52)
                    .foregroundStyle(Organic.Color.text)
                    .accessibilityAddTraits(.isHeader)
                Text(
                    "Microphone and system audio. Keep TAM Forge open until you stop and seal this recording; nothing leaves this Mac before then."
                )
                .organic(.body, color: Organic.Color.muted)
                .fixedSize(horizontal: false, vertical: true)
            }
            .multilineTextAlignment(.center)
            recordingControls
            HStack(spacing: Organic.Space.p24) {
                ForEach(liveChecks) { item in
                    HStack(spacing: 6) {
                        OrganicStatusDot(color: dotColor(item.passed), diameter: 7)
                        Text(item.title)
                            .organic(
                                .caption,
                                color: item.passed == false ? Organic.Color.accent300 : Organic.Color.muted)
                    }
                    .accessibilityElement(children: .combine)
                }
            }
        }
        .frame(maxWidth: 640)
        .frame(maxWidth: .infinity)
        .padding(.vertical, Organic.Space.p32)
    }

    private var recordingRing: some View {
        ZStack {
            Circle().fill(Organic.Color.accent.opacity(0.10))
            Circle().fill(Organic.Color.accent.opacity(0.16)).padding(28)
            Circle().fill(Organic.Color.accent).padding(56)
            Group {
                if let startedAt = coordinator.startedAt {
                    Text(startedAt, style: .timer)
                } else {
                    Text("0:00")
                }
            }
            .font(Organic.Font.tabular(.semibold, size: 32))
            .tracking(-0.32)
            .foregroundStyle(Organic.Color.neutral900)
        }
        .frame(width: 260, height: 260)
    }

    private var liveChecks: [PreflightItem] {
        let microphoneOK = coordinator.health.microphone.warning == nil
        let systemAudioOK = coordinator.health.systemAudio.warning == nil
        var items = [
            PreflightItem(
                id: "microphone",
                title: microphoneOK ? "Mic OK" : "Mic needs attention",
                passed: microphoneOK),
            PreflightItem(
                id: "systemAudio",
                title: systemAudioOK ? "Screen audio OK" : "Screen audio needs attention",
                passed: systemAudioOK),
        ]
        if let snapshot = coordinator.preflightSnapshot {
            items.append(
                PreflightItem(
                    id: "disk",
                    title: "\(byteCount(snapshot.availableDiskBytes)) free",
                    passed: snapshot.availableDiskBytes >= RecordingDiskPolicy.requiredFreeReserveBytes))
        }
        return items
    }

    // MARK: - Phase and controls

    @ViewBuilder
    private var phaseNotice: some View {
        switch coordinator.phase {
        case .idle:
            Label("Ready to check recording access.", systemImage: "record.circle")
                .organic(.small)
        case .preflighting:
            ProgressView("Checking access, microphone, display, and disk reserve…")
                .controlSize(.small)
        case .blocked(let failure):
            stateNotice(title: "Recording is blocked", detail: failure.message, tint: Organic.Color.danger)
        case .recording:
            stateNotice(
                title: "Recording in progress",
                detail: "Keep TAM Forge open until you stop and seal this recording.",
                tint: Organic.Color.accent300,
                compact: true)
        case .stopping:
            stateNotice(
                title: "Sealing recording",
                detail: "TAM Forge is stopping capture and sealing the local recording.",
                tint: Organic.Color.warning,
                systemImage: "lock")
        case .sealed:
            stateNotice(
                title: "Recording sealed",
                detail: "Capture has stopped. It will not resume automatically.",
                tint: Organic.Color.success,
                systemImage: "checkmark.seal")
        case .needsAttention(_, let message):
            stateNotice(title: "Recording needs attention", detail: message, tint: Organic.Color.warning)
        }
    }

    /// While recording the controls sit bare in the centred column; every other
    /// phase keeps them in the "Recording control" card.
    private var recordingControls: some View {
        Group {
            if isRecording {
                controlButton
            } else {
                GroupBox("Recording control") { controlButton }
            }
        }
        .accessibilityIdentifier("recordingControls")
    }

    @ViewBuilder
    private var controlButton: some View {
        switch coordinator.phase {
        case .idle:
            Button("Start recording") { Task { await coordinator.start() } }
                .buttonStyle(.organicPrimary)
                .accessibilityIdentifier("recordingStartButton")
                .accessibilityLabel("Start recording")
        case .preflighting:
            Button("Checking recording access") {}
                .disabled(true)
                .accessibilityIdentifier("recordingPreflightingButton")
        case .recording:
            // No Pause here: the coordinator has no pause, only stop and seal.
            Button {
                Task { await coordinator.stop() }
            } label: {
                HStack(spacing: Organic.Space.p8) {
                    RoundedRectangle(cornerRadius: 2, style: .continuous)
                        .fill(Organic.Color.neutral900)
                        .frame(width: 10, height: 10)
                    Text("Stop & seal")
                }
            }
            .buttonStyle(OrganicPrimaryButtonStyle(size: 14, horizontalPadding: 22, verticalPadding: 11))
            .accessibilityIdentifier("recordingStopButton")
            .accessibilityLabel("Stop recording and seal local capture")
        case .stopping:
            Button("Sealing recording") {}
                .disabled(true)
                .accessibilityIdentifier("recordingStoppingButton")
        case .blocked:
            Button("Retry recording checks") { Task { await coordinator.start() } }
                .buttonStyle(.organicPrimary)
                .accessibilityIdentifier("recordingRetryButton")
                .accessibilityLabel("Retry recording checks")
        case .sealed:
            Button("Prepare another recording") { coordinator.resetSealedState() }
                .buttonStyle(.organicPrimary)
                .accessibilityIdentifier("recordingResetSealedButton")
                .accessibilityLabel("Prepare another recording")
        case .needsAttention:
            Button("Try recording again") { Task { await coordinator.start() } }
                .buttonStyle(.organicPrimary)
                .accessibilityIdentifier("recordingRetryAfterAttentionButton")
                .accessibilityLabel("Try recording again after reviewing capture health")
        }
    }

    // MARK: - Transcript

    // Local only: nothing here is written to disk or sent anywhere until
    // issue #44. Absent whenever transcriptState is .idle, which is every
    // launch that has no transcriber configured.
    @ViewBuilder
    private var transcriptSection: some View {
        if coordinator.transcriptState != .idle {
            GroupBox("Local transcript") {
                switch coordinator.transcriptState {
                case .idle:
                    EmptyView()
                case .running:
                    ProgressView("Transcribing this recording on this Mac.")
                        .controlSize(.small)
                        .accessibilityIdentifier("recordingTranscriptStatus")
                case .ready(_, let result):
                    VStack(alignment: .leading, spacing: Organic.Space.p8) {
                        ScrollView {
                            Text(result.text)
                                .organic(.body)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .textSelection(.enabled)
                        }
                        .frame(maxHeight: 280)
                        .accessibilityIdentifier("recordingTranscript")
                        Text("Transcribed locally with \(result.identity.modelFilename).")
                            .organic(.caption)
                            .accessibilityIdentifier("recordingTranscriptModel")
                    }
                case .failed(_, let reason):
                    Label(reason, systemImage: "exclamationmark.triangle")
                        .organic(.small, color: Organic.Color.warning)
                        .accessibilityIdentifier("recordingTranscriptStatus")
                case .deferred(_, let reason):
                    Label(reason, systemImage: "hourglass")
                        .organic(.small)
                        .accessibilityIdentifier("recordingTranscriptStatus")
                }
            }
            .accessibilityIdentifier("recordingTranscriptSection")
        }
    }

    // MARK: - Setup cards

    private var consentSummary: some View {
        GroupBox("Preflight and consent") {
            VStack(alignment: .leading, spacing: Organic.Space.p12) {
                Text("Start checks these before capture begins.")
                    .organic(.body)
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(preflightChecks) { item in
                        HStack(spacing: 10) {
                            OrganicStatusDot(color: dotColor(item.passed), diameter: 8)
                            Text(item.title)
                                .organic(
                                    .body,
                                    color: item.passed == false ? Organic.Color.accent300 : Organic.Color.body)
                        }
                    }
                }
                Text(
                    "Audio stays in an encrypted local spool while capture is active. Nothing starts automatically."
                )
                .organic(.small)
                Label(
                    "Coverage remains provisional until recording is sealed and reviewed.",
                    systemImage: "exclamationmark.triangle"
                )
                .organic(.small, color: Organic.Color.warning)
                .accessibilityIdentifier("recordingProvisionalCoverage")
            }
        }
        .accessibilityIdentifier("recordingConsentSummary")
        .accessibilityLabel(
            "Preflight and consent. Recording starts only after you press Start recording. Coverage remains provisional until sealed and reviewed."
        )
    }

    /// Sage once the last preflight passed, accent on the check that blocked
    /// it, neutral for anything not checked yet.
    private var preflightChecks: [PreflightItem] {
        let passedAll =
            coordinator.preflightSnapshot != nil && coordinator.phase.hasCurrentPreflightSnapshot
        var blockedOn: RecordingPreflightCheck?
        if case .blocked(let failure) = coordinator.phase { blockedOn = failure.check }
        return RecordingPreflightCheck.allCases.map { check in
            let passed: Bool? = blockedOn == check ? false : (passedAll ? true : nil)
            return PreflightItem(id: check.title, title: check.title, passed: passed)
        }
    }

    private func preflightSummary(_ snapshot: RecordingPreflightSnapshot) -> some View {
        GroupBox("Current recording setup") {
            Grid(alignment: .leading, horizontalSpacing: Organic.Space.p18, verticalSpacing: 10) {
                GridRow {
                    setupLabel("Microphone")
                    Text(snapshot.selectedMicrophone.name)
                        .accessibilityIdentifier("recordingSelectedMicrophone")
                }
                GridRow {
                    setupLabel("Route")
                    Text(routeDescription)
                        .accessibilityIdentifier("recordingRoute")
                }
                GridRow {
                    setupLabel("Displays available")
                    Text("\(snapshot.displayCount)")
                        .accessibilityIdentifier("recordingDisplayCount")
                }
                GridRow {
                    setupLabel("Disk available")
                    Text(byteCount(snapshot.availableDiskBytes))
                        .accessibilityIdentifier("recordingAvailableDisk")
                }
                GridRow {
                    setupLabel("Required free reserve")
                    Text(byteCount(RecordingDiskPolicy.requiredFreeReserveBytes))
                        .accessibilityIdentifier("recordingDiskReserve")
                }
                GridRow {
                    setupLabel("Pending local spools")
                    Text(byteCount(snapshot.pendingSpoolBytes))
                        .accessibilityIdentifier("recordingPendingSpools")
                }
            }
            .organic(.body)
        }
        .accessibilityIdentifier("recordingPreflightSummary")
        .accessibilityElement(children: .contain)
    }

    private func setupLabel(_ title: String) -> some View {
        Text(title).organic(.body, color: Organic.Color.muted)
    }

    // MARK: - Health and recovery

    private var captureHealth: some View {
        GroupBox("Capture health") {
            VStack(alignment: .leading, spacing: Organic.Space.p14) {
                if let startedAt = coordinator.startedAt {
                    HStack(spacing: Organic.Space.p8) {
                        Text("Elapsed").organic(.body, color: Organic.Color.muted)
                        Text(startedAt, style: .timer)
                            .font(Organic.Font.tabular(.semibold, size: 14))
                            .foregroundStyle(Organic.Color.text)
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
            VStack(alignment: .leading, spacing: Organic.Space.p12) {
                Text("TAM Forge retained these recordings for recovery.")
                    .organic(.body, color: Organic.Color.muted)
                Text(
                    "A server audio 201 receipt alone does not delete the local encrypted spool. It stays until transcript-lineage acceptance."
                )
                .organic(.caption)
                ForEach(coordinator.pendingRecordingIDs, id: \.self) { recordingID in
                    VStack(alignment: .leading, spacing: Organic.Space.p8) {
                        Text(recordingID.uuidString)
                            .organic(.mono)
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
                    .padding(Organic.Space.p14)
                    .background(
                        Organic.Color.fill04,
                        in: RoundedRectangle(cornerRadius: Organic.Radius.r20, style: .continuous)
                    )
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
            .organic(.small, color: status.color)
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
                color: Organic.Color.muted,
                accessibilityLabel: "Upload pending. Retry uploads this encrypted recording."
            )
        case .uploading(let completedParts):
            .init(
                title:
                    "Uploading: \(completedParts) part\(completedParts == 1 ? "" : "s") complete",
                symbol: "arrow.up.circle",
                color: Organic.Color.success,
                accessibilityLabel:
                    "Uploading encrypted recording. \(completedParts) part\(completedParts == 1 ? "" : "s") complete."
            )
        case .waitingForAuthentication:
            .init(
                title: "Waiting for sign-in",
                symbol: "person.crop.circle.badge.exclamationmark",
                color: Organic.Color.warning,
                accessibilityLabel: "Upload is waiting for authentication. Sign in, then retry."
            )
        case .waitingForNetwork:
            .init(
                title: "Waiting for network",
                symbol: "wifi.exclamationmark",
                color: Organic.Color.warning,
                accessibilityLabel:
                    "Upload is waiting for a network connection. Reconnect, then retry."
            )
        case .waitingForTranscript:
            .init(
                title: "Waiting for transcript acceptance",
                symbol: "text.badge.clock",
                color: Organic.Color.warning,
                accessibilityLabel:
                    "Server audio was accepted, but the local encrypted spool remains until transcript-lineage acceptance. Retry checks its status again."
            )
        case .needsAttention(let message):
            .init(
                title: "Needs attention: \(message)",
                symbol: "exclamationmark.triangle",
                color: Organic.Color.danger,
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

        return VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(title).organic(.title)
                Spacer()
                Text("\(percentage)%")
                    .font(Organic.Font.tabular(.semibold, size: 13))
                    .foregroundStyle(Organic.Color.muted)
            }
            ProgressView(value: level, total: 1)
            Text(status).organic(
                .caption,
                color: track.warning == nil ? Organic.Color.muted : Organic.Color.warning)
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("\(identifier)Health")
        .accessibilityLabel("\(title) health")
        .accessibilityValue("Level \(percentage) percent. \(status)")
    }

    // MARK: - Helpers

    private var routeDescription: String {
        coordinator.health.routeDescription.isEmpty
            ? coordinator.preflightSnapshot?.routeDescription ?? "Not available"
            : coordinator.health.routeDescription
    }

    private func dotColor(_ passed: Bool?) -> Color {
        switch passed {
        case true?: Organic.Color.accent2_400
        case false?: Organic.Color.accent
        case nil: Organic.Color.faint
        }
    }

    /// The live screen shows the phase as the handoff's accent tag; every other
    /// phase shows a notice strip. Both carry the same identifier and label.
    private func stateNotice(
        title: String,
        detail: String,
        tint: Color,
        systemImage: String = "exclamationmark.triangle",
        compact: Bool = false
    ) -> some View {
        Group {
            if compact {
                OrganicTag(
                    text: title,
                    background: Organic.Color.accent.opacity(0.24),
                    foreground: tint)
            } else {
                OrganicNotice(systemImage: systemImage, tint: tint, title: title, message: detail)
            }
        }
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
            HStack(spacing: Organic.Space.p12) {
                Image(systemName: coordinator.phase.globalStatusSymbol)
                    .foregroundStyle(coordinator.phase.globalStatusColor)
                Text(coordinator.phase.globalStatusTitle).organic(.strong)
                if let startedAt = coordinator.startedAt {
                    Text(startedAt, style: .timer)
                        .font(Organic.Font.tabular(.semibold, size: 14))
                        .foregroundStyle(Organic.Color.text)
                }
                Spacer()
                Text(
                    coordinator.health.routeDescription.isEmpty
                        ? "Recording route pending" : coordinator.health.routeDescription
                )
                .organic(.small)
                .lineLimit(1)
                if case .recording = coordinator.phase {
                    Button("Stop") { Task { await coordinator.stop() } }
                        .buttonStyle(.organicPrimary)
                        .accessibilityIdentifier("recordingGlobalStopButton")
                }
            }
            .padding(.horizontal, Organic.Space.p24)
            .padding(.vertical, 10)
            .background(Organic.Color.sidebarBg)
            .overlay(alignment: .top) {
                Rectangle().fill(Organic.Color.divider).frame(height: 1)
            }
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

/// The four things preflight verifies, shown as the "Preflight and consent" rows.
private enum RecordingPreflightCheck: CaseIterable {
    case microphone, screenRecording, display, disk

    var title: String {
        switch self {
        case .microphone: "Microphone access and audio route"
        case .screenRecording: "Screen Recording access"
        case .display: "Shareable display"
        case .disk: "Disk reserve"
        }
    }
}

extension RecordingPreflightFailure {
    fileprivate var check: RecordingPreflightCheck {
        switch self {
        case .microphonePermissionDenied, .microphonePermissionRestricted,
            .microphonePermissionNotDetermined, .microphoneMissing, .microphoneInUse,
            .routeUnavailable:
            .microphone
        case .screenRecordingPermissionDenied:
            .screenRecording
        case .noShareableDisplay:
            .display
        case .insufficientDiskReserve, .recordingSizeLimitReached, .globalSpoolLimitReached:
            .disk
        }
    }

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
            Organic.Color.accent400
        case .preflighting, .stopping:
            Organic.Color.warning
        case .idle, .blocked, .sealed, .needsAttention:
            Organic.Color.muted
        }
    }
}
