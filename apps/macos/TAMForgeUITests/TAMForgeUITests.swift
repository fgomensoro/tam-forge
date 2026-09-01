import XCTest

final class TAMForgeUITests: XCTestCase {
    @MainActor
    func testNativeFoundationParityJourney() throws {
        let fixtureURL = try XCTUnwrap(
            Bundle(for: Self.self).url(forResource: "foundation-journey-v1", withExtension: "json")
        )
        let packageURL = try XCTUnwrap(
            Bundle(for: Self.self).url(forResource: "month-v1", withExtension: "zip")
        )
        let fixtureData = try Data(contentsOf: fixtureURL)
        let fixture = try XCTUnwrap(
            JSONSerialization.jsonObject(with: fixtureData) as? [String: Any]
        )
        let journey = try XCTUnwrap(fixture["journey"] as? [String: Any])
        let output = try XCTUnwrap(journey["output"] as? [String: Any])
        let selfReview = try XCTUnwrap(journey["self_review"] as? [String: Any])

        let app = launchWorkspace(
            extra: ["-ui-test-parity-journey"],
            environment: ["TAMFORGE_UI_FIXTURE_BASE64": fixtureData.base64EncodedString()]
        )

        app.buttons["roadmapsNavigation"].click()
        chooseRoadmapPackage(packageURL, in: app)
        app.buttons["Review package"].click()
        XCTAssertTrue(app.staticTexts["Validation passed"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["158 tasks"].exists)
        let confirmation = app.checkBoxes["roadmapApprovalConfirmation"]
        reveal(confirmation, in: app, scrollIdentifier: "roadmapWorkspaceScroll")
        confirmation.click()
        let approve = app.buttons["Approve roadmap"]
        reveal(approve, in: app, scrollIdentifier: "roadmapWorkspaceScroll")
        approve.click()
        let activate = app.buttons["Activate Month 1"]
        XCTAssertTrue(activate.waitForExistence(timeout: 10))
        reveal(activate, in: app, scrollIdentifier: "roadmapWorkspaceScroll")
        activate.click()
        XCTAssertTrue(app.staticTexts["Month 1 is active"].waitForExistence(timeout: 10))

        app.buttons["todayNavigation"].click()
        XCTAssertTrue(textContaining("240 planned minutes", in: app).waitForExistence(timeout: 10))
        XCTAssertTrue(textContaining("45 minutes", in: app).exists)
        app.buttons["todayContinueButton"].click()
        XCTAssertTrue(app.buttons["Start activity"].waitForExistence(timeout: 10))
        app.buttons["Start activity"].click()
        XCTAssertTrue(app.buttons["Pause"].waitForExistence(timeout: 10))
        app.buttons["Pause"].click()
        XCTAssertTrue(app.buttons["Resume"].waitForExistence(timeout: 10))
        app.buttons["todayNavigation"].click()
        app.buttons["todayContinueButton"].click()
        XCTAssertTrue(app.buttons["Resume"].waitForExistence(timeout: 10))
        app.buttons["Resume"].click()
        let hideSource = app.buttons["Hide source"]
        reveal(hideSource, in: app)
        hideSource.click()
        XCTAssertTrue(app.staticTexts["Closed-source mode is active. Recall from memory before reopening material."].waitForExistence(timeout: 10))

        let outputFields: [(String, Any?)] = [
            ("Audience", output["audience"]),
            ("Key idea 1", (output["key_ideas"] as? [String])?[safe: 0]),
            ("Key idea 2", (output["key_ideas"] as? [String])?[safe: 1]),
            ("Key idea 3", (output["key_ideas"] as? [String])?[safe: 2]),
            ("Boundary or failure mode", output["boundary_or_failure"]),
            ("TAM or customer example", output["tam_customer_example"]),
            ("Unresolved question", output["unresolved_question"]),
        ]
        for (label, rawValue) in outputFields {
            let editor = app.textViews[label]
            reveal(editor, in: app)
            editor.click()
            editor.typeText(try XCTUnwrap(rawValue as? String))
        }
        let immutable = app.checkBoxes["activityImmutabilityAcknowledgment"]
        reveal(immutable, in: app)
        immutable.click()
        let commit = app.buttons["Commit Attempt A"]
        reveal(commit, in: app)
        XCTAssertTrue(commit.isEnabled)
        commit.click()
        XCTAssertTrue(app.staticTexts["Attempt A is committed and read-only."].waitForExistence(timeout: 10))
        XCTAssertFalse(app.buttons["Commit Attempt A"].exists)

        let reviewFields: [(String, String)] = [
            ("Main answer or decision", "main_answer"),
            ("What I did well", "did_well"),
            ("Where structure was weak", "structure_weakness"),
            ("Where I became vague", "vague_points"),
            ("Where I hesitated", "hesitation_points"),
            ("What I will change", "change_next"),
        ]
        for (label, key) in reviewFields {
            let editor = app.textViews[label]
            reveal(editor, in: app)
            editor.click()
            editor.typeText(try XCTUnwrap(selfReview[key] as? String))
        }
        let score = app.popUpButtons["activitySelfScore"]
        reveal(score, in: app)
        score.click()
        app.menuItems["3"].click()
        let submit = app.buttons["Submit self-review"]
        reveal(submit, in: app)
        submit.click()
        XCTAssertTrue(app.staticTexts["activitySelfReviewSummary"].waitForExistence(timeout: 10))
        XCTAssertEqual(
            app.staticTexts["activitySelfReviewSummary"].value as? String,
            "Your score: 3 / 4. AI analysis has not been requested."
        )

        app.buttons["evidenceNavigation"].click()
        XCTAssertTrue(app.staticTexts["Not assessed"].waitForExistence(timeout: 10))
        XCTAssertEqual(textsContaining("streak", in: app).count, 0)
        XCTAssertEqual(textsContaining("recording count", in: app).count, 0)
        XCTAssertEqual(textsContaining("transcript word count", in: app).count, 0)

        app.buttons["notificationToggle"].click()
        let markRead = app.buttons.matching(
            NSPredicate(format: "label == %@", "Mark Feedback ready as read")
        ).firstMatch
        XCTAssertTrue(markRead.waitForExistence(timeout: 10))
        app.typeKey(.return, modifierFlags: [])
        XCTAssertTrue(markRead.waitForNonExistence(timeout: 10))
        XCTAssertEqual(app.buttons["notificationToggle"].label, "Notifications")
    }

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
        XCTAssertEqual(retry.label, "Retry skill estimates")
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
        XCTAssertTrue(textContaining("2.410 / 4", in: app).waitForExistence(timeout: 5))
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
        XCTAssertEqual(older.label, "Older skill evidence")
        let manifest = app.disclosureTriangles["evidenceManifest"]
        setDisclosure(manifest, expanded: true, in: app)
        XCTAssertTrue(textContaining("Used weight 0.154375 · Event weight 0.617500", in: app).waitForExistence(timeout: 5))
        XCTAssertTrue(textContaining("Outside this page; browse older evidence", in: app).exists)

        let event = eventDisclosure(50, in: app)
        XCTAssertTrue(textContaining("Structured troubleshooting ·", in: app).waitForExistence(timeout: 5))
        setDisclosure(event, expanded: true, in: app)
        XCTAssertTrue(textContaining("human coach", in: app).exists)
        XCTAssertTrue(textContaining("no ai", in: app).exists)
        XCTAssertTrue(textContaining("Qualifies", in: app).exists)
        let raw = app.disclosureTriangles["evidenceRawDimensions_50"]
        setDisclosure(raw, expanded: true, in: app)
        XCTAssertTrue(textContaining("Dimension score", in: app).exists)
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
        XCTAssertTrue(newest.waitForExistence(timeout: 5))
        XCTAssertEqual(newest.label, "Newest skill evidence")
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
        XCTAssertTrue(portfolioOlder.waitForExistence(timeout: 5))
        XCTAssertEqual(portfolioOlder.label, "Older portfolio history")
        reveal(portfolioOlder, in: app, scrollIdentifier: "evidenceLedger")
        portfolioOlder.click()
        XCTAssertTrue(app.descendants(matching: .any)["evidencePortfolio_90"].waitForExistence(timeout: 5))
        let portfolioNewest = app.buttons["evidencePortfolioNewest"]
        XCTAssertTrue(portfolioNewest.waitForExistence(timeout: 5))
        XCTAssertEqual(portfolioNewest.label, "Newest portfolio history")
        reveal(portfolioNewest, in: app, scrollIdentifier: "evidenceLedger")
        portfolioNewest.click()
        XCTAssertTrue(app.descendants(matching: .any)["evidencePortfolio_91"].waitForExistence(timeout: 5))

        let inspect = app.buttons["evidenceInspectPortfolio_91"]
        reveal(inspect, in: app, scrollIdentifier: "evidenceLedger")
        inspect.click()
        let activityOlder = app.buttons["evidenceActivityOlder"]
        XCTAssertTrue(activityOlder.waitForExistence(timeout: 5))
        XCTAssertEqual(activityOlder.label, "Older activity evidence")
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

        let skillGroup = app.groups["evidenceSkill_structured_troubleshooting"]
        let portfolioGroup = app.groups["evidencePortfolio_91"]
        XCTAssertTrue(skillGroup.staticTexts["evidenceSkillName_structured_troubleshooting"].exists)
        XCTAssertTrue(portfolioGroup.staticTexts["Portfolio judgment"].exists)

        let landmarks = [
            app.staticTexts["evidenceTitle"],
            app.staticTexts["evidenceIntro"],
            app.staticTexts["Skill estimates"],
            app.staticTexts["evidenceSkillName_structured_troubleshooting"],
            app.staticTexts["Portfolio history"],
        ]
        XCTAssertTrue(landmarks.allSatisfy(\.exists), "Expected all Evidence landmarks in the accessibility tree")
        let topEdges = landmarks.map { $0.frame.minY }
        XCTAssertEqual(topEdges, topEdges.sorted(), "Evidence landmarks must follow their visual reading order")
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
    private func launchWorkspace(
        extra: [String] = [], environment: [String: String] = [:]
    ) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-ApplePersistenceIgnoreState", "YES", "-ui-test-signed-in", "-ui-test-native-features"] + extra
        for (key, value) in environment { app.launchEnvironment[key] = value }
        app.launch()
        XCTAssertTrue(app.buttons["todayNavigation"].waitForExistence(timeout: 5))
        app.activate()
        return app
    }

