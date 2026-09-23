package com.jarvis.companion

import android.content.Context
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable

/** RFC-0140 — optional post-pair offer for recommended STT+TTS voice packs. */
object PostPairVoicePackOfferPrefs {
    private const val PREFS_NAME = "companion_ui"
    private const val KEY_OFFER_HANDLED_DEVICE = "post_pair_voice_pack_offer_handled_device"

    fun shouldOffer(context: Context, deviceId: String, sttStatus: String, ttsStatus: String): Boolean {
        if (deviceId.isBlank()) return false
        if (sttStatus in CompanionVoicePackStatus.USABLE && ttsStatus in CompanionVoicePackStatus.USABLE) return false
        if (sttStatus == CompanionVoicePackStatus.DOWNLOADING || ttsStatus == CompanionVoicePackStatus.DOWNLOADING) return false
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

data class RecommendedVoicePackOffer(
    val sttId: String,
    val sttLabel: String,
    val sttSizeBytes: Long,
    val ttsId: String,
    val ttsLabel: String,
    val ttsSizeBytes: Long,
) {
    val combinedSizeBytes: Long get() = sttSizeBytes + ttsSizeBytes
}

fun recommendedVoicePackOffer(model: CompanionModel): RecommendedVoicePackOffer? {
    val items = model.voicePackManager.catalogJson()
    val stt = items.firstOrNull { it.optString("role") == "stt" && it.optBoolean("recommended") }
        ?: items.firstOrNull { it.optString("role") == "stt" }
        ?: return null
    val tts = items.firstOrNull { it.optString("role") == "tts" && it.optBoolean("recommended") }
        ?: items.firstOrNull { it.optString("role") == "tts" }
        ?: return null
    return RecommendedVoicePackOffer(
        sttId = stt.optString("id"),
        sttLabel = stt.optString("label").ifBlank { stt.optString("id") },
        sttSizeBytes = stt.optLong("size_bytes"),
        ttsId = tts.optString("id"),
        ttsLabel = tts.optString("label").ifBlank { tts.optString("id") },
        ttsSizeBytes = tts.optLong("size_bytes"),
    )
}

@Composable
fun PostPairVoicePackOfferDialog(
    visible: Boolean,
    offer: RecommendedVoicePackOffer?,
    onDownload: () -> Unit,
    onDismiss: () -> Unit,
) {
    if (!visible || offer == null) return
    val sizeMb = formatPackCatalogSizeMb(offer.combinedSizeBytes)
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("On-device voice (optional)") },
        text = {
            Text(
                "Download ${offer.sttLabel} + ${offer.ttsLabel} for speech when your PC is unreachable. " +
                    "Optional; install later under More → Voice." +
                    if (sizeMb != null) " Approximate download size: $sizeMb." else "",
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
