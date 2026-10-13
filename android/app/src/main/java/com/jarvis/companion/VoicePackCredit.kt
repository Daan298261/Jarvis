package com.jarvis.companion

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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

private val URL_PATTERN = Regex("""https://[^\s)]+""")

/** CC BY credit for on-device voice packs; shown under the pack row without a tap (RFC-0140 Pocket TTS / Alba voice). */
object VoicePackCredit {
    fun creditText(packId: String, attribution: String?): String? = when {
        !attribution.isNullOrBlank() -> attribution.trim()
        packId == CompanionVoicePackCatalog.POCKET_TTS_ID -> CompanionVoicePackCatalog.POCKET_VOICE_ATTRIBUTION
        else -> null
    }

    fun firstUrl(credit: String): String? = URL_PATTERN.find(credit)?.value?.trimEnd('.', ',', ';')
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
    val url = VoicePackCredit.firstUrl(credit)
    val context = LocalContext.current
    val openFailed = stringResource(R.string.voice_credit_open_failed)
    val openLabel = stringResource(R.string.voice_credit_open_label)
    var error by remember(packId) { mutableStateOf<String?>(null) }
    Column(modifier.fillMaxWidth()) {
        Text(
            text = credit,
            color = color,
            fontSize = 11.sp,
            textDecoration = if (url != null) TextDecoration.Underline else null,
            modifier = if (url != null) {
                Modifier.clickable(role = Role.Button, onClickLabel = openLabel) {
                    error = if (SponsorCredit.openInBrowser(context, url)) null else openFailed
                }
            } else {
                Modifier
            },
        )
        error?.let { Text(it, color = errorColor, fontSize = 11.sp, modifier = Modifier.padding(top = 2.dp)) }
    }
}
