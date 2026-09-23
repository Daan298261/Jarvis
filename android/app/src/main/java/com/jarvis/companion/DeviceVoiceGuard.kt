package com.jarvis.companion

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Build
import android.os.PowerManager

/** Thermal/battery/RAM gates before loading on-device STT/TTS packs (RFC-0140). */
object DeviceVoiceGuard {
    fun blockReason(context: Context, pack: CompanionVoicePack): String? {
        val activity = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        val memory = ActivityManager.MemoryInfo()
        activity.getMemoryInfo(memory)
        val availMb = memory.availMem / (1024 * 1024)
        if (availMb < pack.minRamMb) {
            return "Need about ${pack.minRamMb} MiB free RAM for ${pack.label} (have ~$availMb MiB)."
        }
        val battery = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val level = battery?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = battery?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
        val percent = if (level >= 0 && scale > 0) level * 100 / scale else 100
        val charging = battery?.getIntExtra(BatteryManager.EXTRA_STATUS, -1)?.let {
            it == BatteryManager.BATTERY_STATUS_CHARGING || it == BatteryManager.BATTERY_STATUS_FULL
        } ?: false
        if (!charging && percent < 12) {
            return "Battery is low ($percent%). Plug in before a long on-device voice session."
        }
        val power = context.getSystemService(Context.POWER_SERVICE) as PowerManager
        if (power.isPowerSaveMode) {
            return "Power saver is on. Disable power saver to run on-device voice."
        }
        val thermalBlocked = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            when (power.currentThermalStatus) {
                PowerManager.THERMAL_STATUS_SEVERE,
                PowerManager.THERMAL_STATUS_CRITICAL,
                PowerManager.THERMAL_STATUS_EMERGENCY,
                PowerManager.THERMAL_STATUS_SHUTDOWN,
                -> true
                else -> false
            }
        } else {
            false
        }
        if (thermalBlocked) {
            return "Phone is thermally throttled — pause on-device voice until it cools."
        }
        return null
    }
}
