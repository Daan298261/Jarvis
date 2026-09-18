package com.jarvis.companion

interface LocalInferenceEngine {
    val runtimeName: String
    fun isRuntimeAvailable(): Boolean
    fun load(modelPath: String, contextTokens: Int): String?
    fun generate(prompt: String, maxTokens: Int, onToken: (String) -> Unit): String?
    fun unload()
}
