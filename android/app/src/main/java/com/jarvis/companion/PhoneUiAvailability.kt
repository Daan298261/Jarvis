package com.jarvis.companion

/** Only surfaces that have executable behavior belong in main navigation. */
object PhoneUiAvailability {
    fun tabs(connected: Boolean, hasCachedTasks: Boolean): List<String> = buildList {
        add("Home")
        add("Chat")
        if (connected || hasCachedTasks) add("Tasks")
        add("More")
    }

    fun desktopActionsEnabled(connected: Boolean, busy: Boolean) = connected && !busy
    fun manualPairingReady(endpoint: String, pin: String, code: String): Boolean =
        runCatching { TransportPolicy.origin(endpoint) }.isSuccess &&
            pin.trim().matches(Regex("[a-fA-F0-9]{64}")) && CompanionCodeValidator.isComplete(code)
}
