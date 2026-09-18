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

    override fun generate(prompt: String, maxTokens: Int, onToken: (String) -> Unit): String? {
        if (!isRuntimeAvailable()) {
            return "On-device inference runtime is missing from this build"
        }
        val output = CompanionNativeBridge.nativeGenerate(prompt, maxTokens)
        if (output.startsWith("error:")) return output.removePrefix("error:")
        if (output.isNotEmpty()) onToken(output)
        return null
    }

    override fun unload() {
        if (isRuntimeAvailable()) CompanionNativeBridge.nativeUnload()
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
    external fun nativeGenerate(prompt: String, maxTokens: Int): String
    external fun nativeUnload()
}
