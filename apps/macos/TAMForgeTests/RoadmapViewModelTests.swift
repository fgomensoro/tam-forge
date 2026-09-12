import Foundation
import XCTest

@MainActor
final class RoadmapViewModelTests: XCTestCase {
    func testReviewApprovalMirrorRetryAndActivationJourneyRequiresExplicitApproval() async throws {
        let importResponse = validImport()
        let failedMirror = version(month: 2, state: "approved", mirrorStatus: "failed")
        let syncedMirror = version(month: 2, state: "approved", mirrorStatus: "synced")
        let active = version(month: 2, state: "active", mirrorStatus: "synced")
        let service = RoadmapServiceFixture(
            stages: [.success(importResponse)],
            approved: failedMirror,
            retried: syncedMirror,
            activated: active
        )
        let model = RoadmapAdministrationModel(service: service)
        model.select(try package())

        await model.stage()
        await model.approve()
        let approvalCalls = await service.approvalCalls
        XCTAssertEqual(approvalCalls, 0)

        model.approvalConfirmed = true
        await model.approve()
        XCTAssertEqual(model.version, failedMirror)
        XCTAssertEqual(model.version?.state, "approved")
        XCTAssertEqual(model.version?.mirrorStatus, "failed")

        await model.retryMirror()
        XCTAssertEqual(model.version, syncedMirror)
        await model.activate()
        XCTAssertEqual(model.version, active)
        XCTAssertTrue(model.errorMessage == nil)
    }

    func testStageRetryKeepsIdempotencyKeyAfterTransientFailure() async throws {
        let service = RoadmapServiceFixture(
            stages: [.failure(.unavailable), .success(validImport())],
            approved: version(month: 1, state: "approved", mirrorStatus: "not_required"),
            retried: version(month: 1, state: "approved", mirrorStatus: "not_required"),
            activated: version(month: 1, state: "active", mirrorStatus: "not_required")
        )
        let model = RoadmapAdministrationModel(service: service)
        model.select(try package())

        await model.stage()
        XCTAssertNotNil(model.errorMessage)
        await model.stage()

        let keys = await service.stageKeys
        XCTAssertEqual(keys.count, 2)
        XCTAssertEqual(keys[0], keys[1])
        XCTAssertEqual(model.roadmapImport, validImport())
    }

    func testCancellationKeepsSelectionAndDoesNotInventFailure() async throws {
        let service = RoadmapServiceFixture(
            stages: [.failure(.cancelled)],
            approved: version(month: 1, state: "approved", mirrorStatus: "not_required"),
            retried: version(month: 1, state: "approved", mirrorStatus: "not_required"),
            activated: version(month: 1, state: "active", mirrorStatus: "not_required")
        )
        let model = RoadmapAdministrationModel(service: service)
        model.select(try package())

        await model.stage()

        XCTAssertNotNil(model.selection)
        XCTAssertNil(model.roadmapImport)
        XCTAssertNil(model.errorMessage)
        XCTAssertFalse(model.isBusy)
    }

    func testCancelUploadPreservesRetrySelectionAndKeyAndIgnoresLateCompletion() async throws {
        let started = expectation(description: "first upload started")
        let startedBox = RoadmapExpectationBox(started)
        let response = validImport()
        let service = DelayedRoadmapService(response: response) { startedBox.fulfill() }
        let model = RoadmapAdministrationModel(service: service, makeIdempotencyKey: { "roadmap-stable-key" })
        model.select(try package())

        model.beginStage()
        await fulfillment(of: [started], timeout: 1)
        model.cancelUpload()

        XCTAssertNotNil(model.selection)
        XCTAssertFalse(model.isBusy)
        XCTAssertNil(model.errorMessage)

        await service.finishFirstStage()
        await Task.yield()
        XCTAssertNil(model.roadmapImport)

        await model.stage()

        let keys = await service.stageKeys
        XCTAssertEqual(keys, ["roadmap-stable-key", "roadmap-stable-key"])
        XCTAssertEqual(model.roadmapImport, response)
    }

