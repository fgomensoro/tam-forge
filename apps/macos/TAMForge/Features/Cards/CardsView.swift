import SwiftUI

/// The Cards section: run today's due cards, add one by hand, import a roadmap version's
/// vault notes. The same panel opens inside a block whose procedure has a retrieval phase,
/// so its minutes count in that block.
struct CardsView: View {
    @ObservedObject var model: CardsModel
    @State private var importVersionText = ""

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("Cards").font(.title2.weight(.semibold))
                practice
                CardsPanel(model: model)
                Divider()
                newCard
                Divider()
                importer
            }
            .padding()
        }
        .accessibilityIdentifier("cardsScreen")
        .task { await model.loadLibrary() }
    }

    /// Free practice: any topic, any time, whatever is due. The due queue is the minimum.
    private var practice: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Practice whenever you want").font(.headline)
            Text("Pick one topic or everything mixed. Cards come shuffled whatever their due date, in Written or Spoken mode, and each grade still reschedules the card.")
                .font(.caption).foregroundStyle(.secondary)
            HStack {
                Picker("Topic", selection: $model.practiceTopicID) {
                    ForEach(model.practiceTopics) { topic in
                        Text("\(topic.title) · \(topic.count)").tag(topic.id)
                    }
                }
                .frame(maxWidth: 420)
                .disabled(model.isPracticing || model.practiceTopics.isEmpty)
                .accessibilityIdentifier("cardsPracticeTopic")
                if model.isPracticing {
                    Button("Back to due cards") { Task { await model.stopPractice() } }
                        .disabled(model.isBusy)
                        .accessibilityIdentifier("cardsPracticeStop")
                } else {
                    Button("Practice") { Task { await model.startPractice() } }
                        .disabled(!model.canPractice)
                        .accessibilityIdentifier("cardsPracticeStart")
                }
            }
        }
    }

    private var newCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("New card").font(.headline)
            TextField("Question", text: $model.draft.question).accessibilityIdentifier("cardQuestion")
            TextField("Answer", text: $model.draft.answer).accessibilityIdentifier("cardAnswer")
            TextField("Skill slug", text: $model.draft.skillSlug).accessibilityIdentifier("cardSkill")
            Button("Add card") { Task { await model.create() } }
                .disabled(!model.canCreate)
                .accessibilityIdentifier("cardCreate")
        }
        .textFieldStyle(.roundedBorder)
    }

    private var importer: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Import from a roadmap version").font(.headline)
            Text("Vault notes marked flashcard-source: true import their Q/A pairs. Importing again adds nothing.")
                .font(.caption).foregroundStyle(.secondary)
            HStack {
                TextField("Version id", text: $importVersionText).frame(width: 120)
                Button("Import") {
                    if let id = Int(importVersionText) { Task { await model.importRoadmapVersion(id) } }
                }
                .disabled(Int(importVersionText) == nil || model.isBusy)
                .accessibilityIdentifier("cardImport")
            }
            if let outcome = model.lastImport {
                Text("\(outcome.created) new, \(outcome.existing) already known.")
                    .font(.caption).accessibilityIdentifier("cardImportOutcome")
            }
        }
        .textFieldStyle(.roundedBorder)
    }
}

/// The review loop itself; embedded in the Cards section and in a block's retrieval phase.
struct CardsPanel: View {
    @ObservedObject var model: CardsModel

    var body: some View {
        GroupBox(model.isPracticing ? "Practice" : "Due today") {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Picker("Mode", selection: $model.mode) {
                        Text("Written").tag(CardsModel.Mode.written)
                        Text("Spoken").tag(CardsModel.Mode.spoken)
                    }
                    .pickerStyle(.segmented)
                    .frame(width: 200)
                    .accessibilityIdentifier("cardsMode")
                    Spacer()
                    Text("\(model.remaining) left · \(model.reviewedCount) done")
                        .font(.caption).foregroundStyle(.secondary)
                        .accessibilityIdentifier("cardsProgress")
                    Button("Refresh") { Task { await model.load() } }
                        .disabled(model.isBusy)
                        .accessibilityIdentifier("cardsRefresh")
                }
                if let card = model.current {
                    cardBody(card)
                } else {
                    Text(model.isPracticing
                        ? "Practice round finished. Pick another topic or go back to the due cards."
                        : "No cards due. Practice any topic above, or add a card below.")
                        .foregroundStyle(.secondary)
                        .accessibilityIdentifier("cardsEmpty")
                }
                if let outcome = model.lastOutcome {
                    Text("Next in \(outcome.intervalAfter) day\(outcome.intervalAfter == 1 ? "" : "s"), on \(outcome.dueAfter).")
                        .font(.caption).foregroundStyle(.secondary)
                        .accessibilityIdentifier("cardsLastOutcome")
                }
                if let message = model.errorMessage {
                    Label(message, systemImage: "exclamationmark.triangle").foregroundStyle(Color.orange)
                        .accessibilityIdentifier("cardsError")
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityIdentifier("cardsPanel")
        .task { await model.load() }
    }

    @ViewBuilder
    private func cardBody(_ card: CardRecord) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(card.skillSlug.replacingOccurrences(of: "_", with: " "))
                .font(.caption).foregroundStyle(.secondary)
            Text(card.question).font(.title3).textSelection(.enabled)
                .accessibilityIdentifier("cardsQuestion")
            if model.mode == .spoken {
                HStack {
                    Button(model.spokenRecordingID == nil ? "Record your answer" : "Answer recorded") {
                        Task { await model.recordAnswer() }
                    }
                    .disabled(!model.canRecord || model.spokenRecordingID != nil)
                    .accessibilityIdentifier("cardsRecord")
                    Text("Say the answer aloud; the recording stays with this review as TAM English evidence.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            if model.isRevealed {
                Text(card.answer).textSelection(.enabled).accessibilityIdentifier("cardsAnswer")
                HStack(spacing: 6) {
                    ForEach(0..<6, id: \.self) { grade in
                        Button(gradeLabel(grade)) { Task { await model.grade(grade) } }
                            .disabled(!model.canGrade)
                            .accessibilityIdentifier("cardsGrade\(grade)")
                    }
                }
            } else {
                Button("Show answer") { model.reveal() }
                    .buttonStyle(.borderedProminent)
                    .accessibilityIdentifier("cardsReveal")
            }
        }
        .padding(8)
        .background(.quaternary, in: RoundedRectangle(cornerRadius: 6))
    }

    private func gradeLabel(_ grade: Int) -> String {
        switch grade {
        case 0: "0 Blank"
        case 1: "1 Wrong"
        case 2: "2 Close"
        case 3: "3 Hard"
        case 4: "4 Good"
        default: "5 Easy"
        }
    }
}
