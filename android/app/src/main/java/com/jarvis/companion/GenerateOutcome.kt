package com.jarvis.companion

import kotlinx.coroutines.CancellationException

/** Result of one on-device GGUF generate call. [error] is null on success. */
data class GenerateOutcome(
    val error: String? = null,
    val truncated: Boolean = false,
    val cancelled: Boolean = false,
)

data class GenerateResult(
    val truncated: Boolean = false,
    val sectioned: Boolean = false,
    val clipped: Boolean = false,
)

internal suspend fun <T> withOfflineAnswerCleanup(
    packManager: CompanionPackManager,
    clearPicked: () -> Unit,
    onStart: () -> Unit,
    onFinally: () -> Unit,
    keepWarm: () -> Boolean = { false },
    block: suspend () -> T,
): Result<T> {
    onStart()
    var success = false
    return try {
        Result.success(block().also { success = true })
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        Result.failure(e)
    } finally {
        clearPicked()
        if (!success || !keepWarm()) packManager.unload()
        onFinally()
    }
}
