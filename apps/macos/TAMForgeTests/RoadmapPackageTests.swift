import Foundation
import XCTest

final class RoadmapPackageTests: XCTestCase {
    func testFolderEntriesNormalizeRelativePathsAndRejectCollisions() throws {
        let fileURL = try temporaryFile(contents: Data("redacted roadmap".utf8))
        defer { try? FileManager.default.removeItem(at: fileURL) }
        let file = try RoadmapLocalFile(url: fileURL, maximumBytes: 1024)

        let first = try RoadmapFolderEntry(relativePath: "Week 1//./README.md", file: file)
        let second = try RoadmapFolderEntry(relativePath: "Week 1/README.md", file: file)
        let differentCase = try RoadmapFolderEntry(relativePath: "week 1/readme.md", file: file)

        XCTAssertEqual(first.relativePath, "Week 1/README.md")
        XCTAssertThrowsError(try RoadmapFolderPackage(entries: [first, second])) { error in
            XCTAssertEqual(error as? RoadmapPackageError, .duplicateRelativePath)
        }
        XCTAssertThrowsError(try RoadmapFolderPackage(entries: [first, differentCase])) { error in
            XCTAssertEqual(error as? RoadmapPackageError, .duplicateRelativePath)
        }
    }

    func testFolderEntryRejectsInvalidRelativePathWithoutExposingSourcePath() throws {
        let fileURL = try temporaryFile(contents: Data("redacted roadmap".utf8))
        defer { try? FileManager.default.removeItem(at: fileURL) }
        let file = try RoadmapLocalFile(url: fileURL, maximumBytes: 1024)

        XCTAssertThrowsError(try RoadmapFolderEntry(relativePath: "/private/source.md", file: file)) { error in
            XCTAssertEqual(error as? RoadmapPackageError, .invalidRelativePath)
            XCTAssertFalse(String(describing: error).contains("source.md"))
        }
    }

    func testPackageRejectsOversizedFilesBeforeStaging() throws {
        let fileURL = try temporaryFile(contents: Data("four".utf8))
        defer { try? FileManager.default.removeItem(at: fileURL) }

        XCTAssertThrowsError(try RoadmapLocalFile(url: fileURL, maximumBytes: 3)) { error in
            XCTAssertEqual(error as? RoadmapPackageError, .fileTooLarge)
        }
    }

    func testFolderSelectionKeepsNestedRelativePaths() async throws {
        let root = try FileManager.default.url(
            for: .itemReplacementDirectory,
            in: .userDomainMask,
            appropriateFor: FileManager.default.temporaryDirectory,
            create: true
        )
        defer { try? FileManager.default.removeItem(at: root) }
        let week = root.appendingPathComponent("Week 1")
        try FileManager.default.createDirectory(at: week, withIntermediateDirectories: true)
        try Data("redacted roadmap".utf8).write(to: week.appendingPathComponent("README.md"))

        let selection = try await RoadmapPackagePicker.package(for: root)

        guard case let .folder(folder) = selection else {
            return XCTFail("Expected folder package")
        }
        XCTAssertEqual(folder.entries.map(\.relativePath), ["Week 1/README.md"])
    }

    private func temporaryFile(contents: Data) throws -> URL {
        let fileURL = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try contents.write(to: fileURL)
        return fileURL
    }
}
