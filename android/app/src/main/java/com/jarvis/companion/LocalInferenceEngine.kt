package com.jarvis.companion

interface LocalInferenceEngine {
    val runtimeName: String
    fun isRuntimeAvailable(): Boolean
    fun load(modelPath: String, contextTokens: Int): String?
    /** Approximate or native token count for budget planning. */
    fun tokenize(text: String): Int = (text.length + 3) / 4
    /** [maxTokens] is 512 when the guard is clear, 256 under thermal/battery pressure. */
    fun generate(prompt: String, maxTokens: Int, onToken: (String) -> Unit): GenerateOutcome
    fun unload()
    fun requestCancel() {}
    /** Called before every generate pass so KV/state is fresh. Native llama.cpp clears inside nativeGenerate. */
    fun beginPass() {}
}
