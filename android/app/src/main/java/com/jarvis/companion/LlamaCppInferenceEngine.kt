package com.jarvis.companion

/**
 * llama.cpp JNI backend (RFC-0108). Weights live in app-private storage; native runtime ships in APK.
 */
class LlamaCppInferenceEngine : LocalInferenceEngine {
    override val runtimeName: String = "llama.cpp"

    override fun isRuntimeAvailable(): Boolean = CompanionNativeBridge.isLoaded()

    override fun load(modelPath: String, contextTokens: Int): String? {
        if (!isRuntimeAvailable()) {
            return "On-device inference runtime is missing from this build"
        }
        return CompanionNativeBridge.nativeLoad(modelPath, contextTokens).ifBlank { null }
    }

    override fun tokenize(text: String): Int {
        if (!isRuntimeAvailable()) return (text.length + 3) / 4
        val n = CompanionNativeBridge.nativeTokenize(text)
        return if (n > 0) n else (text.length + 3) / 4
    }

    override fun generate(prompt: String, maxTokens: Int, onToken: (String) -> Unit): GenerateOutcome {
        if (!isRuntimeAvailable()) {
            return GenerateOutcome(error = "On-device inference runtime is missing from this build")
        }
        val output = CompanionNativeBridge.nativeGenerate(prompt, maxTokens, OfflinePromptPlanner.N_BATCH)
        if (output.startsWith("error:cancelled") || output == "cancelled") {
            return GenerateOutcome(cancelled = true)
        }
        if (output.startsWith("error:")) {
            return GenerateOutcome(error = output.removePrefix("error:"))
        }
        val truncated = output.startsWith("truncated:")
        val text = if (truncated) output.removePrefix("truncated:") else output
        if (text.isNotEmpty()) onToken(text)
        return GenerateOutcome(truncated = truncated)
    }

    override fun unload() {
        if (isRuntimeAvailable()) CompanionNativeBridge.nativeUnload()
    }

    override fun requestCancel() {
        if (isRuntimeAvailable()) CompanionNativeBridge.nativeGenerateCancel()
    }
}

object CompanionNativeBridge {
    private var loaded = false

    init {
        loaded = runCatching {
            System.loadLibrary("jarvis_llama")
            true
        }.getOrDefault(false)
    }

    fun isLoaded(): Boolean = loaded

    external fun nativeLoad(modelPath: String, contextTokens: Int): String
    external fun nativeTokenize(text: String): Int
    external fun nativeGenerate(prompt: String, maxTokens: Int, batchSize: Int): String
    external fun nativeGenerateCancel()
    external fun nativeUnload()
}
