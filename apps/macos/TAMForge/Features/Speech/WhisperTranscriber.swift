import Foundation
import whisper

// The only file in this target that may `import whisper`. Everything else
// (SpeechTranscribing, SpeechTranscriptionRequest/.validate(), the fake
// engine in tests) stays free of the vendored XCFramework, per
// SpeechTranscription.swift's header comment.
//
// C-string lifetime: whisper_full_params.language and .vad_model_path are
// UnsafePointer<CChar>!. Both are bound with nested withCString(_:) scopes
// in runWhisperFull(context:baseParams:vadModelPath:samples:) below, and the
// call to whisper_full itself happens INSIDE those nested closures — never
// after they return. withCString guarantees its pointer stays valid only
// for the dynamic extent of its closure, so as long as the C call that
// consumes the pointer is made synchronously inside that closure (and the
// pointer is never copied out to somewhere longer-lived), there is no
// window where whisper_full could observe a freed buffer. No `strdup`,
// no manually managed buffer, and no pointer survives past the closure
// that produced it.
actor WhisperTranscriber: SpeechTranscribing {
    private let catalog: SpeechModelCatalog
    private let runtimeVersion: String
    private let modelPath: String
    // OpaquePointer isn't Sendable, so strict concurrency won't let deinit
    // (nonisolated by construction) touch a plain actor-isolated stored
    // property of this type. Every mutation still only ever happens inside
    // isolated actor methods (ensureContext/release); deinit's read is safe
    // because it only runs once nothing else can be running against this
    // instance. nonisolated(unsafe) documents and accepts exactly that.
    private nonisolated(unsafe) var context: OpaquePointer?
    private var metalRequested = false

    init(catalog: SpeechModelCatalog = .init(), runtimeVersion: String = "b4938") throws {
        self.catalog = catalog
        self.runtimeVersion = runtimeVersion
        // Resolve now so construction fails fast when the model was never
        // fetched; the context itself is created lazily on first use.
        modelPath = try catalog.requireTranscriptionModel().path
    }

    deinit {
        // Actor deinit has direct, non-isolated access to stored state (no
        // other task can still be running against this instance), so this
        // is the safe place to free a context the caller never released.
        if let context {
            whisper_free(context)
        }
    }

    /// Frees the loaded model context early. Safe to call more than once,
    /// and safe to skip: deinit frees it too if the caller never calls this.
    func release() {
        guard let context else { return }
        whisper_free(context)
        self.context = nil
    }

    func transcribe(_ request: SpeechTranscriptionRequest) async throws -> SpeechTranscriptionResult {
        try request.validate()
        guard !Task.isCancelled else { throw SpeechTranscriptionError.cancelled }

        let context = try ensureContext()
        let samples = request.samples.map { Float($0) / 32_768.0 }

        var params = whisper_full_default_params(WHISPER_SAMPLING_GREEDY)
        params.translate = false
        params.token_timestamps = true
        params.no_timestamps = false
        params.print_progress = false
        params.print_realtime = false
        params.single_segment = false
        params.n_threads = Int32(max(1, ProcessInfo.processInfo.activeProcessorCount - 2))
        // Returning true aborts whisper_full. Task.isCancelled reads the
        // current thread's task-local cancellation flag with no captures,
        // so this closure is a valid, context-free @convention(c) callback.
        params.abort_callback = { _ in Task.isCancelled }
        params.abort_callback_user_data = nil

        let resultCode = runWhisperFull(
            context: context,
            baseParams: params,
            vadModelPath: catalog.vadModelURL?.path,
            samples: samples
        )
        if resultCode != 0 {
            // whisper_full has no distinct "aborted" return code, so we
            // disambiguate by re-checking cancellation after the call.
            throw Task.isCancelled ? SpeechTranscriptionError.cancelled : SpeechTranscriptionError.runtimeFailure(code: resultCode)
        }

        return SpeechTranscriptionResult(
            segments: readSegments(context: context),
            identity: SpeechRuntimeIdentity(
                runtimeVersion: runtimeVersion,
                modelFilename: SpeechModelCatalog.transcriptionModelFilename,
                modelSHA256: SpeechModelCatalog.transcriptionModelSHA256,
                metalRequested: metalRequested,
                usedBuiltInVAD: catalog.vadModelURL != nil,
                language: "en"
            ),
            lineage: request.lineage
        )
    }

    // MARK: - Context lifecycle

    private func ensureContext() throws -> OpaquePointer {
        if let context { return context }
        var contextParams = whisper_context_default_params()
        // Metal is the whole point of this runtime; keep GPU inference on.
        contextParams.use_gpu = true
        guard let created = modelPath.withCString({ whisper_init_from_file_with_params($0, contextParams) }) else {
            throw SpeechTranscriptionError.runtimeFailure(code: -1)
        }
        // Store immediately: if anything below ever threw before this line
        // ran, the freshly created context would leak.
        context = created
        metalRequested = contextParams.use_gpu && Self.systemInfoReportsMetalSupport()
        return created
    }

    private static func systemInfoReportsMetalSupport() -> Bool {
        let info = String(cString: whisper_print_system_info())
        for field in info.split(separator: "|") {
            let trimmed = field.trimmingCharacters(in: .whitespaces)
            if trimmed.hasPrefix("MTL"), trimmed.hasSuffix("= 1") {
                return true
            }
        }
        return false
    }

    // MARK: - whisper_full invocation

    // Binds `language` (always) and `vad_model_path` (when VAD is enabled)
    // as nested withCString scopes around the single whisper_full call, so
    // both C strings are guaranteed alive for the call's entire duration.
    private nonisolated func runWhisperFull(
        context: OpaquePointer,
        baseParams: whisper_full_params,
        vadModelPath: String?,
        samples: [Float]
    ) -> Int32 {
        "en".withCString { languagePointer in
            var params = baseParams
            params.language = languagePointer
            if let vadModelPath {
                return vadModelPath.withCString { vadPointer in
                    params.vad = true
                    params.vad_model_path = vadPointer
                    return samples.withUnsafeBufferPointer { buffer in
                        whisper_full(context, params, buffer.baseAddress, Int32(buffer.count))
                    }
                }
            }
            return samples.withUnsafeBufferPointer { buffer in
                whisper_full(context, params, buffer.baseAddress, Int32(buffer.count))
            }
        }
    }

    // MARK: - Reading results

    private nonisolated func readSegments(context: OpaquePointer) -> [SpeechTranscribedSegment] {
        let eot = whisper_token_eot(context)
        let segmentCount = whisper_full_n_segments(context)
        var segments: [SpeechTranscribedSegment] = []
        segments.reserveCapacity(Int(segmentCount))
        for segmentIndex in 0..<segmentCount {
            let text = String(cString: whisper_full_get_segment_text(context, segmentIndex))
            let words = readWords(context: context, segmentIndex: segmentIndex, eot: eot)
            segments.append(
                SpeechTranscribedSegment(
                    text: text,
                    startMilliseconds: whisper_full_get_segment_t0(context, segmentIndex) * 10,
                    endMilliseconds: whisper_full_get_segment_t1(context, segmentIndex) * 10,
                    words: words
                )
            )
        }
        return segments
    }

    private nonisolated func readWords(
        context: OpaquePointer, segmentIndex: Int32, eot: whisper_token
    ) -> [SpeechTranscribedWord] {
        let tokenCount = whisper_full_n_tokens(context, segmentIndex)
        var words: [SpeechTranscribedWord] = []
        words.reserveCapacity(Int(tokenCount))
        for tokenIndex in 0..<tokenCount {
            let data = whisper_full_get_token_data(context, segmentIndex, tokenIndex)
            // Special tokens (EOT, SOT, language, timestamp, ...) all live
            // at ids >= eot in whisper's vocabulary; only real words remain.
            guard data.id < eot else { continue }
            let text = String(cString: whisper_full_get_token_text(context, segmentIndex, tokenIndex))
            words.append(
                SpeechTranscribedWord(
                    text: text,
                    startMilliseconds: data.t0 * 10,
                    endMilliseconds: data.t1 * 10,
                    probability: Double(data.p)
                )
            )
        }
        return words
    }
}
