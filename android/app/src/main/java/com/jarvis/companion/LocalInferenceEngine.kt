package com.jarvis.companion

interface LocalInferenceEngine {
    val runtimeName: String
    fun isRuntimeAvailable(): Boolean
    fun load(modelPath: String, contextTokens: Int): String?
    /** [maxTokens] is 512 when the guard is clear, 256 under thermal/battery pressure. */
    fun generate(prompt: String, maxTokens: Int, onToken: (String) -> Unit): String?
    fun unload()
}
