import SwiftUI

// What the app may say about pronunciation, and what it may not.
//
// Until the server's calibrated pipeline exists, every word is "not measured"
// and the diagnostic says so in words rather than showing an empty bar. When
// an assessment does arrive it carries, per word, how intelligible the word
// was, how sure the pipeline is, and a proposed correction. There is no accent
// field in the model and no place in the view to draw one: the closed
// vocabulary is intelligibility, uncertainty and correction.

enum PronunciationIntelligibility: String, Codable, Sendable, Equatable {
    case clear
    case unclear
    case notMeasured = "not_measured"
}

struct PronunciationWordAssessment: Codable, Sendable, Equatable, Identifiable {
    let text: String
    let startMilliseconds: Int64
    let endMilliseconds: Int64
    let intelligibility: PronunciationIntelligibility
    /// 0 means the pipeline is certain, 1 means it knows nothing.
    let uncertainty: Double
    let correction: String?
    let excludedReason: String?

    var id: Int64 { startMilliseconds }

    /// A word the pipeline was not sure about is shown as a question, not a verdict.
    var isTentative: Bool { intelligibility != .notMeasured && uncertainty >= 0.5 }
}

struct PronunciationAssessment: Codable, Sendable, Equatable {
    let availability: String          // "measured" | "not_measured"
    let reasonCode: String?
    let words: [PronunciationWordAssessment]

    static let notMeasured = PronunciationAssessment(
        availability: "not_measured", reasonCode: "pronunciation_not_measured", words: []
    )

    var isMeasured: Bool { availability == "measured" }
    var measuredWords: [PronunciationWordAssessment] {
        words.filter { $0.intelligibility != .notMeasured }
    }
    var corrections: [PronunciationWordAssessment] {
        measuredWords.filter { $0.correction != nil }
    }

    /// The one sentence the diagnostic leads with. Never a score.
    var headline: String {
        guard isMeasured else {
            return "Pronunciation is not measured yet. It stays that way until the server pipeline passes calibration against human labels."
        }
        let unclear = measuredWords.filter { $0.intelligibility == .unclear }.count
        let excluded = words.count - measuredWords.count
        var parts = ["\(measuredWords.count) words assessed", "\(unclear) unclear"]
        if excluded > 0 { parts.append("\(excluded) excluded for crosstalk or echo") }
        return parts.joined(separator: ", ") + "."
    }
}

struct PronunciationDiagnosticView: View {
    let assessment: PronunciationAssessment

    var body: some View {
        GroupBox("Pronunciation") {
            VStack(alignment: .leading, spacing: 8) {
                Text(assessment.headline)
                    .font(.callout)
                    .foregroundStyle(assessment.isMeasured ? .primary : .secondary)
                    .accessibilityIdentifier("pronunciationHeadline")
                if assessment.isMeasured {
                    ForEach(assessment.corrections) { word in
                        HStack(alignment: .firstTextBaseline, spacing: 6) {
                            Text(word.text).bold()
                            Text("heard as")
                                .foregroundStyle(.secondary)
                            Text(word.correction ?? "")
                            if word.isTentative {
                                Text("(uncertain)")
                                    .foregroundStyle(.secondary)
                                    .accessibilityLabel("uncertain")
                            }
                        }
                        .font(.caption)
                        .accessibilityIdentifier("pronunciationCorrection")
                    }
                    if assessment.corrections.isEmpty {
                        Text("No corrections proposed.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityIdentifier("pronunciationDiagnostic")
    }
}
