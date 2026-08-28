import XCTest

final class TAMForgeUITests: XCTestCase {
    @MainActor
    func testShellUsesSelectedEnvironmentWithoutExposingSecrets() {
        let app = XCUIApplication()
        let token = "test-token-must-not-appear"
        app.launchEnvironment["TAMFORGE_ENV"] = "preview"
        app.launchEnvironment["TAMFORGE_API_TOKEN"] = token
        app.launch()

        XCTAssertTrue(app.staticTexts["TAM Forge"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Preview environment"].exists)
        XCTAssertFalse(app.staticTexts[token].exists)

        let connectionCheck = app.buttons["connectionCheckButton"]
        XCTAssertTrue(connectionCheck.exists)
        XCTAssertTrue(connectionCheck.isHittable)
    }
}
