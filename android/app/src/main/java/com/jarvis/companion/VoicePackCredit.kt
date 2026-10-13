package com.jarvis.companion

import androidx.annotation.StringRes
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

private val URL_PATTERN = Regex("""https://[^\s)]+""")

/** CC BY credit for on-device voice packs, shown without a tap (RFC-0140 Pocket TTS / Alba voice). */
object VoicePackCredit {
    fun creditText(packId: String, attribution: String?): String? = when {
        !attribution.isNullOrBlank() -> attribution.trim()
        packId == CompanionVoicePackCatalog.POCKET_TTS_ID -> CompanionVoicePackCatalog.POCKET_VOICE_ATTRIBUTION
        else -> null
    }

    /** Every https link in the credit, in order; each gets its own tappable row. */
    fun urls(credit: String): List<String> =
        URL_PATTERN.findAll(credit).map { it.value.trimEnd('.', ',', ';') }.distinct().toList()

    /** Credit sentence without the raw URLs (they are rendered as separate links). */
    fun sentence(credit: String): String =
        credit.replace(Regex("""\s*\(https://[^\s)]+\)"""), "").replace(URL_PATTERN, "").replace(Regex("\\s+"), " ").trim()

    @StringRes
    fun linkLabel(url: String): Int = when {
        url.startsWith("https://creativecommons.org/licenses/by/4.0") -> R.string.voice_credit_link_license
        url.startsWith("https://huggingface.co/kyutai/pocket-tts") -> R.string.voice_credit_link_model
        url.startsWith("https://huggingface.co/soniqo/") -> R.string.voice_credit_link_conversion
        url.startsWith("https://huggingface.co/kyutai/tts-voices") -> R.string.voice_credit_link_voice
        else -> R.string.voice_credit_open_label
    }

    /** Pocket's credit shows whenever it is installed or selected; any other selected pack shows its own. */
    fun shouldShow(packId: String, selectedId: String, installed: Boolean): Boolean =
        packId == selectedId || (packId == CompanionVoicePackCatalog.POCKET_TTS_ID && installed)
}

/** Colours come from the caller's settings theme so this row matches the rest of the voice-pack card. */
@Composable
fun VoicePackCreditText(
    packId: String,
    attribution: String?,
    color: Color,
    errorColor: Color,
    modifier: Modifier = Modifier,
) {
    val credit = VoicePackCredit.creditText(packId, attribution) ?: return
    val context = LocalContext.current
    val openFailed = stringResource(R.string.voice_credit_open_failed)
    var error by remember(packId) { mutableStateOf<String?>(null) }
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(VoicePackCredit.sentence(credit), color = color, fontSize = 11.sp)
        VoicePackCredit.urls(credit).forEach { url ->
            val label = stringResource(VoicePackCredit.linkLabel(url))
            Text(
                text = "$label: $url",
                color = color,
                fontSize = 11.sp,
                textDecoration = TextDecoration.Underline,
                modifier = Modifier.clickable(role = Role.Button, onClickLabel = label) {
                    error = if (SponsorCredit.openInBrowser(context, url)) null else openFailed
                },
            )
        }
        error?.let { Text(it, color = errorColor, fontSize = 11.sp, modifier = Modifier.padding(top = 2.dp)) }
    }
}
