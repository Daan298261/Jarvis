package com.jarvis.companion

import android.content.Context
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable

/** RFC-0108 §2.4 — one-shot post-pair offer to download the recommended offline pack. */
object PostPairPackOfferPrefs {
    private const val PREFS_NAME = "companion_ui"
    private const val KEY_OFFER_HANDLED_DEVICE = "post_pair_offline_pack_offer_handled_device"

    fun shouldOffer(context: Context, deviceId: String, packStatus: DevicePackStatus): Boolean {
        if (deviceId.isBlank()) return false
        if (packStatus == DevicePackStatus.READY ||
            packStatus == DevicePackStatus.RUNNING ||
            packStatus == DevicePackStatus.DOWNLOADING
        ) {
            return false
        }
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        return prefs.getString(KEY_OFFER_HANDLED_DEVICE, "") != deviceId
    }

    fun markHandled(context: Context, deviceId: String) {
        if (deviceId.isBlank()) return
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_OFFER_HANDLED_DEVICE, deviceId)
            .apply()
    }
}

data class RecommendedPackOffer(
    val id: String,
    val label: String,
    val sizeBytes: Long,
)

fun recommendedPackOffer(model: CompanionModel): RecommendedPackOffer? {
    val items = model.packManager.catalogJson()
    val chosen = items.firstOrNull { it.optBoolean("recommended") } ?: items.firstOrNull() ?: return null
    val id = chosen.optString("id")
    if (id.isBlank()) return null
    val label = chosen.optString("label").ifBlank { id }
    val sizeBytes = chosen.optLong("size_bytes")
    return RecommendedPackOffer(id = id, label = label, sizeBytes = sizeBytes)
}

/** Catalog `size_bytes` displayed as MB per RFC-0108 (`size_bytes / 1_000_000`, rounded). */
fun formatPackCatalogSizeMb(sizeBytes: Long): String? {
    if (sizeBytes <= 0L) return null
    val mb = (sizeBytes + 500_000L) / 1_000_000L
    return "~$mb MB"
}

@Composable
fun PostPairOfflinePackOfferDialog(
    visible: Boolean,
    packLabel: String,
    sizeMbText: String?,
    onDownload: () -> Unit,
    onDismiss: () -> Unit,
) {
    if (!visible) return
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Offline model (optional)") },
        text = {
            Text(
                "Download $packLabel for offline chat when your PC is unreachable. " +
                    "This step is optional; you can install the pack later under More → Models." +
                    if (sizeMbText != null) " Approximate download size: $sizeMbText." else "",
            )
        },
        confirmButton = {
            TextButton(onClick = onDownload) { Text("Download") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Not now") }
        },
    )
}
