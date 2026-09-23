import SwiftUI

/// The Cards section: run today's due cards, add one by hand, import a roadmap version's
/// vault notes. The same panel opens inside a block whose procedure has a retrieval phase,
/// so its minutes count in that block.
struct CardsView: View {
    @ObservedObject var model: CardsModel
    @State private var importVersionText = ""

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 26) {
                header
                HStack(alignment: .top, spacing: Organic.Space.p24) {
                    CardsPanel(model: model, showsQueueControls: false)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    VStack(alignment: .leading, spacing: Organic.Space.p14) {
                        practice
                        newCard
                        importer
                    }
                    .frame(width: 300)
                }
            }
            .frame(maxWidth: 1040, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityIdentifier("cardsScreen")
        .task { await model.loadLibrary() }
    }

    private var header: some View {
        HStack(alignment: .bottom, spacing: Organic.Space.p20) {
            VStack(alignment: .leading, spacing: 6) {
                Text("Cards").organic(.h1).accessibilityAddTraits(.isHeader)
                CardsProgressText(model: model, role: .body)
            }
            Spacer(minLength: 0)
            CardsModePicker(model: model)
            CardsRefreshButton(model: model)
        }
    }

    /// Free practice: any topic, any time, whatever is due. The due queue is the minimum.
    private var practice: some View {
        VStack(alignment: .leading, spacing: Organic.Space.p12) {
            Text("Practice whenever you want").organic(.kicker)
            Text("Pick one topic or everything mixed. Cards come shuffled whatever their due date, in Written or Spoken mode, and each grade still reschedules the card.")
                .organic(.small, color: Organic.Color.neutral300)
                .fixedSize(horizontal: false, vertical: true)
            Picker("Topic", selection: $model.practiceTopicID) {
                ForEach(model.practiceTopics) { topic in
                    Text("\(topic.title) · \(topic.count)").tag(topic.id)
                }
            }
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
        .frame(maxWidth: .infinity, alignment: .leading)
        .organicCard(radius: Organic.Radius.r26, padding: Organic.Space.p20)
    }

    private var newCard: some View {
        VStack(alignment: .leading, spacing: Organic.Space.p12) {
            Text("New card").organic(.kicker)
            TextField("Question", text: $model.draft.question)
                .organicField(onSurface: true)
                .accessibilityIdentifier("cardQuestion")
            TextField("Answer", text: $model.draft.answer)
                .organicField(onSurface: true)
                .accessibilityIdentifier("cardAnswer")
            TextField("Skill slug", text: $model.draft.skillSlug)
                .organicField(onSurface: true)
                .accessibilityIdentifier("cardSkill")
            Button("Add card") { Task { await model.create() } }
                .disabled(!model.canCreate)
                .accessibilityIdentifier("cardCreate")
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .organicCard(radius: Organic.Radius.r26, padding: Organic.Space.p20)
    }

    private var importer: some View {
        VStack(alignment: .leading, spacing: Organic.Space.p8) {
            Text("Import from roadmap").organic(.kicker)
            Text("Vault notes marked \(Text("flashcard-source: true").font(OrganicText.mono.font)) import their Q/A pairs. Importing again adds nothing.")
                .organic(.small, color: Organic.Color.neutral300)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: Organic.Space.p8) {
                TextField("Version id", text: $importVersionText)
                    .organicField(onSurface: true)
                    .frame(width: 110)
                Button("Import") {
                    if let id = Int(importVersionText) { Task { await model.importRoadmapVersion(id) } }
                }
                .disabled(Int(importVersionText) == nil || model.isBusy)
                .accessibilityIdentifier("cardImport")
            }
            if let outcome = model.lastImport {
                Text("\(outcome.created) new, \(outcome.existing) already known.")
                    .organic(.caption, color: Organic.Color.accent2_300)
                    .accessibilityIdentifier("cardImportOutcome")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Organic.Space.p20)
        .background(Organic.Color.fill04, in: RoundedRectangle(cornerRadius: Organic.Radius.r26, style: .continuous))
    }
}

/// The review loop itself; embedded in the Cards section and in a block's retrieval phase.
/// The Cards page puts the mode picker, the count and Refresh in its own header, so it
/// turns `showsQueueControls` off; the block's retrieval phase keeps them above the card.
struct CardsPanel: View {
    @ObservedObject var model: CardsModel
    var showsQueueControls = true

    var body: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: Organic.Space.p14) {
                if let card = model.current {
                    flashcard(card)
                } else {
                    Text(model.isPracticing
                        ? "Practice round finished. Pick another topic or go back to the due cards."
                        : "No cards due. Practice any topic, or add a new card.")
                        .organic(.body, color: Organic.Color.muted)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(EdgeInsets(top: 36, leading: 40, bottom: 32, trailing: 40))
                        .organicCard(radius: Organic.Radius.r36, padding: 0)
                        .accessibilityIdentifier("cardsEmpty")
                }
                if let outcome = model.lastOutcome {
                    Text("Next in \(outcome.intervalAfter) day\(outcome.intervalAfter == 1 ? "" : "s"), on \(outcome.dueAfter).")
                        .organic(.caption, color: Organic.Color.faint)
                        .padding(.leading, 6)
                        .accessibilityIdentifier("cardsLastOutcome")
                }
                if let message = model.errorMessage {
                    Label(message, systemImage: "exclamationmark.triangle")
                        .organic(.small, color: Organic.Color.warning)
                        .accessibilityIdentifier("cardsError")
                }
            }
        } label: {
            HStack(spacing: Organic.Space.p12) {
                Text(model.isPracticing ? "Practice" : "Due today").organic(.title)
                if showsQueueControls {
                    Spacer(minLength: 0)
                    CardsModePicker(model: model)
                    CardsProgressText(model: model, role: .caption)
                    CardsRefreshButton(model: model)
                }
            }
        }
        .groupBoxStyle(CardsPanelGroupBoxStyle())
        .accessibilityIdentifier("cardsPanel")
        .task { await model.load() }
    }

    /// The due card: an r36 shadowed surface with a second card stacked behind it. The
    /// actions sit at the bottom of the 340 pt minimum, as the handoff's `margin-top: auto`.
    private func flashcard(_ card: CardRecord) -> some View {
        VStack(alignment: .leading, spacing: 22) {
            Text("\(card.skillSlug.replacingOccurrences(of: "_", with: " ")) · card \(model.reviewedCount + 1) of \(model.reviewedCount + model.remaining)")
                .organic(.kicker, color: Organic.Color.accent400)
            Text(card.question)
                .organic(.h2)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: 560, alignment: .leading)
                .textSelection(.enabled)
                .accessibilityIdentifier("cardsQuestion")
            if model.mode == .spoken {
                HStack(spacing: Organic.Space.p12) {
                    Button(model.spokenRecordingID == nil ? "Record your answer" : "Answer recorded") {
                        Task { await model.recordAnswer() }
                    }
                    .disabled(!model.canRecord || model.spokenRecordingID != nil)
                    .accessibilityIdentifier("cardsRecord")
                    Text("Say the answer aloud; the recording stays with this review as TAM English evidence.")
                        .organic(.caption)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            if model.isRevealed {
                Rectangle().fill(Organic.Color.divider).frame(height: 1)
                Text(card.answer)
                    .organic(.body)
                    .lineSpacing(5)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: 600, alignment: .leading)
                    .textSelection(.enabled)
                    .accessibilityIdentifier("cardsAnswer")
                Spacer(minLength: 0)
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: Organic.Space.p8) { gradeButtons(0..<6) }
                    VStack(alignment: .leading, spacing: Organic.Space.p8) {
                        HStack(spacing: Organic.Space.p8) { gradeButtons(0..<3) }
                        HStack(spacing: Organic.Space.p8) { gradeButtons(3..<6) }
                    }
                }
            } else {
                Spacer(minLength: 0)
                Button("Show answer") { model.reveal() }
                    .buttonStyle(.organicPrimary)
                    .accessibilityIdentifier("cardsReveal")
            }
        }
        // idealHeight turns the scroll view's open-ended proposal into 340, so the Spacer
        // pushes the actions down; the fixed-size texts still grow the card past it.
        .frame(maxWidth: .infinity, minHeight: 340, idealHeight: 340, alignment: .topLeading)
        .padding(EdgeInsets(top: 36, leading: 40, bottom: 32, trailing: 40))
        .organicCard(radius: Organic.Radius.r36, padding: 0, shadowed: true)
        .background(
            RoundedRectangle(cornerRadius: Organic.Radius.r36, style: .continuous)
                .fill(Organic.Color.surface.opacity(0.6))
                .offset(x: 8, y: 8)
        )
    }

    private func gradeButtons(_ grades: Range<Int>) -> some View {
        ForEach(grades, id: \.self) { grade in
            Button { Task { await model.grade(grade) } } label: {
                Text("\(Text("\(grade)").font(Organic.Font.tabular(.semibold, size: 13)).foregroundStyle(Organic.Color.accent400)) \(gradeName(grade))")
            }
            .buttonStyle(.organicSecondary)
            .disabled(!model.canGrade)
            .accessibilityIdentifier("cardsGrade\(grade)")
        }
    }

    private func gradeName(_ grade: Int) -> String {
        switch grade {
        case 0: "Blank"
        case 1: "Wrong"
        case 2: "Close"
        case 3: "Hard"
        case 4: "Good"
        default: "Easy"
        }
    }
}

