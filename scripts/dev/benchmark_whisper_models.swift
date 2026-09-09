// Benchmark runner: transcribes every canonical benchmark passage with one
// pinned whisper.cpp model, using the production Speech sources unmodified.
//
// Usage: benchmark_whisper_models <models-dir> <model-filename> <canonical-audio-dir> <output-dir>
//
// SpeechModelCatalog.transcriptionModelFilename is fixed to the shipped
// base.en filename (see WhisperTranscriber.swift), so the model under test
// is exposed to it through a private, single-model directory: a symlink
// named with that fixed filename, pointing at whichever model this run was
// asked to test. That is the only way to select a model without changing
// production code, per the plan's Global Constraints.
//
// For each canonical WAV this writes <output-dir>/<passage>.json with
// transcript, audio_seconds, transcription_seconds, peak_resident_bytes,
// model_filename, and model_sha256 - never a path, and never more than one
// passage's own transcript.
import CryptoKit
import Darwin
import Foundation

struct PassageResult: Encodable {
    let transcript: String
    let audio_seconds: Double
    let transcription_seconds: Double
    let peak_resident_bytes: UInt64
    let model_filename: String
    let model_sha256: String
}

struct RunnerError: Error, CustomStringConvertible {
    let description: String
}

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data("benchmark_whisper_models: \(message)\n".utf8))
    exit(1)
}

// MARK: - Peak resident memory (mach_task_basic_info.resident_size_max)

func peakResidentBytes() -> UInt64 {
    var info = mach_task_basic_info()
    var count = mach_msg_type_number_t(MemoryLayout<mach_task_basic_info>.size / MemoryLayout<natural_t>.size)
    let result = withUnsafeMutablePointer(to: &info) { pointer -> kern_return_t in
        pointer.withMemoryRebound(to: integer_t.self, capacity: Int(count)) { reboundPointer in
            task_info(mach_task_self_, task_flavor_t(MACH_TASK_BASIC_INFO), reboundPointer, &count)
        }
    }
    guard result == KERN_SUCCESS else { return 0 }
    return info.resident_size_max
}

func sha256Hex(ofFileAt url: URL) throws -> String {
    let data = try Data(contentsOf: url)
    return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
}

// MARK: - Canonical WAV reading

// Reads a WAVE file written by `afconvert -f WAVE -d LEI16@48000 -c 1`
// (prepare_benchmark_audio.sh). afconvert writes an "optimized" WAVE with a
// "FLLR" filler chunk that pads the "data" chunk to a page-aligned offset
// (observed at byte 4096, not 44), so this walks RIFF chunks to find "data"
// rather than assuming a fixed header size.
func readCanonicalWAVSamples(_ url: URL) throws -> [Int16] {
    let data = try Data(contentsOf: url)

    func byte(_ offset: Int) -> UInt8 { data[data.startIndex + offset] }

    func fourCC(_ offset: Int) -> String {
        String(decoding: (0..<4).map { byte(offset + $0) }, as: UTF8.self)
    }

    func littleEndianUInt32(_ offset: Int) -> UInt32 {
        (0..<4).reduce(UInt32(0)) { accumulator, index in
            accumulator | (UInt32(byte(offset + index)) << (8 * index))
        }
    }

    guard data.count >= 12, fourCC(0) == "RIFF", fourCC(8) == "WAVE" else {
        throw RunnerError(description: "\(url.path) is not a RIFF/WAVE file")
    }

    var offset = 12
    var payloadRange: Range<Int>?
    while offset + 8 <= data.count {
        let chunkID = fourCC(offset)
        let chunkSize = Int(littleEndianUInt32(offset + 4))
        let chunkStart = offset + 8
        guard chunkSize >= 0, chunkStart + chunkSize <= data.count else {
            throw RunnerError(description: "\(url.path) has a truncated '\(chunkID)' chunk")
        }
        if chunkID == "data" {
            payloadRange = chunkStart..<(chunkStart + chunkSize)
            break
        }
        // RIFF chunks are word-aligned: an odd-sized chunk has one pad byte after it.
        offset = chunkStart + chunkSize + (chunkSize % 2)
    }
    guard let payloadRange else {
        throw RunnerError(description: "\(url.path) has no 'data' chunk")
    }

    let payload = data.subdata(in: payloadRange)
    guard payload.count % 2 == 0 else {
        throw RunnerError(description: "\(url.path) has a trailing partial sample")
    }
    var samples = [Int16](repeating: 0, count: payload.count / 2)
    samples.withUnsafeMutableBytes { destination in
        _ = payload.copyBytes(to: destination)
    }
    return samples.map { Int16(littleEndian: $0) }
}

// MARK: - Feeding audio through the production ASR derivation path