    func testDuplicateBeginStageWhileBusyKeepsOriginalUploadAndBusyState() async throws {
        let started = expectation(description: "first upload started")
        let startedBox = RoadmapExpectationBox(started)
        let response = validImport()
        let service = DelayedRoadmapService(response: response) { startedBox.fulfill() }
        let model = RoadmapAdministrationModel(service: service, makeIdempotencyKey: { "roadmap-stable-key" })
        model.select(try package())

        model.beginStage()
        await fulfillment(of: [started], timeout: 1)
        model.beginStage()
        await Task.yield()

        XCTAssertTrue(model.isBusy)
        let stageKeys = await service.stageKeys
        XCTAssertEqual(stageKeys, ["roadmap-stable-key"])

        await service.finishFirstStage()
        await Task.yield()

        XCTAssertEqual(model.roadmapImport, response)
        XCTAssertFalse(model.isBusy)
    }

    func testSemanticDiffPresentationKeepsDefaultPreviewBounded() {
        let section = semanticDiffSection(entries: 13, fields: 9, valueCharacters: 281)

        let entries = RoadmapSemanticDiffPresentation.changedEntries(in: section)

        XCTAssertEqual(entries.count, RoadmapSemanticDiffPresentation.maximumEntriesPerSection)
        XCTAssertEqual(entries.first?.fields.count, RoadmapSemanticDiffPresentation.maximumFieldsPerEntry)
        XCTAssertEqual(entries.first?.fields.first?.before.count, RoadmapSemanticDiffPresentation.maximumValueCharacters)
        XCTAssertEqual(entries.first?.fields.first?.after.count, RoadmapSemanticDiffPresentation.maximumValueCharacters)
        XCTAssertTrue(RoadmapSemanticDiffPresentation.hasMoreEntries(in: section))
    }

    func testSemanticDiffPresentationExpandedEntriesKeepAllServerValues() {
        let section = semanticDiffSection(entries: 13, fields: 9, valueCharacters: 281)

        let entries = RoadmapSemanticDiffPresentation.allChangedEntries(in: section)

        XCTAssertEqual(entries.count, 13)
        XCTAssertEqual(entries.first?.fields.count, 9)
        XCTAssertEqual(entries.first?.fields.first?.before, String(repeating: "before", count: 281))
        XCTAssertEqual(entries.first?.fields.first?.after, String(repeating: "after", count: 281))
        XCTAssertEqual(entries.last?.key, "change-12")
    }

    func testAddedAndRemovedTaskPayloadsPreservePreviewLimitsAndFullObjectiveAndTimebox() {
        let objective = String(repeating: "Inspect the complete assignment. ", count: 20)
        let payload: [String: RoadmapJSONValue] = [
            "stable_id": .string("m1-w1-d01-sql"),
            "month": .integer(1),
            "week": .integer(1),
            "day": .integer(1),
            "block": .string("practice"),
            "order": .integer(1),
            "source_path": .string("sql/tasks.md"),
            "source_heading": .string("SQL practice"),
            "exercise_type": .string("sql"),
            "mapping_version": .string("v1"),
            "required": .bool(true),
            "timebox_minutes": .integer(45),
            "objective": .string(objective),
            "allowed_ai_role": .string("review_only"),
        ]

        for status in ["added", "removed"] {
            let section = semanticDiffPayloadSection(status: status, payload: payload, entries: 13)
            let preview = RoadmapSemanticDiffPresentation.changedEntries(in: section)
            let expanded = RoadmapSemanticDiffPresentation.allChangedEntries(in: section)
            let expectedObjective = RoadmapSemanticDiffField(
                name: "objective", label: "Assignment",
                before: status == "removed" ? objective : "None",
                after: status == "added" ? objective : "None"
            )

            XCTAssertEqual(preview.count, 12, status)
            XCTAssertEqual(preview.first?.fields.count, 8, status)
            let previewObjective = preview.first?.fields.first { $0.name == "objective" }
            XCTAssertEqual(previewObjective?.before, String(expectedObjective.before.prefix(280)), status)
            XCTAssertEqual(previewObjective?.after, String(expectedObjective.after.prefix(280)), status)
            XCTAssertEqual(expanded.count, 13, status)
            XCTAssertEqual(Set(expanded.first?.fields.map(\.name) ?? []), Set(payload.keys), status)
            XCTAssertEqual(expanded.last?.fields.first { $0.name == "objective" }, expectedObjective, status)
            XCTAssertEqual(
                expanded.last?.fields.first { $0.name == "timebox_minutes" },
                RoadmapSemanticDiffField(
                    name: "timebox_minutes", label: "Timebox",
                    before: status == "removed" ? "45" : "None",
                    after: status == "added" ? "45" : "None"
                ),
                status
            )
        }
    }

