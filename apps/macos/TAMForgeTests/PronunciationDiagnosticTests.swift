import XCTest

final class PronunciationDiagnosticTests: XCTestCase {
    private func word(
        _ text: String, at start: Int64, _ intelligibility: PronunciationIntelligibility,
        uncertainty: Double = 0.1, correction: String? = nil, excluded: String? = nil
    ) -> PronunciationWordAssessment {
        PronunciationWordAssessment(
            text: text, startMilliseconds: start, endMilliseconds: start + 300,
            intelligibility: intelligibility, uncertainty: uncertainty,
            correction: correction, excludedReason: excluded
        )
    }

    func testNotMeasuredIsSaidInWordsWithItsReason() {
        let assessment = PronunciationAssessment.notMeasured
        XCTAssertFalse(assessment.isMeasured)
        XCTAssertEqual(assessment.reasonCode, "pronunciation_not_measured")
        XCTAssertTrue(assessment.headline.contains("not measured"))
        XCTAssertTrue(assessment.headline.contains("calibration"))
        XCTAssertTrue(assessment.corrections.isEmpty)
    }

    func testAMeasuredAssessmentExposesUncertaintyAndCorrectionsPerWord() {
        let assessment = PronunciationAssessment(
            availability: "measured", reasonCode: nil,
            words: [
                word("the", at: 0, .clear),
                word("cohort", at: 400, .unclear, uncertainty: 0.6, correction: "cohort"),
                word("churn", at: 800, .notMeasured, uncertainty: 1, excluded: "crosstalk"),
            ]
        )
        XCTAssertTrue(assessment.isMeasured)
        XCTAssertEqual(assessment.measuredWords.count, 2)
        XCTAssertEqual(assessment.corrections.map(\.text), ["cohort"])
        XCTAssertTrue(assessment.corrections[0].isTentative)
        XCTAssertEqual(assessment.headline, "2 words assessed, 1 unclear, 1 excluded for crosstalk or echo.")
    }

    func testTheModelHasNoPlaceForAccentOrNativeness() {
        let labels = Mirror(reflecting: word("x", at: 0, .clear)).children.compactMap(\.label)
            + Mirror(reflecting: PronunciationAssessment.notMeasured).children.compactMap(\.label)
        for forbidden in ["accent", "native", "country"] {
            XCTAssertFalse(labels.contains { $0.lowercased().contains(forbidden) }, forbidden)
        }
        XCTAssertEqual(Set(PronunciationIntelligibility.allCasesForTest.map(\.rawValue)), ["clear", "unclear", "not_measured"])
    }

    func testTheWireFormatMatchesTheServerVocabulary() throws {
        let json = """
        {"availability":"measured","reasonCode":null,"words":[{"text":"churn","startMilliseconds":0,"endMilliseconds":300,"intelligibility":"not_measured","uncertainty":1.0,"correction":null,"excludedReason":"echo"}]}
        """
        let decoded = try JSONDecoder().decode(PronunciationAssessment.self, from: Data(json.utf8))
        XCTAssertEqual(decoded.words[0].intelligibility, .notMeasured)
        XCTAssertEqual(decoded.words[0].excludedReason, "echo")
    }
}

extension PronunciationIntelligibility {
    static var allCasesForTest: [PronunciationIntelligibility] { [.clear, .unclear, .notMeasured] }
}
