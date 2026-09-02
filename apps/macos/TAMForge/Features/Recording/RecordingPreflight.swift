import AVFoundation
import CoreGraphics
import Foundation
import ScreenCaptureKit

struct LiveRecordingPreflight: RecordingPreflighting {
    let preferredMicrophoneID: @Sendable () -> String?
    let spoolRootURL: URL

    init(
        preferredMicrophoneID: @escaping @Sendable () -> String? = { nil },
        spoolRootURL: URL = EncryptedRecordingSpoolFactory.defaultRootURL()
    ) {
        self.preferredMicrophoneID = preferredMicrophoneID
        self.spoolRootURL = spoolRootURL
    }

    func run() async -> RecordingPreflightResult {
        let microphonePermission = await requestMicrophonePermissionAfterUserAction()
        guard microphonePermission == .authorized else {
            return .blocked(microphonePermission.failure)
        }
        guard CGPreflightScreenCaptureAccess() || CGRequestScreenCaptureAccess() else {
            return .blocked(.screenRecordingPermissionDenied)
        }

        let devices = AVCaptureDevice.DiscoverySession(
            deviceTypes: [.microphone], mediaType: .audio, position: .unspecified
        ).devices.filter(\.isConnected)
        guard !devices.isEmpty else { return .blocked(.microphoneMissing) }
        let selected = preferredMicrophoneID().flatMap { preferred in
            devices.first { $0.uniqueID == preferred }
        } ?? AVCaptureDevice.default(for: .audio) ?? devices[0]
        guard !selected.isSuspended else { return .blocked(.routeUnavailable) }
        if selected.isInUseByAnotherApplication { return .blocked(.microphoneInUse) }

        let content: SCShareableContent
        do {
            content = try await SCShareableContent.excludingDesktopWindows(
                false, onScreenWindowsOnly: false
            )
        } catch {
            return .blocked(.screenRecordingPermissionDenied)
        }
        guard !content.displays.isEmpty else { return .blocked(.noShareableDisplay) }

        let availableBytes: Int64
        do {
            // The spool directory may not exist before the first recording;
            // measure the volume through the home directory, which always
            // exists on the same user data volume.
            let values = try URL(fileURLWithPath: NSHomeDirectory(), isDirectory: true)
                .resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey])
            availableBytes = values.volumeAvailableCapacityForImportantUsage ?? 0
        } catch {
            return .blocked(.insufficientDiskReserve)
        }
        let pendingBytes = Self.pendingSpoolBytes(at: spoolRootURL)
        if let failure = RecordingDiskPolicy.failure(
            availableBytes: availableBytes,
            pendingGlobalBytes: pendingBytes,
            proposedRecordingBytes: RecordingDiskPolicy.maximumRecordingBytes
        ) {
            return .blocked(failure)
        }

        let microphones = devices.map { RecordingMicrophone(id: $0.uniqueID, name: $0.localizedName) }
        return .ready(.init(
            selectedMicrophone: .init(id: selected.uniqueID, name: selected.localizedName),
            availableMicrophones: microphones,
            displayCount: content.displays.count,
            availableDiskBytes: availableBytes,
            pendingSpoolBytes: pendingBytes,
            routeDescription: selected.localizedName,
            coverageIsProvisional: true
        ))
    }

    private func requestMicrophonePermissionAfterUserAction() async -> AVAuthorizationStatus {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .notDetermined:
            let granted = await AVCaptureDevice.requestAccess(for: .audio)
            return granted ? .authorized : .denied
        case let status:
            return status
        }
    }

    static func pendingSpoolBytes(at spoolRootURL: URL) -> Int64 {
        guard let enumerator = FileManager.default.enumerator(
            at: spoolRootURL,
            includingPropertiesForKeys: [.isRegularFileKey, .fileSizeKey],
            options: []
        ) else { return 0 }
        var total: Int64 = 0
        while let url = enumerator.nextObject() as? URL {
            guard let values = try? url.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey]),
                  values.isRegularFile == true,
                  let bytes = values.fileSize
            else { continue }
            let (next, overflow) = total.addingReportingOverflow(Int64(bytes))
            if overflow { return Int64.max }
            total = next
        }
        return total
    }
}

private extension AVAuthorizationStatus {
    var failure: RecordingPreflightFailure {
        switch self {
        case .denied:
            .microphonePermissionDenied
        case .restricted:
            .microphonePermissionRestricted
        case .notDetermined:
            .microphonePermissionNotDetermined
        case .authorized:
            .microphonePermissionNotDetermined
        @unknown default:
            .microphonePermissionRestricted
        }
    }
}