    @MainActor
    private func chooseRoadmapPackage(_ package: URL, in app: XCUIApplication) {
        let choose = app.buttons["Choose ZIP or folder"]
        XCTAssertTrue(choose.waitForExistence(timeout: 5))
        choose.click()
        app.typeKey("g", modifierFlags: [.command, .shift])
        let location = app.textFields.firstMatch
        XCTAssertTrue(location.waitForExistence(timeout: 5))
        location.typeText(package.path)
        app.typeKey(.return, modifierFlags: [])
        app.windows["open-panel"].buttons["OKButton"].click()
        XCTAssertTrue(app.buttons["Review package"].waitForExistence(timeout: 5))
    }

    @MainActor
    func testLocalNativeResourceReceipt() throws {
        let configURL = URL(
            fileURLWithPath: "/tmp/tamforge-native-resource-receipt-config.json"
        )
        guard let configData = try? Data(contentsOf: configURL) else {
            throw XCTSkip("opt-in local 8-minute resource receipt")
        }
        let config = try XCTUnwrap(
            JSONSerialization.jsonObject(with: configData) as? [String: String]
        )
        let receiptPath = try XCTUnwrap(config["receipt_path"])
        let gitSHA = try XCTUnwrap(config["git_sha"])
        let fixtureURL = try XCTUnwrap(
            Bundle(for: Self.self).url(
                forResource: "foundation-journey-v1", withExtension: "json"
            )
        )
        let fixtureData = try Data(contentsOf: fixtureURL)
        let app = XCUIApplication()
        app.launchArguments = [
            "-ApplePersistenceIgnoreState", "YES",
            "-ui-test-signed-in",
            "-ui-test-native-features",
            "-ui-test-parity-journey",
        ]
        app.launchEnvironment["TAMFORGE_UI_FIXTURE_BASE64"] =
            fixtureData.base64EncodedString()

        var launchSeconds: [Double] = []
        for _ in 0..<5 {
            if app.state != .notRunning {
                app.terminate()
                XCTAssertTrue(waitForTermination(app, timeout: 10))
            }
            let startedAt = ContinuousClock.now
            app.launch()
            XCTAssertTrue(
                textContaining("240 planned minutes", in: app)
                    .waitForExistence(timeout: 15)
            )
            let duration = startedAt.duration(to: .now).components
            launchSeconds.append(
                Double(duration.seconds) + Double(duration.attoseconds) / 1_000_000_000_000_000_000
            )
        }

        app.buttons["evidenceNavigation"].click()
        XCTAssertTrue(app.staticTexts["Not assessed"].waitForExistence(timeout: 10))
        let pid = try tamForgeProcessID()

        Thread.sleep(forTimeInterval: 60)
        var idleRSSKiB: [Int] = []
        for _ in 0..<300 {
            idleRSSKiB.append(try residentMemoryKiB(pid: pid))
            Thread.sleep(forTimeInterval: 1)
        }

        var navigationRSSKiB: [Int] = []
        for _ in 0..<20 {
            app.buttons["todayNavigation"].click()
            XCTAssertTrue(
                textContaining("240 planned minutes", in: app)
                    .waitForExistence(timeout: 5)
            )
            app.buttons["evidenceNavigation"].click()
            XCTAssertTrue(app.staticTexts["evidenceTitle"].waitForExistence(timeout: 5))
            app.buttons["evidenceRefresh"].click()
            XCTAssertTrue(app.staticTexts["Not assessed"].waitForExistence(timeout: 5))
            navigationRSSKiB.append(try residentMemoryKiB(pid: pid))
        }
        Thread.sleep(forTimeInterval: 60)
        let finalRSSKiB = try residentMemoryKiB(pid: pid)

        let idleP50MiB = mib(percentile(0.50, values: idleRSSKiB))
        let idleP95MiB = mib(percentile(0.95, values: idleRSSKiB))
        let finalMiB = mib(finalRSSKiB)
        XCTAssertLessThanOrEqual(idleP95MiB, 180.0, "idle p95 exceeded the locked gate")
        XCTAssertLessThanOrEqual(
            finalMiB,
            idleP95MiB + 20.0,
            "retired Evidence pages remained resident after 20 navigation cycles"
        )

        let receipt: [String: Any] = [
            "schema_version": 1,
            "git_sha": gitSHA,
            "scenario": "DEBUG shared parity fixture; Today and Evidence usable",
            "build": "ad-hoc signed macOS app; xcodebuild -jobs 2",
            "hardware_model": try command("/usr/sbin/sysctl", ["-n", "hw.model"]),
            "physical_memory_bytes": ProcessInfo.processInfo.physicalMemory,
            "macos": ProcessInfo.processInfo.operatingSystemVersionString,
            "launch_count": launchSeconds.count,
            "launch_seconds": launchSeconds,
            "launch_p50_seconds": percentile(0.50, values: launchSeconds),
            "launch_p95_seconds": percentile(0.95, values: launchSeconds),
            "settle_seconds": 60,
            "idle_sample_interval_seconds": 1,
            "idle_sample_count": idleRSSKiB.count,
            "idle_rss_mib": [
                "min": mib(idleRSSKiB.min() ?? 0),
                "p50": idleP50MiB,
                "p95": idleP95MiB,
                "max": mib(idleRSSKiB.max() ?? 0),
            ],
            "navigation_cycles": navigationRSSKiB.count,
            "navigation_peak_rss_mib": mib(navigationRSSKiB.max() ?? 0),
            "post_cycle_settle_seconds": 60,
            "post_cycle_rss_mib": finalMiB,
        ]
        let receiptData = try JSONSerialization.data(
            withJSONObject: receipt, options: [.prettyPrinted, .sortedKeys]
        )
        let receiptURL = URL(fileURLWithPath: receiptPath)
        try receiptData.write(to: receiptURL, options: .atomic)
        let attachment = XCTAttachment(data: receiptData, uniformTypeIdentifier: "public.json")
        attachment.name = "tamforge-native-resource-receipt"
        attachment.lifetime = .keepAlways
        add(attachment)
        print("Native resource receipt: \(receiptURL.path)")
    }

