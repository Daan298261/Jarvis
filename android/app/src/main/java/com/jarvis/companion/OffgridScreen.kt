package com.jarvis.companion

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp

@Composable
fun OffgridScreen(state: CompanionState, onChat: () -> Unit) {
    val context = LocalContext.current
    LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            Text("Offgrid", style = MaterialTheme.typography.headlineMedium)
            Text("Maps, knowledge and chat on this phone.")
            Button(onClick = onChat) { Text("Offline chat · Abliterated / Heretic") }
            Text(if (state.localModelReady) "Local model installed" else "Install a local model in More → Models", color = Muted)
        }
        item { OffGridContentSection() }
        item {
            Text("LoRa communication", style = MaterialTheme.typography.titleLarge)
            Text("This phone needs an external LoRa radio. Pair a Meshtastic radio using Bluetooth or USB in the Meshtastic app. Text messages are already text; voice needs compatible radio hardware and an audio decoder before transcription.")
            OutlinedButton(onClick = {
                val target = context.packageManager.getLaunchIntentForPackage("com.geeksville.mesh")
                    ?: Intent(Intent.ACTION_VIEW, Uri.parse("https://meshtastic.org/docs/software/android/installation/"))
                context.startActivity(target)
            }) { Text("Open / install Meshtastic") }
            Text("Live radio reception and radio-audio transcription are not connected to ANZU yet.", color = Muted)
        }
    }
}

@Composable
fun OffgridChatScreen(model: CompanionModel, state: CompanionState) {
    var draft by rememberSaveable { mutableStateOf("") }
    LaunchedEffect(Unit) { model.startOffgridConversation() }
    Column(Modifier.fillMaxSize()) {
        Text("Offgrid chat", style = MaterialTheme.typography.headlineMedium)
        Text("Uses a verified Abliterated / Heretic model on this phone.", color = Muted)
        TextButton(onClick = model::startOffgridConversation, enabled = !state.busy) { Text("New conversation") }
        LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(state.messages) { message ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp)) {
                        Text(if (message.optString("role") == "user") "You" else "ANZU")
                        Text(message.optString("text"))
                    }
                }
            }
        }
        if (state.busy) {
            LinearProgressIndicator(Modifier.fillMaxWidth())
            Text("Answering on this phone…", color = Muted)
        }
        state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        OutlinedTextField(draft, { draft = it }, label = { Text("Ask offline") }, modifier = Modifier.fillMaxWidth())
        Button(onClick = { model.sendOffgrid(draft); draft = "" }, enabled = draft.isNotBlank() && !state.busy) { Text("Send") }
    }
}