    func testAddedAndRemovedPassContractPayloadsExposeFullRequiredOutputAndPassCriteria() {
        let output = String(repeating: "Include the complete query and result. ", count: 20)
        let criteria = String(repeating: "Explain every join and verify the result. ", count: 20)
        let payload: [String: RoadmapJSONValue] = [
            "stable_id": .string("m1-w1-d01-sql"),
            "required_output": .array([.string("SQL query"), .string(output)]),
            "pass_criteria": .array([.string("Correct result"), .string(criteria)]),
            "evidence_requirements": .array([.string("Self-review")]),
            "procedure": .array([]),
            "constraints": .array([]),
            "correction_selection": .null,
        ]

        for status in ["added", "removed"] {
            let section = semanticDiffPayloadSection(status: status, payload: payload)
            let preview = RoadmapSemanticDiffPresentation.changedEntries(in: section)
            let expanded = RoadmapSemanticDiffPresentation.allChangedEntries(in: section)

            XCTAssertEqual(expanded.count, 1, status)
            XCTAssertEqual(Set(expanded.first?.fields.map(\.name) ?? []), Set(payload.keys), status)
            for (name, label, value) in [
                ("required_output", "Required output", "SQL query · \(output)"),
                ("pass_criteria", "Pass criteria", "Correct result · \(criteria)"),
            ] {
                let expected = RoadmapSemanticDiffField(
                    name: name, label: label,
                    before: status == "removed" ? value : "None",
                    after: status == "added" ? value : "None"
                )
                let previewField = preview.first?.fields.first { $0.name == name }
                XCTAssertEqual(previewField?.before, String(expected.before.prefix(280)), status)
                XCTAssertEqual(previewField?.after, String(expected.after.prefix(280)), status)
                XCTAssertEqual(expanded.first?.fields.first { $0.name == name }, expected, status)
            }
        }
    }

    func testGeneratedRoadmapImportMapsDynamicValuesWithoutJSONRoundTrip() throws {
        let wire = try NativeJSONCodec.decode(
            Components.Schemas.RoadmapImportResponse.self,
            from: Data("""
            {
              "id":17,
              "status":"validated",
              "validation_report":{"accepted":true,"count":2,"ratio":1.25,"missing":null,"list":["x",3],"nested":{"enabled":false}},
              "semantic_diff":{"summary":{"changed":1}},
              "failure_code":null
            }
            """.utf8)
        )

        let roadmapImport = try RoadmapImport(wire: wire)

        XCTAssertEqual(roadmapImport.validationReport.objectValue?["accepted"], .bool(true))
        XCTAssertEqual(roadmapImport.validationReport.objectValue?["count"], .integer(2))
        XCTAssertEqual(roadmapImport.validationReport.objectValue?["ratio"], .number(1.25))
        XCTAssertEqual(roadmapImport.validationReport.objectValue?["missing"], .null)
        XCTAssertEqual(roadmapImport.validationReport.objectValue?["list"], .array([.string("x"), .integer(3)]))
        XCTAssertEqual(roadmapImport.validationReport.objectValue?["nested"], .object(["enabled": .bool(false)]))
        XCTAssertTrue(roadmapImport.isValidated)
    }

    func testGeneratedRoadmapVersionMapsToLocalDomain() throws {
        let wire = try NativeJSONCodec.decode(
            Components.Schemas.RoadmapVersionResponse.self,
            from: Data("""
            {"id":5,"version_key":"m2-v1","version_number":1,"month_number":2,"state":"approved","mirror_status":"synced","mirror_ref":"refs/heads/main","mirror_error_code":null}
            """.utf8)
        )

        let version = RoadmapVersion(wire: wire)

        XCTAssertEqual(version.id, 5)
        XCTAssertEqual(version.versionKey, "m2-v1")
        XCTAssertEqual(version.monthNumber, 2)
        XCTAssertTrue(version.canActivate)
        XCTAssertEqual(version.mirrorRef, "refs/heads/main")
    }

