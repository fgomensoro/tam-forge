import AppKit
import Foundation
import UniformTypeIdentifiers

enum RoadmapPackageError: Error, Equatable, Sendable {
    case invalidSelection
    case invalidRelativePath
    case duplicateRelativePath
    case notRegularFile
    case fileTooLarge
    case packageTooLarge
    case tooManyFiles
    case sourceChanged
}

struct RoadmapPackageLimits: Sendable {
    static let standard = Self(
        maximumZipBytes: 32 * 1024 * 1024,
        maximumFileBytes: 16 * 1024 * 1024,
        maximumFolderBytes: 64 * 1024 * 1024,
        maximumFolderEntries: 512
    )

    let maximumZipBytes: Int64
    let maximumFileBytes: Int64
    let maximumFolderBytes: Int64
    let maximumFolderEntries: Int
}

struct RoadmapSecurityScope: Sendable {
    let start: @Sendable () -> Bool
    let stop: @Sendable () -> Void

    static let unscoped = Self(start: { false }, stop: {})

    static func selectedURL(_ url: URL) -> Self {
        Self(
            start: { url.startAccessingSecurityScopedResource() },
            stop: { url.stopAccessingSecurityScopedResource() }
        )
    }

    func withAccess<T: Sendable>(
        _ operation: @Sendable () async throws -> T
    ) async throws -> T {
        let started = start()
        defer {
            if started { stop() }
        }
        return try await operation()
    }
}

struct RoadmapLocalFile: Sendable {
    let url: URL
    let byteCount: Int64

    init(url: URL, maximumBytes: Int64) throws {
        let values = try url.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
        guard values.isRegularFile == true else { throw RoadmapPackageError.notRegularFile }
        let byteCount = Int64(values.fileSize ?? -1)
        guard byteCount >= 0 else { throw RoadmapPackageError.notRegularFile }
        guard byteCount <= maximumBytes else { throw RoadmapPackageError.fileTooLarge }
        self.url = url
        self.byteCount = byteCount
    }
}

struct RoadmapFolderEntry: Sendable {
    let relativePath: String
    let file: RoadmapLocalFile

    init(relativePath: String, file: RoadmapLocalFile) throws {
        self.relativePath = try RoadmapRelativePath.normalize(relativePath)
        self.file = file
    }
}

struct RoadmapFolderPackage: Sendable {
    let entries: [RoadmapFolderEntry]
    let scope: RoadmapSecurityScope

    init(
        entries: [RoadmapFolderEntry],
        scope: RoadmapSecurityScope = .unscoped,
        limits: RoadmapPackageLimits = .standard
    ) throws {
        guard !entries.isEmpty else { throw RoadmapPackageError.invalidSelection }
        guard entries.count <= limits.maximumFolderEntries else { throw RoadmapPackageError.tooManyFiles }

        var paths = Set<String>()
        var caseFoldedPaths = Set<String>()
        var totalBytes: Int64 = 0
        for entry in entries {
            guard paths.insert(entry.relativePath).inserted,
                  caseFoldedPaths.insert(entry.relativePath.folding(
                      options: [.caseInsensitive],
                      locale: Locale(identifier: "en_US_POSIX")
                  )).inserted
            else {
                throw RoadmapPackageError.duplicateRelativePath
            }
            guard entry.file.byteCount <= limits.maximumFileBytes else {
                throw RoadmapPackageError.fileTooLarge
            }
            totalBytes += entry.file.byteCount
            guard totalBytes <= limits.maximumFolderBytes else {
                throw RoadmapPackageError.packageTooLarge
            }
        }
        self.entries = entries.sorted { $0.relativePath < $1.relativePath }
        self.scope = scope
    }
}

enum RoadmapPackage: Sendable {
    case zip(RoadmapLocalFile, scope: RoadmapSecurityScope = .unscoped)
    case folder(RoadmapFolderPackage)

    var kind: String {
        switch self {
        case .zip: "zip"
        case .folder: "folder_entries"
        }
    }

    var displayName: String {
        switch self {
        case .zip: "ZIP package selected"
        case let .folder(folder): "\(folder.entries.count) files selected"
        }
    }

    func withSecurityScopedAccess<T: Sendable>(
        _ operation: @Sendable () async throws -> T
    ) async throws -> T {
        switch self {
        case let .zip(_, scope): try await scope.withAccess(operation)
        case let .folder(folder): try await folder.scope.withAccess(operation)
        }
    }
}

