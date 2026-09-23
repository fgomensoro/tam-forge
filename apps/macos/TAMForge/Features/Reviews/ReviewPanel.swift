import SwiftUI

/// The AI review of a committed, self-reviewed attempt: rubric scores with reasons,
/// two strengths, two corrections, and what was recorded as evidence.
struct ReviewPanel: View {
    @ObservedObject var model: ReviewModel

    var body: some View {
        GroupBox("AI review") {
            VStack(alignment: .leading, spacing: 12) {
                if !model.isOpened {
                    Text("After your self-review, the reviewer scores the attempt against the block's rubric and records the result as evidence.")
                        .organic(.small)
                    Button("Open review") { Task { await model.open() } }
                        .accessibilityIdentifier("reviewOpen")
                } else if let review = model.review {
                    content(review)
                } else if model.isBusy {
                    ProgressView("Opening review…")
                        .controlSize(.small)
                } else {
                    Button("Retry") { Task { await model.open() } }
                }
                if let message = model.errorMessage {
                    Label(message, systemImage: "exclamationmark.triangle")
                        .organic(.small, color: Organic.Color.warning)
                        .accessibilityIdentifier("reviewError")
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityIdentifier("reviewPanel")
    }

    @ViewBuilder
    private func content(_ review: ActivityReview) -> some View {
        if review.isReady {
            if let verdict = review.verdict {
                Text(verdict).organic(.title).accessibilityIdentifier("reviewVerdict")
            }
            ForEach(review.dimensions) { dimension in
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: Organic.Space.p8) {
                        Text(dimension.name).organic(.strong)
                        Spacer(minLength: 0)
                        Text("\(dimension.score) / \(dimension.maximum)")
                            .font(Organic.Font.tabular(.semibold, size: 13))
                            .foregroundStyle(Organic.Color.text)
                    }
                    Text(dimension.rationale).organic(.small, color: Organic.Color.body)
                    Text("“\(dimension.evidence)”").organic(.caption)
                }
                .padding(.vertical, 2)
            }
            findings("Strengths", review.strengths)
            findings("Corrections", review.corrections)
            if let next = review.nextPractice {
                Label(next, systemImage: "arrow.turn.down.right")
                    .organic(.small, color: Organic.Color.accent300)
            }
            HStack(spacing: Organic.Space.p8) {
                if let model = review.model {
                    Text("Model \(model)").organic(.caption)
                }
                if let evidence = review.evidenceStatus {
                    Text(evidence == "recorded" ? "Recorded as evidence" : "Not recorded: \(evidence)")
                        .organic(.caption, color: evidence == "recorded" ? Organic.Color.muted : Organic.Color.warning)
                        .accessibilityIdentifier("reviewEvidenceStatus")
                }
            }
        } else {
            HStack(spacing: Organic.Space.p8) {
                Text(statusLabel(review)).organic(.small, color: Organic.Color.body).accessibilityIdentifier("reviewStatus")
                Spacer(minLength: 0)
                if model.isPending {
                    Button("Refresh") { Task { await model.refresh() } }.disabled(model.isBusy)
                }
                if model.canRequest {
                    Button("Request review") { Task { await model.request() } }
                        .buttonStyle(.organicPrimary)
                        .accessibilityIdentifier("reviewRequest")
                }
            }
        }
    }

    @ViewBuilder
    private func findings(_ title: String, _ items: [ReviewFinding]) -> some View {
        if !items.isEmpty {
            Text(title).organic(.strong)
            ForEach(items, id: \.statement) { item in
                VStack(alignment: .leading, spacing: 2) {
                    Text("• \(item.statement)").organic(.small, color: Organic.Color.body)
                    if !item.instruction.isEmpty {
                        Text(item.instruction).organic(.caption)
                    }
                }
            }
        }
    }

    private func statusLabel(_ review: ActivityReview) -> String {
        switch review.status {
        case "queued", "running": "The reviewer is scoring this attempt."
        case "needs_attention": "The review could not be produced" + (review.failureCategory.map { " (\($0.replacingOccurrences(of: "_", with: " ")))" } ?? "") + "."
        default: "No review yet. Commit the attempt and finish the self-review, then request one."
        }
    }
}