    func testActivationConflictTellsUserThatEarlierMonthExitReviewBlocksActivation() async throws {
        let importResponse = validImport()
        let approved = version(month: 2, state: "approved", mirrorStatus: "synced")
        let service = RoadmapServiceFixture(
            stages: [.success(importResponse)],
            approved: approved,
            retried: approved,
            activated: approved,
            activationFailure: .activationConflict
        )
        let model = RoadmapAdministrationModel(service: service)
        model.select(try package())
        await model.stage()
        model.approvalConfirmed = true
        await model.approve()

        await model.activate()

        XCTAssertEqual(
            model.errorMessage,
            "Month 2 remains locked until the previous month exit review is complete and eligible."
        )
        XCTAssertEqual(model.version?.state, "approved")
    }

    func testGenerateStoresTheProposalAsTheDraftAndAttachingStagesANewImport() async throws {
        let service = RoadmapServiceFixture(
            stages: [.success(validImport())],
            approved: version(month: 1, state: "approved", mirrorStatus: "not_required"),
            retried: version(month: 1, state: "approved", mirrorStatus: "not_required"),
            activated: version(month: 1, state: "active", mirrorStatus: "not_required")
        )
        let proposal = SchemeProposal(
            yamlText: "schema_version: 1\n",
            summary: .object(["program": .string("Demo"), "study_days": .integer(2)]),
            issues: []
        )
        let staged = RoadmapImport(
            id: 18,
            status: "validated",
            validationReport: .object([
                "accepted": .bool(true),
                "issues": .array([]),
                "scheme_summary": .object(["program": .string("Demo"), "study_days": .integer(2)]),
            ]),
            semanticDiff: .object(["summary": .object(["added": .number(4)])]),
            failureCode: nil
        )
        await service.configure(proposal: proposal, schemeImport: staged)
        let model = RoadmapAdministrationModel(service: service)
        model.select(try package())
        await model.stage()
        model.plannerInstruction = "three hours a day"

        await model.generateScheme()

        XCTAssertEqual(model.schemeDraft, "schema_version: 1\n")
        XCTAssertEqual(model.schemeIssues, [])
        XCTAssertEqual(model.schemeSummary?.objectValue?["study_days"]?.integerValue, 2)
        let instructions = await service.proposalInstructions
        XCTAssertEqual(instructions, ["three hours a day"])
        XCTAssertTrue(model.canAttachScheme)

        await model.attachScheme()

        XCTAssertEqual(model.roadmapImport?.id, 18)
        XCTAssertTrue(model.roadmapImport?.isValidated == true)
        let stagedSchemes = await service.stagedSchemes
        XCTAssertEqual(stagedSchemes, ["schema_version: 1\n"])
        XCTAssertNil(model.errorMessage)
    }

    func testRefusedProposalKeepsItsIssuesAndPlannerUnavailableIsActionable() async throws {
        let service = RoadmapServiceFixture(
            stages: [.success(validImport())],
            approved: version(month: 1, state: "approved", mirrorStatus: "not_required"),
            retried: version(month: 1, state: "approved", mirrorStatus: "not_required"),
            activated: version(month: 1, state: "active", mirrorStatus: "not_required")
        )
        await service.configure(
            proposal: SchemeProposal(yamlText: "days: []\n", summary: .object([:]), issues: ["day 'x' is over budget"])
        )
        let model = RoadmapAdministrationModel(service: service)
        model.select(try package())
        await model.stage()

        await model.generateScheme()
        XCTAssertEqual(model.schemeIssues, ["day 'x' is over budget"])
        XCTAssertNil(model.schemeSummary)
        XCTAssertEqual(model.schemeDraft, "days: []\n")

        await service.configure(proposalError: .problem(statusCode: 503, code: "planner_unavailable"))
        await model.generateScheme()
        XCTAssertEqual(model.errorMessage, "The planner needs Claude enabled on the server.")
    }

    func testReforecastTargetsTheActiveVersionAndExportHandsTheBytesToTheSaver() async throws {
        let active = version(month: 1, state: "active", mirrorStatus: "not_required")
        let service = RoadmapServiceFixture(
            stages: [],
            approved: active,
            retried: active,
            activated: active
        )
        await service.configure(
            proposal: SchemeProposal(yamlText: "schema_version: 1\n", summary: .object([:]), issues: []),
            schemeImport: validImport()
        )
        let saved = RoadmapSavedExportBox()
        let model = RoadmapAdministrationModel(
            service: service,
            saveExport: { data, name in saved.record(data: data, name: name) }
        )

        await model.proposeReforecast(active)
        XCTAssertEqual(model.reforecastTarget, active)
        XCTAssertTrue(model.canAttachScheme)
        await model.attachScheme()
        XCTAssertNil(model.reforecastTarget)
        XCTAssertEqual(model.roadmapImport, validImport())

        await model.exportVersion(active)
        XCTAssertEqual(saved.names, ["month-1-v1-v1.zip"])
        XCTAssertEqual(saved.payloads.first, Data("PK-fixture".utf8))
        let exported = await service.exportedVersions
        XCTAssertEqual(exported, [8])
    }

