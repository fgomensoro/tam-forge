import XCTest

final class TAMForgeUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    func testSignedOutShellUsesSelectedEnvironmentWithoutExposingSecrets() {
        let app = XCUIApplication()
        let token = "test-token-must-not-appear"
        app.launchArguments = [
            "-ApplePersistenceIgnoreState", "YES",
            "-ui-test-signed-out",
        ]
        app.launchEnvironment["TAMFORGE_ENV"] = "preview"
        app.launchEnvironment["TAMFORGE_API_TOKEN"] = token
        app.launch()

        XCTAssertTrue(app.staticTexts["TAM Forge"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Preview environment"].exists)
        XCTAssertFalse(app.staticTexts[token].exists)

        let signIn = app.buttons["signInButton"]
        XCTAssertTrue(signIn.exists)
        XCTAssertTrue(signIn.isHittable)
    }

    @MainActor
    func testAuthenticatedShellNavigatesShowsOfflineBannerAndSignsOut() {
        let app = XCUIApplication()
        app.launchArguments = [
            "-ApplePersistenceIgnoreState", "YES",
            "-ui-test-signed-in",
            "-ui-test-native-features",
            "-ui-test-offline",
        ]
        app.launch()

        XCTAssertTrue(app.buttons["todayNavigation"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["offlineBanner"].exists)
        let roadmaps = app.buttons["roadmapsNavigation"]
        XCTAssertTrue(roadmaps.isHittable)
        roadmaps.click()
        XCTAssertTrue(app.staticTexts["Roadmaps"].waitForExistence(timeout: 5))

        let signOut = app.buttons["signOutButton"]
        XCTAssertTrue(signOut.isHittable)
        signOut.click()
        XCTAssertTrue(app.buttons["signInButton"].waitForExistence(timeout: 5))
    }

    @MainActor
    func testAuthenticatedShellHidesDestinationsWithoutNativeSlices() {
        let app = XCUIApplication()
        app.launchArguments = [
            "-ApplePersistenceIgnoreState", "YES",
            "-ui-test-signed-in",
        ]
        app.launch()

        XCTAssertTrue(app.staticTexts["noNativeFeatures"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["todayNavigation"].exists)
        XCTAssertFalse(app.buttons["roadmapsNavigation"].exists)
        let signOut = app.buttons["signOutButton"]
        XCTAssertTrue(signOut.waitForExistence(timeout: 5))
        signOut.click()
        XCTAssertTrue(app.buttons["signInButton"].waitForExistence(timeout: 5))
    }
}
