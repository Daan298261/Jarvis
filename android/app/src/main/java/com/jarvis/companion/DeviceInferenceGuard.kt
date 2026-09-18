package com.jarvis.companion

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Build
import android.os.PowerManager

/** Thermal/battery/RAM gates before loading a phone-sized GGUF pack. */
object DeviceInferenceGuard {
    fun blockReason(context: Context, pack: CompanionPack): String? {
        val activity = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        val memory = ActivityManager.MemoryInfo()
        activity.getMemoryInfo(memory)
        val availMb = memory.availMem / (1024 * 1024)
        if (availMb < pack.minRamMb) {
            return "Need about ${pack.minRamMb} MiB free RAM (have ~$availMb MiB). Close other apps or pick a smaller pack."
        }
        val battery = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val level = battery?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = battery?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
        val percent = if (level >= 0 && scale > 0) level * 100 / scale else 100
        val charging = battery?.getIntExtra(BatteryManager.EXTRA_STATUS, -1)?.let {
            it == BatteryManager.BATTERY_STATUS_CHARGING || it == BatteryManager.BATTERY_STATUS_FULL
        } ?: false
        if (!charging && percent < 15) {
            return "Battery is low ($percent%). Plug in or wait before loading the on-device model."
        }
        val power = context.getSystemService(Context.POWER_SERVICE) as PowerManager
        if (power.isPowerSaveMode) {
            return "Power saver is on. Disable power saver to run the on-device model."
        }
        val deepIdle = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            power.isDeviceLightIdleMode || power.isDeviceIdleMode
        } else {
            power.isDeviceIdleMode
        }
        if (deepIdle) {
            return "Device is in deep idle. Wake the phone to load the on-device model."
        }
        return null
    }
}