    private func package() throws -> RoadmapPackage {
        let fileURL = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try Data("redacted roadmap".utf8).write(to: fileURL)
        addTeardownBlock { try? FileManager.default.removeItem(at: fileURL) }
        return .zip(try RoadmapLocalFile(url: fileURL, maximumBytes: 1024))
    }

    private func validImport() -> RoadmapImport {
        RoadmapImport(
            id: 17,
            status: "validated",
            validationReport: .object([
                "accepted": .bool(true),
                "normalized_hash": .string(String(repeating: "a", count: 64)),
                "task_count": .number(158),
                "resource_count": .number(12),
                "exit_criterion_count": .number(5),
                "issues": .array([]),
            ]),
            semanticDiff: .object(["summary": .object(["added": .number(158)])]),
            failureCode: nil
        )
    }

    private func version(month: Int, state: String, mirrorStatus: String) -> RoadmapVersion {
        RoadmapVersion(
            id: 8,
            versionKey: "month-\(month)-v1",
            versionNumber: 1,
            monthNumber: month,
            state: state,
            mirrorStatus: mirrorStatus,
            mirrorRef: mirrorStatus == "synced" ? "redacted-ref" : nil,
            mirrorErrorCode: mirrorStatus == "failed" ? "write_failed" : nil
        )
    }

    private func semanticDiffSection(entries: Int, fields: Int, valueCharacters: Int) -> RoadmapJSONValue {
        let fields = (0 ..< fields).map { index in
            RoadmapJSONValue.object([
                "name": .string("field_\(index)"),
                "before": .string(String(repeating: "before", count: valueCharacters)),
                "after": .string(String(repeating: "after", count: valueCharacters)),
            ])
        }
        return .object([
            "entries": .array((0 ..< entries).map { index in
                .object([
                    "key": .string("change-\(index)"),
                    "status": .string("changed"),
                    "fields": .array(fields),
                ])
            }),
        ])
    }

    private func semanticDiffPayloadSection(
        status: String, payload: [String: RoadmapJSONValue], entries: Int = 1
    ) -> RoadmapJSONValue {
        .object([
            "entries": .array((0 ..< entries).map { index in
                .object([
                    "key": .string("payload-\(index)"),
                    "status": .string(status),
                    "fields": .array([]),
                    "before": status == "removed" ? .object(payload) : .null,
                    "after": status == "added" ? .object(payload) : .null,
                ])
            }),
        ])
    }
}

