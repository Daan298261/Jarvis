package com.jarvis.companion

import android.app.AlarmManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.app.Notification
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale
import java.util.UUID

/**
 * Black Grid local actions: notes, phone reminders, picked-text cap, honest queue/refuse.
 */
object StandaloneActions {
    const val ORIGIN_USER = "device_offline"
    const val ORIGIN_ASSISTANT = "device_local_draft"
    const val PICKED_TEXT_MAX_BYTES = 64 * 1024
    const val CHANNEL_ID = "anzu_phone_reminders"
    const val PREFS = "standalone_actions"
    const val KEY_REMINDERS = "reminders_json"
    const val EXTRA_REMINDER_ID = "com.jarvis.companion.REMINDER_ID"

    fun queueOrRefuseCopy(): String = "I'll do that when the ANZU desktop is back."

    fun mediaSavedCopy(): String =
        "Saved on this phone. It will be analyzed when the ANZU desktop is back."

    fun claimsAlreadyAnalyzed(text: String): Boolean {
        val lower = text.lowercase(Locale.US)
        return lower.contains("was analyzed") ||
            lower.contains("i've analyzed") ||
            lower.contains("i have analyzed") ||
            lower.contains("analyzed the image") ||
            lower.contains("analyzed the photo") ||
            lower.contains("analyzed the video")
    }

    fun reminderNeedsTimeCopy(): String =
        "When should I remind you? Say a time on this phone, for example 7:30 pm."

    fun reminderPermissionDeniedCopy(): String =
        "Notification permission is off, so I cannot show the reminder on this phone."

    fun reminderOnThisPhoneCopy(at: ZonedDateTime, inexact: Boolean): String {
        val whenText = at.format(DateTimeFormatter.ofPattern("h:mm a", Locale.getDefault()))
        return if (inexact) {
            "Reminder set on this phone around $whenText. The time may move slightly because exact alarms are not allowed."
        } else {
            "Reminder set on this phone for $whenText."
        }
    }

    fun noteAckCopy(): String = "Saved as a note on this phone. I will sync it when the ANZU desktop is back."

    fun pickedTextTooLargeCopy(): String =
        "That text file is larger than 64 KiB. Pick a smaller file or trim it, then try again."

    fun nonTextFileCopy(): String =
        "I can only read plain text or markdown on this phone. Other files wait for the ANZU desktop."

    fun parseReminderInstant(text: String, now: ZonedDateTime): ZonedDateTime? {
        val lower = text.lowercase(Locale.US)
        Regex("""\bin\s+(\d+)\s+(minutes?|mins?|hours?|hrs?)\b""").find(lower)?.let { match ->
            val amount = match.groupValues[1].toLong()
            val unit = match.groupValues[2]
            return if (unit.startsWith("hour") || unit.startsWith("hr")) {
                now.plusHours(amount)
            } else {
                now.plusMinutes(amount)
            }
        }
        val tomorrow = lower.contains("tomorrow")
        Regex("""\bat\s+noon\b""").find(lower)?.let {
            var at = now.withHour(12).withMinute(0).withSecond(0).withNano(0)
            if (tomorrow || !at.isAfter(now)) at = at.plusDays(1)
            return at
        }
        Regex("""\bat\s+midnight\b""").find(lower)?.let {
            var at = now.withHour(0).withMinute(0).withSecond(0).withNano(0).plusDays(1)
            if (tomorrow) at = now.plusDays(1).withHour(0).withMinute(0).withSecond(0).withNano(0)
            return at
        }
        Regex("""\bat\s+(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?""").find(lower)?.let { match ->
            var hour = match.groupValues[1].toInt()
            val minute = match.groupValues[2].ifBlank { "0" }.toInt()
            val ampm = match.groupValues[3]
            if (hour > 23 || minute > 59) return@let
            if (ampm.startsWith("p") && hour < 12) hour += 12
            if (ampm.startsWith("a") && hour == 12) hour = 0
            if (ampm.isBlank() && hour < 7 && hour != 0) hour += 12
            var at = now.withHour(hour).withMinute(minute).withSecond(0).withNano(0)
            if (tomorrow || !at.isAfter(now)) at = at.plusDays(1)
            return at
        }
        return null
    }

