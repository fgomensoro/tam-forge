import Foundation

enum ActivityState: String, Codable, CaseIterable, Equatable, Sendable {
    case ready
    case active
    case paused
    case outputCommitted = "output_committed"
    case selfReviewComplete = "self_review_complete"
    case aiProcessing = "ai_processing"
    case feedbackReady = "feedback_ready"
    case correctionDue = "correction_due"
    case demonstrated
    case needsWork = "needs_work"
    case incomplete
    case superseded

    var isEditable: Bool {
        switch self {
        case .ready, .active, .paused:
            true
        default:
            false
        }
    }
}

enum ActivityIncompleteClassification: String, Codable, CaseIterable, Equatable, Sendable {
    case required
    case useful
    case optional
    case superseded
}

enum ActivityBlock: String, Codable, CaseIterable, Equatable, Sendable {
    case sql
    case technicalLearning = "technical_learning"
    case careerPipeline = "career_pipeline"
    case correctionWarmup = "correction_warmup"
    case tamCase = "tam_case"
    case communicationSpoken = "communication_spoken"
    case dailyClose = "daily_close"
    case saturdayAssessment = "saturday_assessment"
}

enum ActivityAIRole: String, Codable, CaseIterable, Equatable, Sendable {
    case none
    case planner
    case tutor
    case coach
    case interviewer
    case reviewer
    case analyst
}

enum ActivityArtifactClass: String, Codable, CaseIterable, Equatable, Sendable {
    case originalAudio = "original_audio"
    case transcript
    case writtenOutput = "written_output"
    case sqlOutput = "sql_output"
    case recallNote = "recall_note"
    case caseArtifact = "case_artifact"
    case analysis
    case export
}

enum ActivityArtifactLinkRole: String, Codable, CaseIterable, Equatable, Sendable {
    case originalOutput = "original_output"
    case presentationAudio = "presentation_audio"
    case transcript
    case analysis
    case supporting
    case correction
}

struct ActivitySourceReference: Codable, Equatable, Sendable {
    var path: String
    var anchor: String?
}

struct ActivityProcedureStep: Codable, Equatable, Sendable {
    var phase: String
    var minutes: Int?
    var requirement: String
}

struct ActivityTaskContract: Codable, Equatable, Sendable {
    var stableID: String
    var block: ActivityBlock
    var objective: String
    var timeboxMinutes: Int
    var required: Bool
    var sourceReferences: [ActivitySourceReference]
    var requiredOutput: [String]
    var passCriteria: [String]
    var evidenceRequirements: [String]
    var allowedAIRole: ActivityAIRole
    var procedure: [ActivityProcedureStep]
    var constraints: [String]
    var exerciseType: String?
    var mappingVersion: String?

    enum CodingKeys: String, CodingKey {
        case stableID = "stable_id"
        case block, objective
        case timeboxMinutes = "timebox_minutes"
        case required
        case sourceReferences = "source_references"
        case requiredOutput = "required_output"
        case passCriteria = "pass_criteria"
        case evidenceRequirements = "evidence_requirements"
        case allowedAIRole = "allowed_ai_role"
        case procedure, constraints
        case exerciseType = "exercise_type"
        case mappingVersion = "mapping_version"
    }
}

struct ActivityTimer: Codable, Equatable, Sendable {
    var id: Int
    var startedAt: Date
    var lastHeartbeatAt: Date
    var countedSeconds: Int
    var lastClientSequence: Int

    enum CodingKeys: String, CodingKey {
        case id
        case startedAt = "started_at"
        case lastHeartbeatAt = "last_heartbeat_at"
        case countedSeconds = "counted_seconds"
        case lastClientSequence = "last_client_sequence"
    }
}

struct ActivityArtifact: Codable, Equatable, Sendable {
    var id: Int
    var sha256: String
    var byteLength: Int
    var contentType: String
    var originalFilename: String
    var artifactClass: ActivityArtifactClass

    enum CodingKeys: String, CodingKey {
        case id, sha256
        case byteLength = "byte_length"
        case contentType = "content_type"
        case originalFilename = "original_filename"
        case artifactClass = "artifact_class"
    }
}

struct ActivityArtifactReference: Codable, Equatable, Sendable {
    var artifactID: Int
    var linkRole: ActivityArtifactLinkRole

    enum CodingKeys: String, CodingKey {
        case artifactID = "artifact_id"
        case linkRole = "link_role"
    }
}

struct ActivityCommittedOutput: Codable, Equatable, Sendable {
    var attemptID: Int
    var attemptKind: String
    var commitmentSHA256: String
    var contractPayload: [String: ActivityJSONValue]
    var artifactIDs: [Int]
    var committedAt: Date

    enum CodingKeys: String, CodingKey {
        case attemptID = "attempt_id"
        case attemptKind = "attempt_kind"
        case commitmentSHA256 = "commitment_sha256"
        case contractPayload = "contract_payload"
        case artifactIDs = "artifact_ids"
        case committedAt = "committed_at"
    }
}

