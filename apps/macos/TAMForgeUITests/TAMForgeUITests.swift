import XCTest

final class TAMForgeUITests: XCTestCase {
    @MainActor
    func testEvidenceIsReachableFromSidebar() {
        let app = launchWorkspace()
        let evidence = app.buttons["evidenceNavigation"]
        XCTAssertTrue(evidence.waitForExistence(timeout: 5))
        evidence.click()
        XCTAssertTrue(app.staticTexts["evidenceTitle"].waitForExistence(timeout: 5))
    }

    @MainActor
    func testTodayEvidenceKeepsActivityContextAndSignOutClearsIt() {
        let app = launchWorkspace(extra: ["-ui-test-evidence-route"])
        app.buttons["todayContinueButton"].click()
        let openActivity = app.buttons["evidenceOpenActivity"]
        XCTAssertTrue(openActivity.waitForExistence(timeout: 5))
        openActivity.click()
        // The fixture accepts only activity 41: a lost or changed target cannot load it.
        XCTAssertTrue(app.buttons["Start activity"].waitForExistence(timeout: 5))
        app.buttons["todayNavigation"].click()
        XCTAssertTrue(app.buttons["todayContinueButton"].waitForExistence(timeout: 5))
        app.buttons["todayContinueButton"].click()
        XCTAssertTrue(openActivity.waitForExistence(timeout: 5))
        app.buttons["evidenceAllActivities"].click()
        XCTAssertTrue(openActivity.waitForNonExistence(timeout: 5))

        app.buttons["todayNavigation"].click()
        XCTAssertTrue(app.buttons["todayContinueButton"].waitForExistence(timeout: 5))
        app.buttons["todayContinueButton"].click()
        XCTAssertTrue(openActivity.waitForExistence(timeout: 5))
        app.buttons["signOutButton"].click()
        XCTAssertTrue(app.buttons["signInButton"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["evidenceTitle"].exists)
        app.buttons["signInButton"].click()
        XCTAssertTrue(app.buttons["todayNavigation"].waitForExistence(timeout: 5))
        app.buttons["evidenceNavigation"].click()
        XCTAssertTrue(app.staticTexts["evidenceTitle"].waitForExistence(timeout: 5))
        XCTAssertFalse(openActivity.exists)
    }

    @MainActor
    func testEvidenceSkillsCanRetryWithoutHidingPortfolio() {
        let app = launchWorkspace(extra: ["-ui-test-evidence-retry"])
        app.buttons["evidenceNavigation"].click()
        let retry = app.buttons["evidenceRetrySkills"]
        XCTAssertTrue(retry.waitForExistence(timeout: 5))
        let portfolioScore = textContaining("14.000 / 20", in: app)
        XCTAssertTrue(portfolioScore.waitForExistence(timeout: 5))
        retry.click()
        XCTAssertTrue(app.staticTexts["Structured troubleshooting"].waitForExistence(timeout: 5))
        XCTAssertTrue(retry.waitForNonExistence(timeout: 5))
        XCTAssertTrue(portfolioScore.exists)
    }

    @MainActor
    func testEvidenceKeepsSkillAndPortfolioScalesSeparateAndMissingIsNotZero() {
        let app = launchWorkspace()
        app.buttons["evidenceNavigation"].click()

        XCTAssertTrue(app.staticTexts["evidenceTitle"].waitForExistence(timeout: 5))
        XCTAssertTrue(textContaining("2.750 / 4", in: app).waitForExistence(timeout: 5))
        XCTAssertTrue(textContaining("14.000 / 20", in: app).waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Not assessed"].waitForExistence(timeout: 5))
        XCTAssertTrue(textContaining("Missing evidence is not zero", in: app).exists)
        XCTAssertTrue(textContaining("Baseline gap", in: app).exists)
        XCTAssertTrue(textContaining("Final target gap", in: app).exists)
        XCTAssertEqual(textsContaining("streak", in: app).count, 0)
        XCTAssertEqual(textsContaining("recording count", in: app).count, 0)
        XCTAssertEqual(textsContaining("transcript word count", in: app).count, 0)
    }

    @MainActor
    func testEvidenceSkillLineageAndBoundedPagingRemainInspectable() {
        let app = launchWorkspace()
        app.buttons["evidenceNavigation"].click()
        let inspect = app.buttons["evidenceInspectSkill_structured_troubleshooting"]
        reveal(inspect, in: app, scrollIdentifier: "evidenceLedger")
        app.activate()
        inspect.click()

        let older = app.buttons["evidenceSkillOlder"]
        XCTAssertTrue(older.waitForExistence(timeout: 5))
        let manifest = app.disclosureTriangles["evidenceManifest"]
        setDisclosure(manifest, expanded: true, in: app)
        XCTAssertTrue(textContaining("Used weight 0.400 · Event weight 0.800", in: app).waitForExistence(timeout: 5))
        XCTAssertTrue(textContaining("Outside this page; browse older evidence", in: app).exists)

        let event = eventDisclosure(50, in: app)
        XCTAssertTrue(textContaining("Structured troubleshooting ·", in: app).waitForExistence(timeout: 5))
        setDisclosure(event, expanded: true, in: app)
        XCTAssertTrue(textContaining("human coach", in: app).exists)
        XCTAssertTrue(textContaining("no ai", in: app).exists)
        XCTAssertTrue(textContaining("Qualifies", in: app).exists)
        let raw = app.disclosureTriangles["evidenceRawDimensions_50"]
        setDisclosure(raw, expanded: true, in: app)
        XCTAssertTrue(textContaining("Customer impact is explicit", in: app).exists)
        setDisclosure(event, expanded: false, in: app)

        let excluded = eventDisclosure(49, in: app)
        setDisclosure(excluded, expanded: true, in: app)
        XCTAssertTrue(textContaining("Excluded from level", in: app).exists)
        XCTAssertTrue(textContaining("Excluded by formula", in: app).exists)
        setDisclosure(excluded, expanded: false, in: app)

        reveal(older, in: app, scrollIdentifier: "evidenceLedger")
        app.activate()
        older.click()
        XCTAssertTrue(app.staticTexts["Evidence event 39"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["Evidence event 50"].exists)
        let newest = app.buttons["evidenceSkillNewest"]
        reveal(newest, in: app, scrollIdentifier: "evidenceLedger")
        app.activate()
        newest.click()
        XCTAssertTrue(app.staticTexts["Evidence event 50"].waitForExistence(timeout: 5))
    }

    @MainActor
    func testEvidencePortfolioAndActivityPagingDoNotLoseAllEvidenceRoute() {
        let app = launchWorkspace()
        app.buttons["evidenceNavigation"].click()

        let portfolioOlder = app.buttons["evidencePortfolioOlder"]
        reveal(portfolioOlder, in: app, scrollIdentifier: "evidenceLedger")
        portfolioOlder.click()
        XCTAssertTrue(app.descendants(matching: .any)["evidencePortfolio_90"].waitForExistence(timeout: 5))
        let portfolioNewest = app.buttons["evidencePortfolioNewest"]
        reveal(portfolioNewest, in: app, scrollIdentifier: "evidenceLedger")
        portfolioNewest.click()
        XCTAssertTrue(app.descendants(matching: .any)["evidencePortfolio_91"].waitForExistence(timeout: 5))

        let inspect = app.buttons["evidenceInspectPortfolio_91"]
        reveal(inspect, in: app, scrollIdentifier: "evidenceLedger")
        inspect.click()
        let activityOlder = app.buttons["evidenceActivityOlder"]
        XCTAssertTrue(activityOlder.waitForExistence(timeout: 5))
        reveal(activityOlder, in: app, scrollIdentifier: "evidenceLedger")
        activityOlder.click()
        XCTAssertTrue(app.staticTexts["Evidence event 39"].waitForExistence(timeout: 5))

        let allEvidence = app.buttons["evidenceAllActivitiesFromInspector"]
        reveal(allEvidence, in: app, scrollIdentifier: "evidenceLedger")
        allEvidence.click()
        XCTAssertTrue(app.descendants(matching: .any)["evidenceActivityHistory"].waitForNonExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["evidenceTitle"].exists)
    }

    @MainActor
    func testEvidenceEmptyStateNeverInventsZero() {
        let app = launchWorkspace(extra: ["-ui-test-empty-evidence", "-ui-test-evidence-route"])
        app.buttons["todayContinueButton"].click()

        XCTAssertTrue(app.staticTexts["evidenceTitle"].waitForExistence(timeout: 5))
        XCTAssertTrue(textContaining("No qualifying evidence is recorded for this activity", in: app).waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Not assessed"].waitForExistence(timeout: 5))
        XCTAssertGreaterThanOrEqual(textsContaining("Not assessed", in: app).count, 1)
        XCTAssertEqual(textsContaining("0 / 4", in: app).count, 0)
        XCTAssertTrue(app.buttons["evidenceOpenActivity"].exists)
    }

    @MainActor
    func testEvidenceRendersInDarkAppearanceWithLargeTextAndReducedScrollingMotion() {
        let app = launchWorkspace(extra: [
            "-AppleInterfaceStyle", "Dark",
            "-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityExtraExtraExtraLarge",
            "-NSScrollAnimationEnabled", "NO",
        ])
        app.buttons["evidenceNavigation"].click()

        XCTAssertTrue(app.staticTexts["evidenceTitle"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["evidenceRefresh"].isEnabled)
        let inspect = app.buttons["evidenceInspectSkill_structured_troubleshooting"]
        reveal(inspect, in: app, scrollIdentifier: "evidenceLedger")
        XCTAssertTrue(inspect.isHittable)
        capture("Evidence dark large text", app: app)
    }

    @MainActor
    func testEvidenceKeyboardRefreshAndAccessibilityReadingOrder() {
        let app = launchWorkspace(extra: ["-ui-test-evidence-keyboard-refresh"])
        app.buttons["evidenceNavigation"].click()

        XCTAssertTrue(app.staticTexts["evidenceTitle"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Structured troubleshooting"].waitForExistence(timeout: 5))
        app.typeKey("r", modifierFlags: .command)
        XCTAssertTrue(app.staticTexts["Structured troubleshooting refreshed"].waitForExistence(timeout: 5))

        let labels = app.staticTexts.allElementsBoundByAccessibilityElement.map(\.label)
        let expected = [
            "Evidence",
            "See what you demonstrated, how each estimate was calculated, and the evidence behind it.",
            "Skill estimates",
            "Structured troubleshooting refreshed",
            "Portfolio history",
        ]
        let positions = expected.compactMap { labels.firstIndex(of: $0) }
        XCTAssertEqual(positions.count, expected.count, "Expected all Evidence landmarks in the accessibility tree")
        XCTAssertEqual(positions, positions.sorted(), "Evidence landmarks must follow their visual reading order")
    }

    @MainActor
    func testApplicationCannotOpenAnIndependentSecondWorkspace() {
        let app = launchWorkspace()
        XCTAssertEqual(app.windows.count, 1)
        app.typeKey("n", modifierFlags: [.command])
        XCTAssertFalse(app.windows.element(boundBy: 1).waitForExistence(timeout: 1))
        XCTAssertEqual(app.windows.count, 1)
    }

    @MainActor
    func testDraftSurvivesNavigationButNotSignOut() {
        let app = launchWorkspace()
        app.buttons["todayContinueButton"].click()
        let audience = app.textViews["Audience"]
        reveal(audience, in: app)
        audience.click()
        audience.typeText("Private customer draft")
        app.buttons["todayNavigation"].click()
        XCTAssertTrue(app.buttons["todayContinueButton"].waitForExistence(timeout: 5))
        app.buttons["todayContinueButton"].click()
        reveal(audience, in: app)
        XCTAssertEqual(audience.value as? String, "Private customer draft")
        app.buttons["signOutButton"].click()
        XCTAssertTrue(app.buttons["signInButton"].waitForExistence(timeout: 5))
        app.buttons["signInButton"].click()
        XCTAssertTrue(app.buttons["todayContinueButton"].waitForExistence(timeout: 5))
        app.buttons["todayContinueButton"].click()
        reveal(audience, in: app)
        XCTAssertEqual(audience.value as? String, "")
    }

    @MainActor
    func testCommittedActivityRequiresCompleteSelfReview() {
        let app = launchWorkspace(extra: ["-ui-test-self-review"])
        app.buttons["todayContinueButton"].click()
        let submit = app.buttons["Submit self-review"]
        reveal(submit, in: app)
        XCTAssertFalse(submit.isEnabled)
        let scroll = app.scrollViews["activityWorkspaceScroll"]
        scroll.scroll(byDeltaX: 0, deltaY: 2_000)
        for title in ["Main answer or decision", "What I did well", "Where structure was weak",
                      "Where I became vague", "Where I hesitated", "What I will change"] {
            let editor = app.textViews[title]
            reveal(editor, in: app)
            editor.click()
            editor.typeText("Clear impact.")
        }
        reveal(submit, in: app)
        XCTAssertTrue(submit.isEnabled)
        submit.click()
        let summary = app.staticTexts["activitySelfReviewSummary"]
        // Wait for the command, detail reload, and macOS accessibility snapshot.
        XCTAssertTrue(summary.waitForExistence(timeout: 20))
        XCTAssertEqual(summary.value as? String, "Your score: 0 / 4. AI analysis has not been requested.")
        XCTAssertFalse(app.buttons["Commit Attempt A"].exists)
    }

    @MainActor
    private func reveal(_ element: XCUIElement, in app: XCUIApplication, scrollIdentifier: String = "activityWorkspaceScroll") {
        app.activate()
        let scroll = app.scrollViews[scrollIdentifier]
        XCTAssertTrue(scroll.waitForExistence(timeout: 5))
        for _ in 0..<12 {
            app.activate()
            if element.exists && element.isHittable && scroll.frame.contains(element.frame) { return }
            scroll.scroll(byDeltaX: 0, deltaY: -350)
        }
        XCTAssertTrue(element.exists && element.isHittable && scroll.frame.contains(element.frame),
                      "Expected control fully inside the scrolling viewport")
    }

    @MainActor
    private func capture(_ name: String, app: XCUIApplication) {
        let attachment = XCTAttachment(screenshot: app.windows.firstMatch.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    @MainActor
    private func setDisclosure(_ element: XCUIElement, expanded: Bool, in app: XCUIApplication) {
        reveal(element, in: app, scrollIdentifier: "evidenceLedger")
        let target = expanded ? "1" : "0"
        if disclosureValue(element) != target {
            app.activate()
            let chevronOffset = min(0.5, 24 / max(element.frame.width, 1))
            element.coordinate(withNormalizedOffset: CGVector(dx: chevronOffset, dy: 0.5)).click()
        }
        XCTAssertEqual(disclosureValue(element), target)
    }

    @MainActor
    private func disclosureValue(_ element: XCUIElement) -> String {
        if let value = element.value as? String { return value }
        if let value = element.value as? NSNumber { return value.stringValue }
        return ""
    }

    @MainActor
    private func eventDisclosure(_ id: Int, in app: XCUIApplication) -> XCUIElement {
        app.disclosureTriangles.matching(NSPredicate(
            format: "label BEGINSWITH[c] %@",
            "Evidence event \(id),"
        )).firstMatch
    }

    @MainActor
    private func textsContaining(_ value: String, in app: XCUIApplication) -> XCUIElementQuery {
        app.staticTexts.matching(NSPredicate(
            format: "label CONTAINS[c] %@ OR value CONTAINS[c] %@",
            value,
            value
        ))
    }

    @MainActor
    private func textContaining(_ value: String, in app: XCUIApplication) -> XCUIElement {
        textsContaining(value, in: app).firstMatch
    }

    @MainActor
    func testTodayOpensActivityAndTimerSurvivesNavigation() {
        let app = launchWorkspace()
        let next = app.buttons["todayContinueButton"]
        XCTAssertTrue(next.waitForExistence(timeout: 5))
        capture("Today workspace", app: app)
        next.click()
        let start = app.buttons["Start activity"]
        XCTAssertTrue(start.waitForExistence(timeout: 5))
        start.click()
        let pause = app.buttons["Pause"]
        XCTAssertTrue(pause.waitForExistence(timeout: 5))
        capture("Activity workspace", app: app)
        pause.click()
        XCTAssertTrue(app.buttons["Resume"].waitForExistence(timeout: 5))
        app.buttons["todayNavigation"].click()
        XCTAssertTrue(next.waitForExistence(timeout: 5))
        next.click()
        XCTAssertTrue(app.buttons["Resume"].waitForExistence(timeout: 5))
        app.buttons["Resume"].click()
        XCTAssertTrue(app.buttons["Pause"].waitForExistence(timeout: 5))
    }

    @MainActor
    func testTodayDailyCloseRequiresEvidenceAndSaves() {
        let app = launchWorkspace(extra: ["-ui-test-daily-close"])
        XCTAssertTrue(app.buttons["todayContinueButton"].waitForExistence(timeout: 5))
        app.buttons["todayContinueButton"].click()
        let close = app.buttons["todayCloseDayButton"]
        XCTAssertTrue(close.waitForExistence(timeout: 5))
        XCTAssertFalse(close.isEnabled)
        app.textViews["Strongest output"].click()
        app.textViews["Strongest output"].typeText("Clear rollback recommendation.")
        app.textViews["Repeated mistake"].click()
        app.textViews["Repeated mistake"].typeText("Impact came too late.")
        app.checkBoxes["todayEvidenceConfirmation"].click()
        close.click()
        XCTAssertTrue(app.staticTexts["Daily close saved."].waitForExistence(timeout: 5))
    }

    @MainActor
    func testRoadmapSelectValidateApproveActivate() throws {
        let package = FileManager.default.temporaryDirectory.appendingPathComponent("roadmap-ui-\(UUID().uuidString).zip")
        try Data("redacted transport fixture".utf8).write(to: package)
        defer { try? FileManager.default.removeItem(at: package) }
        let app = launchWorkspace()
        app.buttons["roadmapsNavigation"].click()
        let choose = app.buttons["Choose ZIP or folder"]
        XCTAssertTrue(choose.waitForExistence(timeout: 5))
        choose.click()
        app.typeKey("g", modifierFlags: [.command, .shift])
        let location = app.textFields.firstMatch
        XCTAssertTrue(location.waitForExistence(timeout: 5))
        location.typeText(package.path)
        app.typeKey(.return, modifierFlags: [])
        app.windows["open-panel"].buttons["OKButton"].click()
        let review = app.buttons["Review package"]
        XCTAssertTrue(review.waitForExistence(timeout: 5))
        review.click()
        XCTAssertTrue(app.staticTexts["Validation passed"].waitForExistence(timeout: 5))
        capture("Roadmap validation", app: app)
        let inspect = app.buttons["Inspect all changes, fields, and values"]
        reveal(inspect, in: app, scrollIdentifier: "roadmapWorkspaceScroll")
        inspect.click()
        XCTAssertTrue(app.staticTexts["Before"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["After"].exists)
        let collapse = app.buttons["Show bounded preview"]
        reveal(collapse, in: app, scrollIdentifier: "roadmapWorkspaceScroll")
        collapse.click()
        let approve = app.buttons["Approve roadmap"]
        XCTAssertFalse(approve.isEnabled)
        let confirmation = app.checkBoxes["roadmapApprovalConfirmation"]
        reveal(confirmation, in: app, scrollIdentifier: "roadmapWorkspaceScroll")
        confirmation.click()
        reveal(approve, in: app, scrollIdentifier: "roadmapWorkspaceScroll")
        approve.click()
        let activate = app.buttons["Activate Month 1"]
        XCTAssertTrue(activate.waitForExistence(timeout: 5))
        reveal(activate, in: app, scrollIdentifier: "roadmapWorkspaceScroll")
        activate.click()
        XCTAssertTrue(app.staticTexts["Month 1 is active"].waitForExistence(timeout: 5))
    }

    @MainActor
    private func launchWorkspace(extra: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-ApplePersistenceIgnoreState", "YES", "-ui-test-signed-in", "-ui-test-native-features"] + extra
        app.launch()
        XCTAssertTrue(app.buttons["todayNavigation"].waitForExistence(timeout: 5))
        app.activate()
        return app
    }

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
        XCTAssertFalse(app.buttons["evidenceNavigation"].exists)
        let signOut = app.buttons["signOutButton"]
        XCTAssertTrue(signOut.waitForExistence(timeout: 5))
        signOut.click()
        XCTAssertTrue(app.buttons["signInButton"].waitForExistence(timeout: 5))
    }
}
