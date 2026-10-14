package com.jarvis.companion

/** Where ANZU's answers come from right now; drives the header indicator. */
enum class AnswerMode { DESKTOP, PHONE, PHONE_NO_MODEL, WAITING_APPROVAL }

data class ModeIndicator(val mode: AnswerMode, val label: String, val detail: String)

/** Features that only the ANZU desktop can run. Each gets an honest explanation while offline. */
enum class DesktopFeature { TASKS, STUDIO, SCHEDULES, WHATSAPP, NOTIFICATIONS, CALLS, DESKTOP_VOICES, ATTACHMENT_ANALYSIS }

object CompanionMode {
    fun answerMode(connected: Boolean, pendingApproval: Boolean, localModelReady: Boolean): AnswerMode = when {
        connected -> AnswerMode.DESKTOP
        pendingApproval && !localModelReady -> AnswerMode.WAITING_APPROVAL
        localModelReady -> AnswerMode.PHONE
        else -> AnswerMode.PHONE_NO_MODEL
    }

    fun indicator(connected: Boolean, pendingApproval: Boolean, localModelReady: Boolean, paired: Boolean): ModeIndicator =
        when (answerMode(connected, pendingApproval, localModelReady)) {
            AnswerMode.DESKTOP -> ModeIndicator(AnswerMode.DESKTOP, "● DESKTOP", "Answers come from your ANZU desktop.")
            AnswerMode.PHONE -> ModeIndicator(
                AnswerMode.PHONE,
                "◐ ON THIS PHONE",
                if (paired) "Desktop unreachable — ANZU answers on this phone and syncs when the desktop is back."
                else "ANZU answers on this phone. Nothing leaves the device.",
            )
            AnswerMode.WAITING_APPROVAL -> ModeIndicator(AnswerMode.WAITING_APPROVAL, "○ WAITING", "Approve this phone on your ANZU desktop.")
            AnswerMode.PHONE_NO_MODEL -> ModeIndicator(
                AnswerMode.PHONE_NO_MODEL,
                "○ OFFLINE",
                "Set up a model on this phone to chat without the desktop.",
            )
        }

    /** First-run / home setup card is shown until the phone can answer on its own or reaches a desktop. */
    fun needsPhoneSetup(connected: Boolean, localModelReady: Boolean): Boolean = !connected && !localModelReady

    fun desktopOnlyNotice(feature: DesktopFeature): String = when (feature) {
        DesktopFeature.TASKS -> "Tasks run on your ANZU desktop. They will show here again when the desktop is reachable. You can keep chatting on this phone."
        DesktopFeature.STUDIO -> "Black Grid Studio renders images, motion and voice on the desktop GPU, so it needs the ANZU desktop."
        DesktopFeature.SCHEDULES -> "Desktop schedules need the ANZU desktop. Offline, ask in Chat (\"remind me at 7:30 pm …\") for a reminder on this phone."
        DesktopFeature.WHATSAPP -> "WhatsApp messages go through the linked desktop session, so this needs the ANZU desktop."
        DesktopFeature.NOTIFICATIONS -> "Task notifications and calls are sent by the ANZU desktop. Reminders set on this phone still notify you."
        DesktopFeature.CALLS -> "Calls are placed by the ANZU desktop."
        DesktopFeature.DESKTOP_VOICES -> "Desktop voices play from the ANZU desktop. Offline, ANZU speaks with this phone's voice."
        DesktopFeature.ATTACHMENT_ANALYSIS -> "Photos, videos and documents are kept on this phone and analysed when the ANZU desktop is back. Text and markdown files can be read here."
    }
}