    private func waitForTermination(_ app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while app.state != .notRunning && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.1)
        }
        return app.state == .notRunning
    }

    private func tamForgeProcessID() throws -> Int32 {
        let output = try command("/usr/bin/pgrep", ["-x", "TAMForge"])
        let pids = output.split(separator: "\n").compactMap { Int32($0) }
        return try XCTUnwrap(pids.max(), "TAMForge process was not found")
    }

    private func residentMemoryKiB(pid: Int32) throws -> Int {
        let output = try command("/bin/ps", ["-o", "rss=", "-p", String(pid)])
        return try XCTUnwrap(Int(output.trimmingCharacters(in: .whitespacesAndNewlines)))
    }

    private func command(_ executable: String, _ arguments: [String]) throws -> String {
        let process = Process()
        let stdout = Pipe()
        let stderr = Pipe()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        process.standardOutput = stdout
        process.standardError = stderr
        try process.run()
        process.waitUntilExit()
        let output = stdout.fileHandleForReading.readDataToEndOfFile()
        let error = stderr.fileHandleForReading.readDataToEndOfFile()
        XCTAssertEqual(
            process.terminationStatus,
            0,
            String(data: error, encoding: .utf8) ?? "command failed"
        )
        return String(data: output, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    }

    private func percentile<T: BinaryFloatingPoint>(_ fraction: T, values: [T]) -> T {
        let sorted = values.sorted()
        let index = max(0, min(sorted.count - 1, Int((fraction * T(sorted.count)).rounded(.up)) - 1))
        return sorted[index]
    }

    private func percentile(_ fraction: Double, values: [Int]) -> Int {
        let sorted = values.sorted()
        let index = max(0, min(sorted.count - 1, Int(ceil(fraction * Double(sorted.count))) - 1))
        return sorted[index]
    }

    private func mib(_ kibibytes: Int) -> Double { Double(kibibytes) / 1024.0 }

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

private extension Array {
    subscript(safe index: Index) -> Element? {
        indices.contains(index) ? self[index] : nil
    }
}
