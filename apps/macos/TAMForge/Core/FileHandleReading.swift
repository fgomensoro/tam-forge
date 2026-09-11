import Darwin
import Foundation

// FileHandle.read(upToCount:) returns an autoreleased NSData, so every
// buffer it hands back stays resident until the enclosing autorelease pool
// drains: at the end of the current task job or test, not when the caller
// drops it. A loop that streams a whole file that way keeps the whole file
// in the physical footprint (measured on macOS 26.5 at 64 KiB and 1 MiB
// reads alike). A plain read(2) into a Data the caller owns does not, so
// every bulk reader in the app reads through this instead.
extension FileHandle {
    /// Reads up to `count` bytes; shorter only at end of file, empty at
    /// end of file.
    func readOwnedBytes(upTo count: Int) throws -> Data {
        guard count > 0 else { return Data() }
        var data = Data(count: count)
        var filled = 0
        while filled < count {
            let got = data.withUnsafeMutableBytes { buffer in
                Darwin.read(fileDescriptor, buffer.baseAddress! + filled, count - filled)
            }
            if got < 0 { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
            if got == 0 { break }
            filled += got
        }
        data.count = filled
        return data
    }
}