struct ActivitySelfReview: Codable, Equatable, Sendable {
    var id: Int
    var attemptID: Int
    var selfScore: Int
    var mainAnswer: String
    var didWell: String
    var structureWeakness: String
    var vaguePoints: String
    var hesitationPoints: String
    var changeNext: String
    var submittedAt: Date

    enum CodingKeys: String, CodingKey {
        case id
        case attemptID = "attempt_id"
        case selfScore = "self_score"
        case mainAnswer = "main_answer"
        case didWell = "did_well"
        case structureWeakness = "structure_weakness"
        case vaguePoints = "vague_points"
        case hesitationPoints = "hesitation_points"
        case changeNext = "change_next"
        case submittedAt = "submitted_at"
    }
}

struct ActivitySummary: Codable, Equatable, Sendable {
    var id: Int
    var studyDayID: Int
    var state: ActivityState
    var optimisticVersion: Int
    var classification: ActivityIncompleteClassification
    var strongerEvidenceID: Int?
    var activityFocusedSeconds: Int
    var dayFocusedMinutes: Int
    var hardStopRecommended: Bool
    var openTimer: ActivityTimer?
    var sourceHidden: Bool

    enum CodingKeys: String, CodingKey {
        case id
        case studyDayID = "study_day_id"
        case state
        case optimisticVersion = "optimistic_version"
        case classification
        case strongerEvidenceID = "stronger_evidence_id"
        case activityFocusedSeconds = "activity_focused_seconds"
        case dayFocusedMinutes = "day_focused_minutes"
        case hardStopRecommended = "hard_stop_recommended"
        case openTimer = "open_timer"
        case sourceHidden = "source_hidden"
    }
}

struct ActivityDetail: Codable, Equatable, Sendable {
    var id: Int
    var studyDayID: Int
    var state: ActivityState
    var optimisticVersion: Int
    var classification: ActivityIncompleteClassification
    var strongerEvidenceID: Int?
    var activityFocusedSeconds: Int
    var dayFocusedMinutes: Int
    var hardStopRecommended: Bool
    var openTimer: ActivityTimer?
    var sourceHidden: Bool
    var taskContract: ActivityTaskContract
    var committedOutput: ActivityCommittedOutput?
    var selfReview: ActivitySelfReview?

    enum CodingKeys: String, CodingKey {
        case id
        case studyDayID = "study_day_id"
        case state
        case optimisticVersion = "optimistic_version"
        case classification
        case strongerEvidenceID = "stronger_evidence_id"
        case activityFocusedSeconds = "activity_focused_seconds"
        case dayFocusedMinutes = "day_focused_minutes"
        case hardStopRecommended = "hard_stop_recommended"
        case openTimer = "open_timer"
        case sourceHidden = "source_hidden"
        case taskContract = "task_contract"
        case committedOutput = "committed_output"
        case selfReview = "self_review"
    }

    var summary: ActivitySummary {
        .init(
            id: id,
            studyDayID: studyDayID,
            state: state,
            optimisticVersion: optimisticVersion,
            classification: classification,
            strongerEvidenceID: strongerEvidenceID,
            activityFocusedSeconds: activityFocusedSeconds,
            dayFocusedMinutes: dayFocusedMinutes,
            hardStopRecommended: hardStopRecommended,
            openTimer: openTimer,
            sourceHidden: sourceHidden
        )
    }

    mutating func apply(_ summary: ActivitySummary) {
        precondition(summary.id == id, "activity summary belongs to another activity")
        state = summary.state
        optimisticVersion = summary.optimisticVersion
        classification = summary.classification
        strongerEvidenceID = summary.strongerEvidenceID
        activityFocusedSeconds = summary.activityFocusedSeconds
        dayFocusedMinutes = summary.dayFocusedMinutes
        hardStopRecommended = summary.hardStopRecommended
        openTimer = summary.openTimer
        sourceHidden = summary.sourceHidden
    }
}

enum ActivityJSONValue: Codable, Equatable, Sendable {
    case string(String)
    case integer(Int)
    case decimal(Double)
    case boolean(Bool)
    case array([ActivityJSONValue])
    case object([String: ActivityJSONValue])
    case null

    init(from decoder: any Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .boolean(value)
        } else if let value = try? container.decode(Int.self) {
            self = .integer(value)
        } else if let value = try? container.decode(Double.self) {
            self = .decimal(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([ActivityJSONValue].self) {
            self = .array(value)
        } else {
            self = .object(try container.decode([String: ActivityJSONValue].self))
        }
    }

    func encode(to encoder: any Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case let .string(value): try container.encode(value)
        case let .integer(value): try container.encode(value)
        case let .decimal(value): try container.encode(value)
        case let .boolean(value): try container.encode(value)
        case let .array(value): try container.encode(value)
        case let .object(value): try container.encode(value)
        case .null: try container.encodeNil()
        }
    }
}
