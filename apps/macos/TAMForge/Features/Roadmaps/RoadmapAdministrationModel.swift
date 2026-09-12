import AppKit
import Combine
import Foundation
import UniformTypeIdentifiers

@MainActor
final class RoadmapAdministrationModel: ObservableObject {
    @Published private(set) var selection: RoadmapPackage?
    @Published private(set) var roadmapImport: RoadmapImport?
    @Published private(set) var version: RoadmapVersion?
    @Published private(set) var versions: [RoadmapVersion] = []
    @Published private(set) var isBusy = false
    @Published private(set) var errorMessage: String?
    @Published var approvalConfirmed = false
    /// The scheme editor: a planner proposal, a hand-written scheme, or a reforecast.
    @Published var schemeDraft = ""
    @Published var plannerInstruction = ""
    @Published private(set) var schemeIssues: [String] = []
    @Published private(set) var schemeSummary: RoadmapJSONValue?
    /// The version a reforecast draft belongs to; nil while the draft targets the import.
    @Published private(set) var reforecastTarget: RoadmapVersion?

    private let service: any RoadmapServicing
    private let makeIdempotencyKey: @Sendable () -> String
    private let saveExport: @MainActor (Data, String) async -> Void
    private var idempotencyKey: String?
    private var operation: Task<Void, Never>?
    private var stageGeneration = 0

    init(
        service: any RoadmapServicing,
        makeIdempotencyKey: @escaping @Sendable () -> String = {
            "roadmap-\(UUID().uuidString)"
        },
        saveExport: @escaping @MainActor (Data, String) async -> Void = RoadmapExportSaver.save
    ) {
        self.service = service
        self.makeIdempotencyKey = makeIdempotencyKey
        self.saveExport = saveExport
    }

    func select(_ package: RoadmapPackage) {
        operation?.cancel()
        operation = nil
        stageGeneration += 1
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
        stageGeneration += 1
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
        guard selection != nil, !isBusy else { return }
        operation?.cancel()
        stageGeneration += 1
        let generation = stageGeneration
        operation = Task { [weak self] in await self?.stage(generation: generation) }
    }

    func stage() async {
        guard selection != nil, !isBusy else { return }
        stageGeneration += 1
        await stage(generation: stageGeneration)
    }

    func cancelUpload() {
        guard isBusy, roadmapImport == nil else { return }
        stageGeneration += 1
        operation?.cancel()
        operation = nil
        isBusy = false
        errorMessage = nil
    }

    private func stage(generation: Int) async {
        guard let selection, !isBusy else { return }
        isBusy = true
        errorMessage = nil
        let key = idempotencyKey ?? makeIdempotencyKey()
        idempotencyKey = key
        defer {
            if generation == stageGeneration {
                isBusy = false
                operation = nil
            }
        }
        do {
            let roadmapImport = try await service.stage(package: selection, idempotencyKey: key)
            try Task.checkCancellation()
            guard generation == stageGeneration else { return }
            self.roadmapImport = roadmapImport
        } catch is CancellationError {
        } catch {
            guard generation == stageGeneration else { return }
            errorMessage = message(for: error, month: nil)
        }
    }

    func cancelReview() {
        operation?.cancel()
        operation = nil
        stageGeneration += 1
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

    // MARK: - Scheme: generate, attach, reforecast, export

    var canGenerateScheme: Bool { roadmapImport != nil && !isBusy }
    var canAttachScheme: Bool {
        !schemeDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !isBusy
            && (roadmapImport != nil || reforecastTarget != nil)
    }

    func generateScheme() async {
        guard let roadmapImport, !isBusy else { return }
        reforecastTarget = nil
        await run(month: nil) {
            let proposal = try await self.service.proposeScheme(
                importID: roadmapImport.id, instruction: self.plannerInstruction
            )
            self.take(proposal)
        }
    }

    func proposeReforecast(_ target: RoadmapVersion) async {
        guard !isBusy else { return }
        reforecastTarget = target
        await run(month: nil) {
            let proposal = try await self.service.proposeReforecast(
                versionID: target.id, instruction: self.plannerInstruction
            )
            self.take(proposal)
        }
    }

    /// Stage the draft: a new import from the stored snapshot plus this scheme, which
    /// then goes through the usual review, approval and activation.
    func attachScheme() async {
        guard canAttachScheme else { return }
        let draft = schemeDraft
        await run(month: nil) {
            let staged: RoadmapImport
            if let target = self.reforecastTarget {
                staged = try await self.service.stageReforecast(versionID: target.id, yamlText: draft)
            } else if let roadmapImport = self.roadmapImport {
                staged = try await self.service.stageScheme(importID: roadmapImport.id, yamlText: draft)
            } else {
                return
            }
            self.roadmapImport = staged
            self.version = nil
            self.approvalConfirmed = false
            self.reforecastTarget = nil
            if staged.isValidated { self.schemeIssues = [] }
        }
    }

    func exportVersion(_ target: RoadmapVersion) async {
        guard !isBusy else { return }
        await run(month: nil) {
            let data = try await self.service.exportVersion(versionID: target.id)
            await self.saveExport(data, "\(target.versionKey)-v\(target.versionNumber).zip")
        }
    }

    private func take(_ proposal: SchemeProposal) {
        schemeDraft = proposal.yamlText
        schemeIssues = proposal.issues
        schemeSummary = proposal.accepted ? proposal.summary : nil
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
        if case let .problem(statusCode, code) = error as? RoadmapServiceError {
            if code == "planner_unavailable" {
                return "The planner needs Claude enabled on the server."
            }
            if code == "invalid_roadmap_scheme" {
                return "The scheme is not valid YAML. Fix the draft and try again."
            }
            if statusCode == 409, let month, month > 1 {
                return "Month \(month) remains locked until the previous month exit review is complete and eligible."
            }
        }
        if error is RoadmapPackageError {
            return "The selected package could not be prepared. Choose another export and try again."
        }
        return "The roadmap operation could not be completed. Please try again."
    }
}

@MainActor
enum RoadmapExportSaver {
    /// A save panel for the exported package: a readable copy, never the source of truth.
    static func save(_ data: Data, suggestedName: String) async {
        let panel = NSSavePanel()
        panel.title = "Export roadmap package"
        panel.nameFieldStringValue = suggestedName
        panel.allowedContentTypes = [.zip]
        panel.canCreateDirectories = true
        guard await panel.begin() == .OK, let url = panel.url else { return }
        try? data.write(to: url, options: .atomic)
    }
}
