package com.jarvis.companion

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * Fires Black Grid phone reminders from AlarmManager without starting an activity
 * (background activity starts are blocked on Android 10+).
 *
 * The reminder alarm is an explicit PendingIntent, so the exported filter is
 * BOOT_COMPLETED only.
 */
class ReminderReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val app = context.applicationContext
        when (intent.action) {
            Intent.ACTION_BOOT_COMPLETED -> {
                StandaloneActions.deliverDueReminders(app)
                StandaloneActions.rearmUnfiredReminders(app)
            }
            StandaloneActions.ACTION_REMINDER -> {
                val id = intent.getStringExtra(StandaloneActions.EXTRA_REMINDER_ID).orEmpty()
                StandaloneActions.fireReminder(app, id)
            }
        }
    }
}