    data class ReminderScheduleResult(
        val id: String,
        val at: ZonedDateTime,
        val inexact: Boolean,
        val message: String,
    )

    fun ensureChannel(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val existing = manager.getNotificationChannel(CHANNEL_ID)
        if (existing != null) return
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_ID, "ANZU phone reminders", NotificationManager.IMPORTANCE_HIGH).apply {
                description = "Reminders scheduled on this phone while the ANZU desktop is unreachable"
            },
        )
    }

    fun canPostNotifications(context: Context): Boolean {
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        return manager.areNotificationsEnabled()
    }

    fun scheduleReminder(context: Context, ownerText: String, at: ZonedDateTime): Result<ReminderScheduleResult> {
        if (!canPostNotifications(context)) {
            return Result.failure(IllegalStateException(reminderPermissionDeniedCopy()))
        }
        ensureChannel(context)
        val id = UUID.randomUUID().toString()
        val triggerAt = at.toInstant().toEpochMilli()
        val alarm = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        // Manifest is owned by a parallel UX PR, so the alarm must wake the existing
        // launcher activity. CompanionModel delivers due reminders on start/refresh.
        val pending = PendingIntent.getActivity(
            context,
            id.hashCode(),
            activityWakeIntent(context, id),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val inexact = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            !alarm.canScheduleExactAlarms()
        } else {
            false
        }
        try {
            if (!inexact && Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                alarm.setAlarmClock(AlarmManager.AlarmClockInfo(triggerAt, pending), pending)
            } else if (!inexact) {
                alarm.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAt, pending)
            } else {
                alarm.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAt, pending)
            }
        } catch (_: SecurityException) {
            alarm.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAt, pending)
            persistReminder(context, id, ownerText, triggerAt)
            return Result.success(
                ReminderScheduleResult(id, at, true, reminderOnThisPhoneCopy(at, true)),
            )
        }
        persistReminder(context, id, ownerText, triggerAt)
        return Result.success(
            ReminderScheduleResult(id, at, inexact, reminderOnThisPhoneCopy(at, inexact)),
        )
    }

    fun deliverDueReminders(context: Context, nowMillis: Long = System.currentTimeMillis()) {
        val items = loadReminders(context)
        if (items.length() == 0) return
        ensureChannel(context)
        val kept = JSONArray()
        for (index in 0 until items.length()) {
            val item = items.optJSONObject(index) ?: continue
            val whenMs = item.optLong("at", 0L)
            if (whenMs in 1 until nowMillis + 1_000L && !item.optBoolean("fired", false)) {
                postReminderNotification(context, item.optString("id"), item.optString("text"))
                item.put("fired", true)
            }
            if (!item.optBoolean("fired", false) || whenMs >= nowMillis - 60_000L) {
                kept.put(item)
            }
        }
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_REMINDERS, kept.toString())
            .apply()
    }

    fun postReminderNotification(context: Context, id: String, text: String) {
        ensureChannel(context)
        val body = text.ifBlank { "Reminder on this phone" }
        val notification = Notification.Builder(context, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
            .setContentTitle("ANZU reminder")
            .setContentText(body)
            .setStyle(Notification.BigTextStyle().bigText(body))
            .setAutoCancel(true)
            .setContentIntent(
                PendingIntent.getActivity(
                    context,
                    id.hashCode(),
                    activityWakeIntent(context, id),
                    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
                ),
            )
            .build()
        val numericId = id.hashCode()
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.notify(numericId, notification)
    }

    fun readPickedText(context: Context, uri: Uri, mimeType: String?, displayName: String): Result<String> {
        val type = (mimeType ?: "").lowercase(Locale.US)
        val name = displayName.lowercase(Locale.US)
        val isText = type == "text/plain" || type == "text/markdown" || type == "text/x-markdown" ||
            name.endsWith(".txt") || name.endsWith(".md") || name.endsWith(".markdown")
        if (!isText) return Result.failure(IllegalArgumentException(nonTextFileCopy()))
        val bytes = context.contentResolver.openInputStream(uri)?.use { it.readBytes() }
            ?: return Result.failure(IllegalStateException("Cannot read that file on this phone."))
        if (bytes.size > PICKED_TEXT_MAX_BYTES) {
            return Result.failure(IllegalArgumentException(pickedTextTooLargeCopy()))
        }
        return Result.success(bytes.toString(Charsets.UTF_8))
    }

    fun storeQueuedMedia(context: Context, bytes: ByteArray, filename: String): File {
        val dir = File(context.filesDir, "offline-media").apply { mkdirs() }
        val target = File(dir, filename.ifBlank { "capture-${System.currentTimeMillis()}" })
        target.writeBytes(bytes)
        return target
    }

    fun isImageOrVideo(mimeType: String?, displayName: String): Boolean {
        val type = (mimeType ?: "").lowercase(Locale.US)
        val name = displayName.lowercase(Locale.US)
        return type.startsWith("image/") || type.startsWith("video/") ||
            name.endsWith(".jpg") || name.endsWith(".jpeg") || name.endsWith(".png") ||
            name.endsWith(".webp") || name.endsWith(".mp4") || name.endsWith(".mov") ||
            name.endsWith(".mkv") || name.endsWith(".webm")
    }

    fun isPlainText(mimeType: String?, displayName: String): Boolean {
        val type = (mimeType ?: "").lowercase(Locale.US)
        val name = displayName.lowercase(Locale.US)
        return type == "text/plain" || type == "text/markdown" || type == "text/x-markdown" ||
            name.endsWith(".txt") || name.endsWith(".md") || name.endsWith(".markdown")
    }

    fun userTurnJson(id: String, text: String, consequential: Boolean, autoReplay: Boolean): JSONObject =
        JSONObject()
            .put("request_id", id)
            .put("client_message_id", id)
            .put("role", "user")
            .put("text", text)
            .put("origin", ORIGIN_USER)
            .put("consequential", consequential)
            .put("auto_replay", autoReplay)

    fun assistantTurnJson(id: String, text: String, consequential: Boolean, autoReplay: Boolean): JSONObject =
        JSONObject()
            .put("request_id", id)
            .put("client_message_id", id)
            .put("role", "assistant")
            .put("text", text)
            .put("origin", ORIGIN_ASSISTANT)
            .put("consequential", consequential)
            .put("auto_replay", autoReplay)

    fun chatMessage(id: String, role: String, text: String, origin: String): JSONObject =
        JSONObject()
            .put("id", id)
            .put("role", role)
            .put("text", text)
            .put("origin", origin)

    fun openDocumentIntent(): Intent =
        Intent(Intent.ACTION_OPEN_DOCUMENT)
            .addCategory(Intent.CATEGORY_OPENABLE)
            .setType("*/*")
            .putExtra(Intent.EXTRA_MIME_TYPES, arrayOf("text/plain", "text/markdown"))

    private fun activityWakeIntent(context: Context, id: String): Intent {
        val launch = context.packageManager.getLaunchIntentForPackage(context.packageName)
            ?: Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        return launch
            .putExtra(EXTRA_REMINDER_ID, id)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
    }

    private fun persistReminder(context: Context, id: String, text: String, atMillis: Long) {
        val items = loadReminders(context)
        items.put(
            JSONObject()
                .put("id", id)
                .put("text", text)
                .put("at", atMillis)
                .put("fired", false),
        )
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_REMINDERS, items.toString())
            .apply()
    }

    private fun loadReminders(context: Context): JSONArray {
        val raw = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY_REMINDERS, "[]") ?: "[]"
        return runCatching { JSONArray(raw) }.getOrElse { JSONArray() }
    }
}

