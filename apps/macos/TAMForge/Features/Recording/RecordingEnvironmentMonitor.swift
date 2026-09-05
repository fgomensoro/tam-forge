import AppKit
import AVFoundation
import CoreAudio
import Foundation

enum RecordingEnvironmentEvent: Sendable {
    case permissionLost
    case inputDeviceChanged(route: String)
    case outputRouteChanged(route: String)
    case willSleep
}

protocol RecordingEnvironmentMonitoring: Sendable {
    func events() -> AsyncStream<RecordingEnvironmentEvent>
}

// Emits machine events only. The route string is the same bounded device name
// the preflight already shows. Nothing here touches crypto, spool, upload, or
// recovery state: the coordinator consumes the stream on its single writer path.
struct LiveRecordingEnvironmentMonitor: RecordingEnvironmentMonitoring {
    func events() -> AsyncStream<RecordingEnvironmentEvent> {
        AsyncStream { continuation in
            let subscription = LiveEnvironmentSubscription(continuation)
            continuation.onTermination = { _ in subscription.cancel() }
        }
    }
}

private final class LiveEnvironmentSubscription: @unchecked Sendable {
    private var observers: [(NotificationCenter, any NSObjectProtocol)] = []
    private var listeners: [(AudioObjectPropertyAddress, AudioObjectPropertyListenerBlock)] = []

    init(_ continuation: AsyncStream<RecordingEnvironmentEvent>.Continuation) {
        observe(NSWorkspace.shared.notificationCenter, NSWorkspace.willSleepNotification) { _ in
            continuation.yield(.willSleep)
        }
        // Permission can only be revoked outside the app; re-check when it
        // returns to the foreground.
        observe(.default, NSApplication.didBecomeActiveNotification) { _ in
            guard !Self.permissionsGranted else { return }
            continuation.yield(.permissionLost)
        }
        // Connecting a device never loses the environment; a plain plug-in is
        // ignored. ponytail: any audio-device disconnect stops, not only the
        // selected microphone; narrow to the captured uniqueID if the runtime
        // window shows unrelated unplugs ending recordings.
        observe(.default, AVCaptureDevice.wasDisconnectedNotification) { notification in
            guard let device = notification.object as? AVCaptureDevice,
                  device.hasMediaType(.audio)
            else { return }
            continuation.yield(Self.deviceEvent(kAudioHardwarePropertyDefaultInputDevice))
        }
        listen(kAudioHardwarePropertyDefaultInputDevice) {
            continuation.yield(Self.deviceEvent(kAudioHardwarePropertyDefaultInputDevice))
        }
        listen(kAudioHardwarePropertyDefaultOutputDevice) {
            continuation.yield(Self.deviceEvent(kAudioHardwarePropertyDefaultOutputDevice))
        }
    }

    func cancel() {
        for (center, observer) in observers { center.removeObserver(observer) }
        observers.removeAll()
        for (address, block) in listeners {
            var address = address
            AudioObjectRemovePropertyListenerBlock(
                AudioObjectID(kAudioObjectSystemObject), &address, .main, block
            )
        }
        listeners.removeAll()
    }

    private func observe(
        _ center: NotificationCenter,
        _ name: Notification.Name,
        _ handler: @escaping @Sendable (Notification) -> Void
    ) {
        observers.append((center, center.addObserver(forName: name, object: nil, queue: nil, using: handler)))
    }

    private func listen(
        _ selector: AudioObjectPropertySelector,
        _ handler: @escaping @Sendable () -> Void
    ) {
        var address = AudioObjectPropertyAddress(
            mSelector: selector,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        let block: AudioObjectPropertyListenerBlock = { _, _ in handler() }
        guard AudioObjectAddPropertyListenerBlock(
            AudioObjectID(kAudioObjectSystemObject), &address, .main, block
        ) == noErr else { return }
        listeners.append((address, block))
    }

    private static var permissionsGranted: Bool {
        AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
            && CGPreflightScreenCaptureAccess()
    }

    private static func deviceEvent(
        _ selector: AudioObjectPropertySelector
    ) -> RecordingEnvironmentEvent {
        guard permissionsGranted else { return .permissionLost }
        let route = defaultDeviceName(selector)
        return selector == kAudioHardwarePropertyDefaultOutputDevice
            ? .outputRouteChanged(route: route)
            : .inputDeviceChanged(route: route)
    }

    private static func defaultDeviceName(_ selector: AudioObjectPropertySelector) -> String {
        var address = AudioObjectPropertyAddress(
            mSelector: selector,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var deviceID = AudioObjectID(kAudioObjectUnknown)
        var size = UInt32(MemoryLayout<AudioObjectID>.size)
        guard AudioObjectGetPropertyData(
            AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size, &deviceID
        ) == noErr, deviceID != kAudioObjectUnknown else { return "No audio device" }
        address.mSelector = kAudioObjectPropertyName
        var name: Unmanaged<CFString>?
        size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
        guard AudioObjectGetPropertyData(deviceID, &address, 0, nil, &size, &name) == noErr,
              let name
        else { return "Unknown audio device" }
        return name.takeRetainedValue() as String
    }
}
