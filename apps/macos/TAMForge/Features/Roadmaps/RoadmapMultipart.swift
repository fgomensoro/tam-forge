import Foundation

struct RoadmapMultipartBody: Sendable {
    let fileURL: URL
    let contentType: String

    static func make(for package: RoadmapPackage) async throws -> Self {
        try await package.withSecurityScopedAccess {
            try Task.checkCancellation()
            return try Self.makeWithoutAccess(for: package)
        }
    }

    func remove() {
        try? FileManager.default.removeItem(at: fileURL)
    }

    static func makeWithoutAccess(for package: RoadmapPackage) throws -> Self {
        let boundary = "TAMForge-\(UUID().uuidString)"
        let fileURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("tamforge-roadmap-\(UUID().uuidString)")
        guard FileManager.default.createFile(atPath: fileURL.path, contents: nil) else {
            throw RoadmapPackageError.invalidSelection
        }
        do {
            let handle = try FileHandle(forWritingTo: fileURL)
            defer { try? handle.close() }
            try writeTextPart(name: "package_kind", value: package.kind, boundary: boundary, to: handle)
            switch package {
            case let .zip(file, _):
                try writeFilePart(name: "package", file: file, boundary: boundary, to: handle)
            case let .folder(folder):
                for entry in folder.entries {
                    try Task.checkCancellation()
                    try writeTextPart(name: "paths", value: entry.relativePath, boundary: boundary, to: handle)
                    try writeFilePart(name: "files", file: entry.file, boundary: boundary, to: handle)
                }
            }
            try handle.write(contentsOf: Data("--\(boundary)--\r\n".utf8))
            return Self(fileURL: fileURL, contentType: "multipart/form-data; boundary=\(boundary)")
        } catch {
            try? FileManager.default.removeItem(at: fileURL)
            throw error
        }
    }

    private static func writeTextPart(name: String, value: String, boundary: String, to handle: FileHandle) throws {
        try handle.write(contentsOf: Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n".utf8))
    }

    private static func writeFilePart(name: String, file: RoadmapLocalFile, boundary: String, to output: FileHandle) throws {
        try output.write(contentsOf: Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"; filename=\"roadmap-file\"\r\nContent-Type: application/octet-stream\r\n\r\n".utf8))
        let input = try FileHandle(forReadingFrom: file.url)
        defer { try? input.close() }
        var copied: Int64 = 0
        while let chunk = try input.read(upToCount: 64 * 1024), !chunk.isEmpty {
            try Task.checkCancellation()
            copied += Int64(chunk.count)
            guard copied <= file.byteCount else { throw RoadmapPackageError.sourceChanged }
            try output.write(contentsOf: chunk)
        }
        guard copied == file.byteCount else { throw RoadmapPackageError.sourceChanged }
        try output.write(contentsOf: Data("\r\n".utf8))
    }
}
