import OpenAPIRuntime

// Compile-time guard: required-nullable FastAPI fields must survive native generation.
private func generatedRequiredNullableContract() {
    let _: KeyPath<Components.Schemas.TodayResponse, Int?> = \.dayId
    let _: KeyPath<Components.Schemas.TodayResponse, Components.Schemas.TodayResponse.PrimaryContinuePayload?> = \.primaryContinue
    let _: KeyPath<Components.Schemas.NotificationPage, Int?> = \.nextCursor
    let _: KeyPath<
        Components.Schemas.SkillSummaryResponse,
        Components.Schemas.SkillSummaryResponse.LatestSnapshotPayload?
    > = \.latestSnapshot
    let _: KeyPath<Components.Schemas.EvidenceEventPage, Int?> = \.nextCursor
    let _: KeyPath<Components.Schemas.PortfolioHistoryResponse, Int?> = \.nextCursor
}

// Compile-time guard: recording models are generated even before R4 adds HTTP routes.
private func generatedRecordingContract() {
    let _: Components.Schemas.RecordingSealCommand.Type =
        Components.Schemas.RecordingSealCommand.self
    let _: Components.Schemas.RecordingTrackManifest.Type =
        Components.Schemas.RecordingTrackManifest.self
    let _: Components.Schemas.RecordingSourceLineageSegment.Type =
        Components.Schemas.RecordingSourceLineageSegment.self
    let _: Components.Schemas.RecordingStatusResponse.Type =
        Components.Schemas.RecordingStatusResponse.self
}
