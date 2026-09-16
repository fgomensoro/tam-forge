import Foundation
import XCTest

@MainActor
final class ClassesModelTests: XCTestCase {
    func testCreateSaveAttachAndOpenTranscript() async {
        let api = FakeClassAPI()
        let model = ClassesModel(api: api)
        await model.load()
        XCTAssertTrue(model.classes.isEmpty && model.isCreating)

        model.draft = EnglishClassDraft(teacher: "Maria", startsAt: Date(timeIntervalSince1970: 100), expectedDurationMinutes: 60, notes: "Pacing")
        XCTAssertTrue(model.canSave)
        await model.save()
        XCTAssertEqual(model.selectedID, 3)
        XCTAssertEqual(model.classes.first?.skillSlug, "tam_english")

        model.draft.notes = "Conditionals"
        await model.save()
        XCTAssertEqual(api.calls, ["list", "create", "update:3"])

        let recordingID = UUID()
        await model.attach(recordingID: recordingID)
        XCTAssertEqual(model.selected?.recordings.first?.recordingID, recordingID)
        await model.openTranscript(recordingID: recordingID)
        XCTAssertEqual(model.analysis(for: model.selected!.recordings[0])?.turns.first?.text, "how was your week")
    }

    func testAnEmptyTeacherCannotBeSavedAndProblemsBecomeMessages() async {
        let api = FakeClassAPI()
        api.failure = .unavailable
        let model = ClassesModel(api: api)
        XCTAssertFalse(model.canSave)
        await model.load()
        XCTAssertEqual(model.errorMessage, EnglishClassAPIError.unavailable.message)
    }

    func testTheCreatePayloadCarriesTheClassId() throws {
        let tracks = [RecordingTrackDeclarationPayload(trackID: "t", kind: "microphone", format: .init(channelCount: 1))]
        let data = try RecordingCanonicalJSON.encode(
            RecordingCreatePayload(recordingID: "r", startedAt: "2026-09-16T10:00:00Z", tracks: tracks, classID: 3)
        )
        XCTAssertTrue(String(decoding: data, as: UTF8.self).contains("\"english_class_id\":3"))
    }
}

@MainActor
private final class FakeClassAPI: EnglishClassAPI {
    var records: [EnglishClassRecord] = []
    var failure: EnglishClassAPIError?
    private(set) var calls: [String] = []

    func list() async throws -> [EnglishClassRecord] {
        calls.append("list")
        if let failure { throw failure }
        return records
    }

    func create(_ draft: EnglishClassDraft) async throws -> EnglishClassRecord {
        calls.append("create")
        if let failure { throw failure }
        let record = make(id: 3, draft: draft, recordings: [])
        records.insert(record, at: 0)
        return record
    }

    func update(id: Int, draft: EnglishClassDraft) async throws -> EnglishClassRecord {
        calls.append("update:\(id)")
        if let failure { throw failure }
        let record = make(id: id, draft: draft, recordings: records.first { $0.id == id }?.recordings ?? [])
        records = records.map { $0.id == id ? record : $0 }
        return record
    }

    func attach(recordingID: UUID, to id: Int) async throws -> EnglishClassRecord {
        calls.append("attach")
        let existing = records.first { $0.id == id }!
        let record = make(
            id: id, draft: EnglishClassDraft(record: existing),
            recordings: existing.recordings + [ClassRecordingSummary(recordingID: recordingID, state: "stored", startedAt: nil, transcriptLineageAccepted: true)]
        )
        records = records.map { $0.id == id ? record : $0 }
        return record
    }

    func analysis(recordingID: UUID) async throws -> RecordingAnalysis {
        RecordingAnalysis(
            status: "published", failureCategory: nil, analysisVersion: "speech-analysis-v1",
            turns: [RecordingTurn(speaker: "other", startMS: 0, endMS: 900, text: "how was your week")]
        )
    }

    private func make(id: Int, draft: EnglishClassDraft, recordings: [ClassRecordingSummary]) -> EnglishClassRecord {
        EnglishClassRecord(
            id: id, teacher: draft.teacher, startsAt: draft.startsAt, expectedDurationMinutes: draft.expectedDurationMinutes,
            notes: draft.notes, skillSlug: "tam_english", recordings: recordings,
            createdAt: Date(timeIntervalSince1970: 0), updatedAt: Date(timeIntervalSince1970: 0)
        )
    }
}