func makeChunk(
    samples: ArraySlice<Int16>, sampleStart: Int64, source: RecordingSourceLineage
) -> RecordingPCMChunk {
    var payload = Data(capacity: samples.count * 2)
    for sample in samples { withUnsafeBytes(of: sample.littleEndian) { payload.append(contentsOf: $0) } }
    return RecordingPCMChunk(
        track: .microphone,
        presentationNanoseconds: 0,
        sampleStart: sampleStart,
        sampleCount: samples.count,
        format: try! RecordingPCMFormat(track: .microphone, channelCount: 1),
        source: source,
        payload: payload
    )
}

// Feeds 48 kHz mono samples through ASRAudioDeriver in one-second chunks,
// exactly as a live recording delivers audio, and returns the 16 kHz
// stream WhisperTranscriber requires plus its derivation lineage.
func derive(samples: [Int16], recordingID: UUID) throws -> (samples: [Int16], lineage: ASRDerivationLineage) {
    let deriver = ASRAudioDeriver(recordingID: recordingID, track: .microphone)
    let source = RecordingSourceLineage(
        sampleRate: Double(ASRAudioDeriver.sourceSampleRate), channelCount: 1, deviceID: "benchmark",
        initialRoute: "benchmark", conversionVersion: 1, presentationNanoseconds: 0
    )
    let chunkSize = ASRAudioDeriver.sourceSampleRate
    var derived: [Int16] = []
    var offset = 0
    var sampleStart: Int64 = 0
    while offset < samples.count {
        let end = min(offset + chunkSize, samples.count)
        let chunk = makeChunk(samples: samples[offset..<end], sampleStart: sampleStart, source: source)
        if let block = try deriver.append(chunk) { derived += block.samples }
        sampleStart += Int64(end - offset)
        offset = end
    }
    let (last, lineage) = deriver.finish()
    if let last { derived += last.samples }
    return (derived, lineage)
}

@main
struct BenchmarkWhisperModels {
    static func main() async throws {
        let arguments = CommandLine.arguments
        guard arguments.count == 5 else {
            fail("usage: benchmark_whisper_models <models-dir> <model-filename> <canonical-audio-dir> <output-dir>")
        }
        let modelsDir = URL(fileURLWithPath: arguments[1], isDirectory: true).standardizedFileURL
        let modelFilename = arguments[2]
        let canonicalAudioDir = URL(fileURLWithPath: arguments[3], isDirectory: true).standardizedFileURL
        let outputDir = URL(fileURLWithPath: arguments[4], isDirectory: true).standardizedFileURL

        let sourceModelURL = modelsDir.appendingPathComponent(modelFilename, isDirectory: false)
        guard FileManager.default.fileExists(atPath: sourceModelURL.path) else {
            fail("model not found at \(sourceModelURL.path)")
        }

        let wavURLs = try FileManager.default
            .contentsOfDirectory(at: canonicalAudioDir, includingPropertiesForKeys: nil)
            .filter { $0.pathExtension.lowercased() == "wav" }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
        guard !wavURLs.isEmpty else {
            fail("no .wav files found in \(canonicalAudioDir.path)")
        }

        try FileManager.default.createDirectory(at: outputDir, withIntermediateDirectories: true)

        // SpeechModelCatalog always resolves the fixed transcriptionModelFilename,
        // so expose the model under test through a private directory that
        // contains only it, under that fixed name.
        let catalogDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("benchmark-catalog-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: catalogDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: catalogDir) }
        let linkedModelURL = catalogDir.appendingPathComponent(
            SpeechModelCatalog.transcriptionModelFilename, isDirectory: false
        )
        try FileManager.default.createSymbolicLink(at: linkedModelURL, withDestinationURL: sourceModelURL)

        let modelSHA256 = try sha256Hex(ofFileAt: sourceModelURL)
        let catalog = SpeechModelCatalog(directory: catalogDir)
        let transcriber = try WhisperTranscriber(catalog: catalog)

        for wavURL in wavURLs {
            let rawSamples = try readCanonicalWAVSamples(wavURL)
            let (samples, lineage) = try derive(samples: rawSamples, recordingID: UUID())
            let request = SpeechTranscriptionRequest(samples: samples, lineage: lineage)

            let start = Date()
            let result = try await transcriber.transcribe(request)
            let elapsed = Date().timeIntervalSince(start)
            let peak = peakResidentBytes()
            // Release between files so the next file's context is freshly
            // loaded rather than accumulating alongside this one.
            await transcriber.release()

            let audioSeconds = Double(lineage.sourceSampleCount) / Double(lineage.sourceSampleRate)
            let passageResult = PassageResult(
                transcript: result.text,
                audio_seconds: audioSeconds,
                transcription_seconds: elapsed,
                peak_resident_bytes: peak,
                model_filename: modelFilename,
                model_sha256: modelSHA256
            )

            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            let json = try encoder.encode(passageResult)
            let stem = wavURL.deletingPathExtension().lastPathComponent
            try json.write(to: outputDir.appendingPathComponent("\(stem).json", isDirectory: false))

            print("\(modelFilename) \(stem): \(result.segments.count) segment(s) in \(String(format: "%.1f", elapsed))s")
        }
    }
}
