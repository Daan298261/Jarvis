package com.jarvis.companion.device

import java.io.File

/**
 * JNI bridge to the on-device GGUF runtime (llama.cpp-class backend).
 * When the native library is absent, [generate] fails with an actionable error — no canned text.
 */
object DeviceModelInference {
    private var nativeLoaded = false
    private var modelLoaded = false

    init {
        nativeLoaded = runCatching {
            System.loadLibrary("jarvis_llama")
            true
        }.getOrDefault(false)
    }

    val isNativeAvailable: Boolean get() = nativeLoaded

    fun unload() {
        if (nativeLoaded && modelLoaded) {
            runCatching { nativeUnload() }
        }
        modelLoaded = false
    }

    fun load(packFile: File): Result<Unit> {
        if (!nativeLoaded) {
            return Result.failure(
                IllegalStateException(
                    "On-device inference runtime is not bundled in this build. Install a debug build with jarvis_llama native libs.",
                ),
            )
        }
        if (!packFile.isFile) {
            return Result.failure(IllegalStateException("Model pack file is missing."))
        }
        val code = nativeLoad(packFile.absolutePath)
        if (code != 0) {
            return Result.failure(IllegalStateException(nativeLastError().ifBlank { "Failed to load model (code $code)" }))
        }
        modelLoaded = true
        return Result.success(Unit)
    }

    suspend fun generate(prompt: String, onToken: (String) -> Unit): Result<Unit> {
        if (!nativeLoaded) {
            return Result.failure(
                IllegalStateException("On-device inference is unavailable until the native runtime is installed."),
            )
        }
        if (!modelLoaded) {
            return Result.failure(IllegalStateException("Load the model pack before generating."))
        }
        val code = nativeGenerate(prompt) { token -> onToken(token) }
        if (code != 0) {
            return Result.failure(IllegalStateException(nativeLastError().ifBlank { "Generation failed (code $code)" }))
        }
        return Result.success(Unit)
    }

    private external fun nativeLoad(path: String): Int
    private external fun nativeUnload()
    private external fun nativeGenerate(prompt: String, tokenHandler: (String) -> Unit): Int
    private external fun nativeLastError(): String
}
