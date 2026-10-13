package com.jarvis.companion

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

private val CreditMuted = Color(0xFF8C9CAF)
private val CreditError = Color(0xFFE8A87C)
private val URL_PATTERN = Regex("""https://[^\s)]+""")

/** CC BY credit for on-device voice packs; shown under the pack row without a tap (RFC-0140 Pocket TTS / Alba voice). */
object VoicePackCredit {
    const val OPEN_FAILED = "Could not open the voice credit link in a browser."

    fun creditText(packId: String, attribution: String?): String? = when {
        !attribution.isNullOrBlank() -> attribution.trim()
        packId == CompanionVoicePackCatalog.POCKET_TTS_ID -> CompanionVoicePackCatalog.POCKET_VOICE_ATTRIBUTION
        else -> null
    }

    fun firstUrl(credit: String): String? = URL_PATTERN.find(credit)?.value?.trimEnd('.', ',', ';')

    fun browserIntent(url: String): Intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))

    fun openInBrowser(context: Context, url: String): Boolean {
        // Same pattern as SponsorCredit: no resolveActivity pre-check (package visibility), catch instead.
        val intent = browserIntent(url)
        if (context !is Activity) intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        return try {
            context.startActivity(intent)
            true
        } catch (_: ActivityNotFoundException) {
            false
        }
    }
}

@Composable
fun VoicePackCreditText(packId: String, attribution: String?, modifier: Modifier = Modifier) {
    val credit = VoicePackCredit.creditText(packId, attribution) ?: return
    val url = VoicePackCredit.firstUrl(credit)
    val context = LocalContext.current
    var error by remember(packId) { mutableStateOf<String?>(null) }
    Column(modifier.fillMaxWidth()) {
        Text(
            text = credit,
            color = CreditMuted,
            fontSize = 11.sp,
            textDecoration = if (url != null) TextDecoration.Underline else null,
            modifier = if (url != null) {
                Modifier.clickable { error = if (VoicePackCredit.openInBrowser(context, url)) null else VoicePackCredit.OPEN_FAILED }
            } else {
                Modifier
            },
        )
        error?.let { Text(it, color = CreditError, fontSize = 11.sp, modifier = Modifier.padding(top = 2.dp)) }
    }
}
