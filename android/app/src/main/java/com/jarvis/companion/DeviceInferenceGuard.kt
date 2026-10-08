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
    const val BUDGET_CLEAR = 512
    const val BUDGET_PRESSURE = 256

    fun generationBudget(
        batteryPercent: Int,
        charging: Boolean,
        thermalPressure: Boolean,
        powerSave: Boolean,
    ): Int {
        val pressure = thermalPressure || powerSave || (!charging && batteryPercent < 30)
        return if (pressure) BUDGET_PRESSURE else BUDGET_CLEAR
    }

    fun generationBudget(context: Context): Int {
        val snapshot = pressureSnapshot(context)
        return generationBudget(
            batteryPercent = snapshot.batteryPercent,
            charging = snapshot.charging,
            thermalPressure = snapshot.thermalPressure,
            powerSave = snapshot.powerSave,
        )
    }

    fun pressureReason(context: Context): String? {
        val snapshot = pressureSnapshot(context)
        return when {
            snapshot.thermalPressure -> "Phone is warm — shorter answers on this phone."
            snapshot.powerSave -> "Power saver is on — shorter answers on this phone."
            !snapshot.charging && snapshot.batteryPercent < 30 ->
                "Battery is at ${snapshot.batteryPercent}% — shorter answers on this phone."
            else -> null
        }
    }

    data class PressureSnapshot(
        val batteryPercent: Int,
        val charging: Boolean,
        val thermalPressure: Boolean,
        val powerSave: Boolean,
    )

    fun pressureSnapshot(context: Context): PressureSnapshot {
        val battery = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val level = battery?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = battery?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
        val percent = if (level >= 0 && scale > 0) level * 100 / scale else 100
        val charging = battery?.getIntExtra(BatteryManager.EXTRA_STATUS, -1)?.let {
            it == BatteryManager.BATTERY_STATUS_CHARGING || it == BatteryManager.BATTERY_STATUS_FULL
        } ?: false
        val power = context.getSystemService(Context.POWER_SERVICE) as PowerManager
        val thermalPressure = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            when (power.currentThermalStatus) {
                PowerManager.THERMAL_STATUS_MODERATE,
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
        return PressureSnapshot(percent, charging, thermalPressure, power.isPowerSaveMode)
    }

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
