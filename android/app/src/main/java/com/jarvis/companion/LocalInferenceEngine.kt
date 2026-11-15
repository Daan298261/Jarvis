package com.jarvis.companion

interface LocalInferenceEngine {
    val runtimeName: String
    fun isRuntimeAvailable(): Boolean
    fun load(modelPath: String, contextTokens: Int): String?
    /** Approximate or native token count for budget planning. */
    fun tokenize(text: String): Int = (text.length + 3) / 4
    /** [maxTokens] is 512 when the guard is clear, 256 under thermal/battery pressure. */
    fun generate(prompt: String, maxTokens: Int, onToken: (String) -> Unit): GenerateOutcome
    /**
     * Opens one reply turn and returns its token. A [requestCancel] after this call makes every later
     * pass run with that token stop, including a pass that has not started yet, so a cancel landing
     * between two passes is never lost. Engines without such a token return 0 and rely on the pack
     * manager's own check before each pass.
     */
    fun beginTurn(): Long = 0L
    /** One pass of the turn [turn] (from [beginTurn]); an engine without turn tokens runs a plain [generate]. */
    fun generate(prompt: String, maxTokens: Int, turn: Long, onToken: (String) -> Unit): GenerateOutcome =
        generate(prompt, maxTokens, onToken)
    fun unload()
    fun requestCancel() {}
    /** Native code validates any reusable prefix before every pass. */
    fun beginPass() {}
}