/// The panel is a column, not a card: the flashcard inside it is the card.
private struct CardsPanelGroupBoxStyle: GroupBoxStyle {
    func makeBody(configuration: Configuration) -> some View {
        VStack(alignment: .leading, spacing: Organic.Space.p14) {
            configuration.label
            configuration.content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct CardsModePicker: View {
    @ObservedObject var model: CardsModel

    var body: some View {
        Picker("Mode", selection: $model.mode) {
            Text("Written").tag(CardsModel.Mode.written)
            Text("Spoken").tag(CardsModel.Mode.spoken)
        }
        .pickerStyle(.segmented)
        .labelsHidden()
        .frame(width: 200)
        .accessibilityIdentifier("cardsMode")
    }
}

private struct CardsProgressText: View {
    @ObservedObject var model: CardsModel
    let role: OrganicText

    var body: some View {
        Text("\(model.remaining) left · \(model.reviewedCount) done")
            .organic(role, color: Organic.Color.muted)
            .accessibilityIdentifier("cardsProgress")
    }
}

private struct CardsRefreshButton: View {
    @ObservedObject var model: CardsModel

    var body: some View {
        Button("Refresh") { Task { await model.load() } }
            .disabled(model.isBusy)
            .accessibilityIdentifier("cardsRefresh")
    }
}