enum RoadmapRelativePath {
    static func normalize(_ rawPath: String) throws -> String {
        let path = rawPath.precomposedStringWithCanonicalMapping.replacingOccurrences(of: "\\", with: "/")
        guard !path.isEmpty,
              !path.hasPrefix("/"),
              !path.hasPrefix("//"),
              !hasWindowsDrivePrefix(path),
              !path.unicodeScalars.contains(where: { $0.value < 32 || $0.value == 127 })
        else {
            throw RoadmapPackageError.invalidRelativePath
        }
        let rawParts = path.split(separator: "/", omittingEmptySubsequences: false)
        guard !rawParts.contains("..") else { throw RoadmapPackageError.invalidRelativePath }
        let parts = rawParts.filter { !$0.isEmpty && $0 != "." }
        guard !parts.isEmpty else { throw RoadmapPackageError.invalidRelativePath }
        return parts.joined(separator: "/")
    }

    private static func hasWindowsDrivePrefix(_ value: String) -> Bool {
        guard value.count >= 2 else { return false }
        let prefix = value.prefix(2)
        guard prefix.last == ":", let first = prefix.first else { return false }
        return first.isASCII && first.isLetter
    }
}

@MainActor
enum RoadmapPackagePicker {
    static func select() async throws -> RoadmapPackage? {
        let panel = NSOpenPanel()
        panel.title = "Choose roadmap ZIP or folder"
        panel.message = "Choose one exported roadmap ZIP or folder. TAM Forge never reads your Obsidian vault automatically."
        panel.prompt = "Choose"
        panel.canChooseFiles = true
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.allowedContentTypes = [.zip, .folder]
        guard await panel.begin() == .OK, let url = panel.url else { return nil }
        return try await package(for: url)
    }

    static func package(for selectedURL: URL) async throws -> RoadmapPackage {
        let scope = RoadmapSecurityScope.selectedURL(selectedURL)
        let isDirectory = try await scope.withAccess {
            try selectedURL.resourceValues(forKeys: [.isDirectoryKey]).isDirectory == true
        }
        if isDirectory {
            let entries = try await scope.withAccess {
                let scanTask = Task.detached(priority: .userInitiated) {
                    try RoadmapFolderScanner.scan(root: selectedURL)
                }
                return try await withTaskCancellationHandler(
                    operation: { try await scanTask.value },
                    onCancel: { scanTask.cancel() }
                )
            }
            return .folder(try RoadmapFolderPackage(entries: entries, scope: scope))
        }
        guard selectedURL.pathExtension.lowercased() == "zip" else {
            throw RoadmapPackageError.invalidSelection
        }
        let file = try await scope.withAccess {
            try RoadmapLocalFile(
                url: selectedURL,
                maximumBytes: RoadmapPackageLimits.standard.maximumZipBytes
            )
        }
        return .zip(file, scope: scope)
    }
}

private enum RoadmapFolderScanner {
    static func scan(root: URL) throws -> [RoadmapFolderEntry] {
        let limits = RoadmapPackageLimits.standard
        let keys: Set<URLResourceKey> = [.isDirectoryKey, .isRegularFileKey, .isSymbolicLinkKey]
        guard let enumerator = FileManager.default.enumerator(
            at: root,
            includingPropertiesForKeys: Array(keys),
            options: [.skipsHiddenFiles, .skipsPackageDescendants]
        ) else {
            throw RoadmapPackageError.invalidSelection
        }
        let prefix = root.standardizedFileURL.path.hasSuffix("/")
            ? root.standardizedFileURL.path
            : root.standardizedFileURL.path + "/"
        var entries: [RoadmapFolderEntry] = []
        for case let url as URL in enumerator {
            try Task.checkCancellation()
            let values = try url.resourceValues(forKeys: keys)
            if values.isDirectory == true { continue }
            guard values.isSymbolicLink != true, values.isRegularFile == true else {
                throw RoadmapPackageError.invalidSelection
            }
            guard entries.count < limits.maximumFolderEntries else {
                throw RoadmapPackageError.tooManyFiles
            }
            let normalizedURL = url.standardizedFileURL
            guard normalizedURL.path.hasPrefix(prefix) else {
                throw RoadmapPackageError.invalidRelativePath
            }
            let relativePath = String(normalizedURL.path.dropFirst(prefix.count))
            let file = try RoadmapLocalFile(url: normalizedURL, maximumBytes: limits.maximumFileBytes)
            entries.append(try RoadmapFolderEntry(relativePath: relativePath, file: file))
        }
        return entries
    }
}
