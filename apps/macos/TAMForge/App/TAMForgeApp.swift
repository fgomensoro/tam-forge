import SwiftUI

@main
struct TAMForgeApp: App {
    let dependencies: AppDependencies

    init() {
        self.init(
            dependencies: .live(
                environment: .selected(from: ProcessInfo.processInfo.environment)
            )
        )
    }

    init(dependencies: AppDependencies) {
        self.dependencies = dependencies
    }

    var body: some Scene {
        WindowGroup {
            NativeShellView(dependencies: dependencies)
        }
    }
}

private struct NativeShellView: View {
    let dependencies: AppDependencies
    @State private var statusMessage: String

    init(dependencies: AppDependencies) {
        self.dependencies = dependencies
        _statusMessage = State(initialValue: ServiceStatus.unavailable.diagnosticText)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("TAM Forge")
                .font(.largeTitle)
                .accessibilityIdentifier("shellTitle")

            Text(dependencies.environment.displayName)
                .accessibilityIdentifier("environmentLabel")

            Text("Your native study workspace will appear here.")

            Text(statusMessage)
                .accessibilityIdentifier("serviceStatus")

            Button("Check connection") {
                Task {
                    statusMessage = await dependencies.status.currentStatus().diagnosticText
                }
            }
            .accessibilityIdentifier("connectionCheckButton")
            .keyboardShortcut(.defaultAction)
        }
        .padding(24)
        .frame(minWidth: 480, minHeight: 280)
    }
}
