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
                        .foregroundStyle(.secondary)
                    Button("Open review") { Task { await model.open() } }
                        .accessibilityIdentifier("reviewOpen")
                } else if let review = model.review {
                    content(review)
                } else if model.isBusy {
                    ProgressView("Opening review…")
                } else {
                    Button("Retry") { Task { await model.open() } }
                }
                if let message = model.errorMessage {
                    Label(message, systemImage: "exclamationmark.triangle")
                        .foregroundStyle(.orange)
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
                Text(verdict).font(.headline).accessibilityIdentifier("reviewVerdict")
            }
            ForEach(review.dimensions) { dimension in
                VStack(alignment: .leading, spacing: 2) {
                    HStack {
                        Text(dimension.name).font(.subheadline.weight(.medium))
                        Spacer()
                        Text("\(dimension.score) / \(dimension.maximum)").monospacedDigit()
                    }
                    Text(dimension.rationale).font(.callout)
                    Text("“\(dimension.evidence)”").font(.caption).foregroundStyle(.secondary)
                }
                .padding(.vertical, 2)
            }
            findings("Strengths", review.strengths)
            findings("Corrections", review.corrections)
            if let next = review.nextPractice {
                Label(next, systemImage: "arrow.turn.down.right")
            }
            HStack {
                if let model = review.model {
                    Text("Model \(model)").font(.caption).foregroundStyle(.secondary)
                }
                if let evidence = review.evidenceStatus {
                    Text(evidence == "recorded" ? "Recorded as evidence" : "Not recorded: \(evidence)")
                        .font(.caption)
                        .foregroundStyle(evidence == "recorded" ? Color.secondary : Color.orange)
                        .accessibilityIdentifier("reviewEvidenceStatus")
                }
            }
        } else {
            HStack {
                Text(statusLabel(review)).accessibilityIdentifier("reviewStatus")
                Spacer()
                if model.isPending {
                    Button("Refresh") { Task { await model.refresh() } }.disabled(model.isBusy)
                }
                if model.canRequest {
                    Button("Request review") { Task { await model.request() } }
                        .accessibilityIdentifier("reviewRequest")
                }
            }
        }
    }

    @ViewBuilder
    private func findings(_ title: String, _ items: [ReviewFinding]) -> some View {
        if !items.isEmpty {
            Text(title).font(.subheadline.weight(.semibold))
            ForEach(items, id: \.statement) { item in
                VStack(alignment: .leading, spacing: 2) {
                    Text("• \(item.statement)")
                    if !item.instruction.isEmpty {
                        Text(item.instruction).font(.caption).foregroundStyle(.secondary)
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
