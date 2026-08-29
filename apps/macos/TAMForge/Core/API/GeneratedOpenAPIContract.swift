import OpenAPIRuntime

// Compile-time guard: required-nullable FastAPI fields must survive native generation.
private func generatedRequiredNullableContract() {
    let _: KeyPath<Components.Schemas.TodayResponse, Int?> = \.dayId
    let _: KeyPath<Components.Schemas.TodayResponse, Components.Schemas.TodayResponse.PrimaryContinuePayload?> = \.primaryContinue
    let _: KeyPath<Components.Schemas.NotificationPage, Int?> = \.nextCursor
}
