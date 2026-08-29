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