private actor RoadmapServiceFixture: RoadmapServicing {
    private var stages: [StageOutcome]
    private let approved: RoadmapVersion
    private let retried: RoadmapVersion
    private let activated: RoadmapVersion
    private let activationFailure: FixtureError?
    private(set) var stageKeys: [String] = []
    private(set) var approvalCalls = 0

    init(
        stages: [StageOutcome],
        approved: RoadmapVersion,
        retried: RoadmapVersion,
        activated: RoadmapVersion,
        activationFailure: FixtureError? = nil
    ) {
        self.stages = stages
        self.approved = approved
        self.retried = retried
        self.activated = activated
        self.activationFailure = activationFailure
    }

    func stage(package _: RoadmapPackage, idempotencyKey: String) async throws -> RoadmapImport {
        stageKeys.append(idempotencyKey)
        switch stages.removeFirst() {
        case let .success(value): return value
        case .failure(.cancelled): throw CancellationError()
        case let .failure(error): throw error
        }
    }

    func approve(importID _: Int) async throws -> RoadmapVersion {
        approvalCalls += 1
        return approved
    }

    func retryMirror(versionID _: Int) async throws -> RoadmapVersion { retried }
    func activate(versionID _: Int) async throws -> RoadmapVersion {
        if activationFailure == .activationConflict {
            throw RoadmapServiceError.problem(statusCode: 409, code: "roadmap_state_conflict")
        }
        if let activationFailure { throw activationFailure }
        return activated
    }
    func listVersions() async throws -> [RoadmapVersion] { [] }

    var proposal: SchemeProposal?
    var proposalError: RoadmapServiceError?
    var schemeImport: RoadmapImport?
    private(set) var proposalInstructions: [String] = []
    private(set) var stagedSchemes: [String] = []
    private(set) var exportedVersions: [Int] = []

    func configure(
        proposal: SchemeProposal? = nil,
        proposalError: RoadmapServiceError? = nil,
        schemeImport: RoadmapImport? = nil
    ) {
        self.proposal = proposal
        self.proposalError = proposalError
        self.schemeImport = schemeImport
    }

    func proposeScheme(importID _: Int, instruction: String) async throws -> SchemeProposal {
        proposalInstructions.append(instruction)
        if let proposalError { throw proposalError }
        guard let proposal else { throw RoadmapServiceError.invalidResponse }
        return proposal
    }

    func stageScheme(importID _: Int, yamlText: String) async throws -> RoadmapImport {
        stagedSchemes.append(yamlText)
        guard let schemeImport else { throw RoadmapServiceError.invalidResponse }
        return schemeImport
    }

    func proposeReforecast(versionID _: Int, instruction: String) async throws -> SchemeProposal {
        try await proposeScheme(importID: 0, instruction: instruction)
    }

    func stageReforecast(versionID _: Int, yamlText: String) async throws -> RoadmapImport {
        try await stageScheme(importID: 0, yamlText: yamlText)
    }

    func exportVersion(versionID: Int) async throws -> Data {
        exportedVersions.append(versionID)
        return Data("PK-fixture".utf8)
    }
}

private enum StageOutcome: Sendable {
    case success(RoadmapImport)
    case failure(FixtureError)
}

private enum FixtureError: Error, Equatable, Sendable {
    case unavailable
    case cancelled
    case activationConflict
}

private actor DelayedRoadmapService: RoadmapServicing {
    private let response: RoadmapImport
    private let onFirstStage: @Sendable () -> Void
    private var firstStageContinuation: CheckedContinuation<RoadmapImport, Never>?
    private var stageCount = 0
    private(set) var stageKeys: [String] = []

    init(response: RoadmapImport, onFirstStage: @escaping @Sendable () -> Void) {
        self.response = response
        self.onFirstStage = onFirstStage
    }

    func stage(package _: RoadmapPackage, idempotencyKey: String) async throws -> RoadmapImport {
        stageKeys.append(idempotencyKey)
        stageCount += 1
        guard stageCount == 1 else { return response }
        return await withCheckedContinuation { continuation in
            firstStageContinuation = continuation
            onFirstStage()
        }
    }

    func finishFirstStage() {
        firstStageContinuation?.resume(returning: response)
        firstStageContinuation = nil
    }

    func approve(importID _: Int) async throws -> RoadmapVersion { fatalError("Unused") }
    func retryMirror(versionID _: Int) async throws -> RoadmapVersion { fatalError("Unused") }
    func activate(versionID _: Int) async throws -> RoadmapVersion { fatalError("Unused") }
    func listVersions() async throws -> [RoadmapVersion] { [] }
    func proposeScheme(importID _: Int, instruction _: String) async throws -> SchemeProposal { fatalError("Unused") }
    func stageScheme(importID _: Int, yamlText _: String) async throws -> RoadmapImport { fatalError("Unused") }
    func proposeReforecast(versionID _: Int, instruction _: String) async throws -> SchemeProposal { fatalError("Unused") }
    func stageReforecast(versionID _: Int, yamlText _: String) async throws -> RoadmapImport { fatalError("Unused") }
    func exportVersion(versionID _: Int) async throws -> Data { fatalError("Unused") }
}

private final class RoadmapExpectationBox: @unchecked Sendable {
    private let expectation: XCTestExpectation

    init(_ expectation: XCTestExpectation) {
        self.expectation = expectation
    }

    func fulfill() {
        expectation.fulfill()
    }
}


@MainActor
private final class RoadmapSavedExportBox {
    private(set) var payloads: [Data] = []
    private(set) var names: [String] = []

    func record(data: Data, name: String) {
        payloads.append(data)
        names.append(name)
    }
}
