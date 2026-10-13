package com.jarvis.companion

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** RFC-0216 S4 Settings: voice language, Android voice, speech-recognition language, English pack offer. */
@Composable
fun VoiceLanguageSettings(model: CompanionModel, state: CompanionState) {
    val setting = model.voiceLanguage
    val voices = remember(setting, state.voiceTtsStatus, state.platformTtsReady) { model.platformVoicesForLanguage() }
    val pocket = model.voicePackManager.selectedTtsPack()
    val packSpeaks = VoiceLanguagePrefs.packSpeaks(pocket, setting.ttsLanguage)
    val packReady = state.voiceTtsStatus in CompanionVoicePackStatus.USABLE
    Column(Modifier.padding(top = 18.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Voice language", fontSize = 20.sp)
        Text("ANZU speaks and listens in this language, whatever your phone's system language is.")
        Picker("Spoken language", VoiceLanguagePrefs.label(setting.ttsLanguage),
            VoiceLanguagePrefs.options.map { it.tag to it.label }, model::setVoiceLanguage)
        Picker("Phone voice", setting.ttsVoiceName.ifBlank { "Best available" },
            listOf("" to "Best available") + voices.map { it.name to "${it.name}${if (it.needsNetwork) " (online)" else ""}" },
            model::setPlatformVoice)
        Picker("Speech recognition language",
            if (setting.sttLanguageOverride.isBlank()) "Same as spoken language" else VoiceLanguagePrefs.label(setting.sttLanguageOverride),
            listOf("" to "Same as spoken language") + VoiceLanguagePrefs.options.map { it.tag to it.label },
            model::setSttLanguage)
        if (!state.platformTtsReady) {
            Text("Starting this phone's text-to-speech…")
        } else if (voices.isEmpty()) {
            Text(VoiceLanguagePrefs.missingVoiceMessage(setting), color = MaterialTheme.colorScheme.error)
        }
        if (packSpeaks && pocket != null) {
            when {
                packReady -> Text("Offline voice: ${pocket.label} is installed and used when the desktop voice is unavailable.")
                state.voiceTtsStatus == CompanionVoicePackStatus.DOWNLOADING ->
                    Text("Downloading ${pocket.label}… ${state.voicePackProgress}%")
                else -> Button(onClick = { model.downloadVoicePack(pocket.id) }, enabled = !state.busy) {
                    Text("Download offline English voice (${"%.0f".format(pocket.sizeBytes / 1_000_000.0)} MB)")
                }
            }
        } else if (!packSpeaks) {
            Text("ANZU's offline voice pack speaks English only; ${VoiceLanguagePrefs.label(setting.ttsLanguage)} uses this phone's voice.")
        }
    }
}

@Composable
private fun Picker(title: String, current: String, options: List<Pair<String, String>>, onPick: (String) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(title, Modifier.weight(1f))
        OutlinedButton(onClick = { open = true }) { Text("$current  ▾", maxLines = 1) }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            options.forEach { (value, label) ->
                DropdownMenuItem(text = { Text(label) }, onClick = { open = false; onPick(value) })
            }
        }
    }
}
