import Combine
import Foundation

@MainActor
final class RoadmapAdministrationModel: ObservableObject {
    @Published private(set) var selection: RoadmapPackage?
    @Published private(set) var roadmapImport: RoadmapImport?
    @Published private(set) var version: RoadmapVersion?
    @Published private(set) var versions: [RoadmapVersion] = []
    @Published private(set) var isBusy = false
    @Published private(set) var errorMessage: String?
    @Published var approvalConfirmed = false

    private let service: any RoadmapServicing
    private let makeIdempotencyKey: @Sendable () -> String
    private var idempotencyKey: String?
    private var operation: Task<Void, Never>?

    init(
        service: any RoadmapServicing,
        makeIdempotencyKey: @escaping @Sendable () -> String = {
            "roadmap-\(UUID().uuidString)"
        }
    ) {
        self.service = service
        self.makeIdempotencyKey = makeIdempotencyKey
    }

    func select(_ package: RoadmapPackage) {
        operation?.cancel()
        operation = nil
        selection = package
        roadmapImport = nil
        version = nil
        idempotencyKey = makeIdempotencyKey()
        approvalConfirmed = false
        errorMessage = nil
        isBusy = false
    }

    func choosePackage() {
        operation?.cancel()
        operation = Task { [weak self] in
            do {
                guard let package = try await RoadmapPackagePicker.select() else { return }
                guard let self else { return }
                self.operation = nil
                self.select(package)
            } catch is CancellationError {
            } catch {
                self?.errorMessage = "The selected package could not be prepared. Choose another export and try again."
            }
        }
    }

    func beginStage() {
        operation?.cancel()
        operation = Task { [weak self] in await self?.stage() }
    }

    func stage() async {
        guard let selection, !isBusy else { return }
        isBusy = true
        errorMessage = nil
        let key = idempotencyKey ?? makeIdempotencyKey()
        idempotencyKey = key
        defer { isBusy = false }
        do {
            roadmapImport = try await service.stage(package: selection, idempotencyKey: key)
        } catch is CancellationError {
        } catch {
            errorMessage = message(for: error, month: nil)
        }
    }

    func cancelReview() {
        operation?.cancel()
        operation = nil
        selection = nil
        roadmapImport = nil
        version = nil
        idempotencyKey = nil
        approvalConfirmed = false
        errorMessage = nil
        isBusy = false
    }

    func approve() async {
        guard let roadmapImport, roadmapImport.isValidated, approvalConfirmed, !isBusy else { return }
        await run(month: nil) {
            let version = try await self.service.approve(importID: roadmapImport.id)
            self.record(version)
        }
    }

    func retryMirror(_ target: RoadmapVersion? = nil) async {
        guard let target = target ?? version, target.mirrorStatus == "failed", !isBusy else { return }
        await run(month: target.monthNumber) {
            self.record(try await self.service.retryMirror(versionID: target.id))
        }
    }

    func activate(_ target: RoadmapVersion? = nil) async {
        guard let target = target ?? version, target.canActivate, !isBusy else { return }
        await run(month: target.monthNumber) {
            self.record(try await self.service.activate(versionID: target.id))
        }
    }

    func loadHistory() async {
        guard !isBusy else { return }
        isBusy = true
        defer { isBusy = false }
        do {
            versions = try await service.listVersions()
        } catch is CancellationError {
        } catch {
            errorMessage = message(for: error, month: nil)
        }
    }

    private func run(month: Int?, _ action: () async throws -> Void) async {
        isBusy = true
        errorMessage = nil
        defer { isBusy = false }
        do {
            try await action()
        } catch is CancellationError {
        } catch {
            errorMessage = message(for: error, month: month)
        }
    }

    private func record(_ next: RoadmapVersion) {
        version = next
        versions = [next] + versions.filter { $0.id != next.id }
    }

    private func message(for error: Error, month: Int?) -> String {
        if case let .problem(statusCode, _) = error as? RoadmapServiceError,
           statusCode == 409,
           let month,
           month > 1 {
            return "Month \(month) remains locked until the previous month exit review is complete and eligible."
        }
        if error is RoadmapPackageError {
            return "The selected package could not be prepared. Choose another export and try again."
        }
        return "The roadmap operation could not be completed. Please try again."
    }
}
