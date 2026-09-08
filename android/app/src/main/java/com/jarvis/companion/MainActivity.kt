package com.jarvis.companion

import android.Manifest
import android.content.Intent
import android.os.Bundle
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import org.json.JSONObject
import java.time.LocalDateTime
import java.time.ZoneId

private val Gold = Color(0xFFF5A623)
private val Ink = Color(0xFF070B12)
private val Panel = Color(0xFF111B28)
private val Muted = Color(0xFF8C9CAF)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            val model: CompanionModel = viewModel()
            val state by model.state.collectAsStateWithLifecycle()
            var tab by remember { mutableStateOf(if (model.api.endpoint.isEmpty()) "More" else "Home") }
            var draft by remember { mutableStateOf(intent.getStringExtra(Intent.EXTRA_TEXT) ?: "") }
            var incomingCall by remember { mutableStateOf(intent.getStringExtra("incoming_call")) }
            val callPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
                if (granted) {
                    val service = Intent(this@MainActivity, CallService::class.java).setAction("outgoing")
                    incomingCall?.let { service.putExtra("call_id", it) }
                    startForegroundService(service)
                    incomingCall = null
                }
            }
            val mic = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted -> if (granted) model.toggleRecord() }
            val attachment = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri -> uri?.let(model::upload) }
            val notificationPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { }
            LaunchedEffect(Unit) {
                if (android.os.Build.VERSION.SDK_INT >= 33) notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
                @Suppress("DEPRECATION")
                (intent.getParcelableExtra<android.net.Uri>(Intent.EXTRA_STREAM))?.let(model::upload)
            }
            MaterialTheme(colorScheme = darkColorScheme(primary = Gold, background = Ink, surface = Panel, onSurface = Color(0xFFE7EDF5), secondary = Color(0xFF74DCCD))) {
                if (incomingCall != null) AlertDialog(onDismissRequest = { incomingCall = null }, title = { Text("Jarvis is calling") },
                    text = { Text("Answer to discuss the event. Your microphone stays off until you answer.") },
                    confirmButton = { TextButton(onClick = { callPermission.launch(Manifest.permission.RECORD_AUDIO) }) { Text("Answer") } },
                    dismissButton = { TextButton(onClick = { val id = incomingCall; incomingCall = null; model.action { if (id != null) model.api.json("/calls/$id/end", "POST") } }) { Text("Decline") } })
                Scaffold(containerColor = Ink, bottomBar = {
                    NavigationBar(containerColor = Ink) {
                        listOf("Home" to Icons.Outlined.RadioButtonChecked, "Chat" to Icons.Outlined.ChatBubbleOutline,
                            "Tasks" to Icons.Outlined.Checklist, "Studio" to Icons.Outlined.AutoAwesome, "More" to Icons.Outlined.Tune).forEach { (label, icon) ->
                            NavigationBarItem(selected = tab == label, onClick = { tab = label }, icon = { Icon(icon, label) }, label = { Text(label) })
                        }
                    }
                }) { padding ->
                    Column(Modifier.fillMaxSize().padding(padding).padding(horizontal = 20.dp)) {
                        Row(Modifier.fillMaxWidth().padding(top = 18.dp, bottom = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                            Text("J A R V I S", fontSize = 20.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                            Text(if (state.connected) "● CONNECTED" else "○ OFFLINE", fontSize = 10.sp, color = if (state.connected) Color(0xFF74DCCD) else Muted)
                        }
                        if (state.error != null) Card(colors = CardDefaults.cardColors(containerColor = Color(0xFF34251D)), modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp)) {
                            Text(state.error.orEmpty(), Modifier.padding(12.dp), fontSize = 12.sp)
                        }
                        when (tab) {
                            "Home" -> {
                                Spacer(Modifier.height(12.dp))
                                Text("YOUR INTELLIGENCE, EVERYWHERE", fontSize = 10.sp, color = Muted, letterSpacing = 2.sp)
                                Box(Modifier.fillMaxWidth().weight(1f), contentAlignment = Alignment.Center) {
                                    PresenceOrb(if (state.recording) "listening" else if (state.speaking) "speaking" else if (state.tasks.any { it.optString("status") in listOf("queued", "running") }) "thinking" else "idle")
                                }
                                Text(if (state.recording) "I’m listening." else if (state.speaking) "Speaking" else "What’s on your mind?", fontSize = 28.sp, fontWeight = FontWeight.Light)
                                Text(state.activity, fontSize = 12.sp, color = Muted, modifier = Modifier.padding(top = 8.dp, bottom = 20.dp))
                                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                    Button(onClick = { mic.launch(Manifest.permission.RECORD_AUDIO) }, modifier = Modifier.weight(1f)) {
                                        Icon(Icons.Outlined.Mic, null); Spacer(Modifier.width(6.dp)); Text(if (state.recording) "Send voice" else "Talk to Jarvis")
                                    }
                                    OutlinedButton(onClick = {
                                        callPermission.launch(Manifest.permission.RECORD_AUDIO)
                                    }, enabled = state.connected && state.capabilities.optJSONObject("calls")?.optBoolean("available") == true) { Icon(Icons.Outlined.Call, "Start call") }
                                }
                                TextButton(onClick = { tab = "Chat" }, modifier = Modifier.align(Alignment.CenterHorizontally)) { Text("Or write a message", color = Muted) }
                            }
                            "Chat" -> {
                                ModelPicker(state, model::selectModel)
                                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                                    TextButton(onClick = { model.openConversation(null) }) { Text("New conversation") }
                                    var history by remember { mutableStateOf(false) }
                                    Box { TextButton(onClick = { history = true }) { Text("History") }
                                        DropdownMenu(history, { history = false }) { state.conversations.forEach { c -> DropdownMenuItem(text = { Text(c.optString("title")) }, onClick = { history = false; model.openConversation(c.getString("id")) }) } }
                                    }
                                }
                                LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(12.dp), contentPadding = PaddingValues(vertical = 8.dp)) {
                                    if (state.messages.isEmpty()) item { Text("One conversation across your phone and Jarvis. Send a message, file, or voice note.", color = Muted, modifier = Modifier.padding(vertical = 24.dp)) }
                                    items(state.messages) { message ->
                                        Card(colors = CardDefaults.cardColors(containerColor = if (message.optString("role") == "user") Color(0xFF222B38) else Panel), modifier = Modifier.fillMaxWidth()) {
                                            Column(Modifier.padding(16.dp)) {
                                                Text(if (message.optString("role") == "user") "YOU" else "JARVIS", color = Gold, fontSize = 10.sp)
                                                Text(message.optString("text"), Modifier.padding(top = 8.dp), fontSize = 15.sp)
                                                if (message.optString("role") == "assistant") TextButton(onClick = { model.speak(message.optString("text")) }) { Icon(Icons.Outlined.VolumeUp, null); Text(if (state.speaking) " Stop" else " Read aloud") }
                                            }
                                        }
                                    }
                                }
                                if (state.attachmentIds.isNotEmpty()) Text("${state.attachmentIds.size} attachment(s) ready", color = Gold, fontSize = 12.sp)
                                OutlinedTextField(value = draft, onValueChange = { draft = it }, placeholder = { Text("Ask anything…") }, modifier = Modifier.fillMaxWidth(), maxLines = 5, shape = RoundedCornerShape(20.dp))
                                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                                    IconButton(onClick = { attachment.launch("*/*") }) { Icon(Icons.Outlined.AttachFile, "Attach file") }
                                    IconButton(onClick = { mic.launch(Manifest.permission.RECORD_AUDIO) }) { Icon(if (state.recording) Icons.Outlined.Stop else Icons.Outlined.Mic, "Voice message") }
                                    Spacer(Modifier.weight(1f))
                                    Button(onClick = { model.send(draft) }, enabled = draft.isNotBlank() && !state.busy) { Text("Send"); Icon(Icons.Outlined.ArrowUpward, null) }
                                }
                            }
                            "Tasks" -> {
                                Text("Your swarm at work", fontSize = 25.sp, modifier = Modifier.padding(vertical = 12.dp))
                                LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                                    if (state.tasks.isEmpty()) item { Text("Tasks appear here as soon as Jarvis starts working.", color = Muted) }
                                    items(state.tasks) { task -> TaskCard(task, model) }
                                }
                            }
                            "Studio" -> {
                                Spacer(Modifier.height(32.dp)); Icon(Icons.Outlined.AutoAwesome, null, Modifier.size(48.dp), tint = Gold)
                                Text("Creative studio", fontSize = 30.sp, modifier = Modifier.padding(top = 20.dp))
                                Text("Images. Motion. Voice.", color = Muted, modifier = Modifier.padding(vertical = 12.dp))
                                InfoCard("BlackGrid integration", "Multistep generation, takes, timelines, and stitching will be connected through BlackGrid Multimedia Studio. The media engine is not connected in this build.")
                            }
                            "More" -> MoreScreen(model, state)
                        }
                    }
                }
            }
        }
    }
}

@Composable private fun PresenceOrb(phase: String) {
    var web by remember { mutableStateOf<WebView?>(null) }
    val owner = androidx.lifecycle.compose.LocalLifecycleOwner.current
    DisposableEffect(owner) {
        val observer = androidx.lifecycle.LifecycleEventObserver { _, event ->
            if (event == androidx.lifecycle.Lifecycle.Event.ON_PAUSE) web?.onPause()
            if (event == androidx.lifecycle.Lifecycle.Event.ON_RESUME) web?.onResume()
        }
        owner.lifecycle.addObserver(observer)
        onDispose { owner.lifecycle.removeObserver(observer); web?.destroy(); web = null }
    }
    AndroidView(modifier = Modifier.fillMaxWidth().height(310.dp), factory = { context ->
        WebView(context).apply {
            web = this
            setBackgroundColor(android.graphics.Color.TRANSPARENT)
            settings.javaScriptEnabled = true
            settings.allowFileAccess = false
            settings.allowContentAccess = false
            settings.domStorageEnabled = false
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView, request: android.webkit.WebResourceRequest) = true
                override fun shouldInterceptRequest(view: WebView, request: android.webkit.WebResourceRequest): android.webkit.WebResourceResponse? {
                    if (!request.url.toString().startsWith("file:///android_asset/orb/")) return android.webkit.WebResourceResponse("text/plain", "UTF-8", java.io.ByteArrayInputStream(ByteArray(0)))
                    return null
                }
            }
            loadUrl("file:///android_asset/orb/index.html")
        }
    }, update = { it.evaluateJavascript("window.setJarvisPhase && window.setJarvisPhase(${JSONObject.quote(phase)})", null) })
}

@Composable private fun ModelPicker(state: CompanionState, select: (String) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    Box {
        TextButton(onClick = { expanded = true }) { Icon(Icons.Outlined.AutoAwesome, null, Modifier.size(16.dp)); Text("  ${state.selectedModel.uppercase()}  ▾") }
        DropdownMenu(expanded, { expanded = false }) {
            DropdownMenuItem(text = { Text("Auto · Jarvis selects") }, onClick = { select("auto"); expanded = false })
            state.models.forEach { model -> DropdownMenuItem(text = { Text(model.optString("label") + if (!model.optBoolean("installed")) " · unavailable" else "") }, enabled = model.optBoolean("installed"), onClick = { select(model.getString("name")); expanded = false }) }
        }
    }
}

@Composable private fun InfoCard(title: String, text: String) {
    Card(Modifier.fillMaxWidth().padding(vertical = 6.dp)) { Column(Modifier.padding(18.dp)) { Text(title, fontWeight = FontWeight.SemiBold); Text(text, color = Muted, fontSize = 13.sp, modifier = Modifier.padding(top = 8.dp)) } }
}

@Composable private fun TaskCard(task: JSONObject, model: CompanionModel) {
    var expanded by remember { mutableStateOf(false) }
    Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(16.dp)) {
        Text(task.optString("status").uppercase() + if (task.optBoolean("stale")) " · NO RECENT PROGRESS" else "", color = Gold, fontSize = 10.sp)
        Text(task.optString("title"), fontWeight = FontWeight.Medium, modifier = Modifier.padding(vertical = 8.dp))
        Text(task.optString("activity"), color = Muted, fontSize = 12.sp)
        Text("${task.optString("worker")} · ${task.optString("node")} · ${task.optDouble("elapsed_seconds").toInt()}s", color = Muted, fontSize = 11.sp, modifier = Modifier.padding(top = 8.dp))
        Row {
            TextButton(onClick = { expanded = !expanded }) { Text(if (expanded) "Less" else "Activity") }
            if (task.optString("status") in listOf("queued", "running", "waiting")) TextButton(onClick = { model.cancel(task.getString("id")) }) { Text("Cancel") }
        }
        if (expanded) { task.optJSONArray("events")?.objects()?.takeLast(8)?.forEach { Text(it.optString("title"), fontSize = 12.sp, modifier = Modifier.padding(vertical = 3.dp)) }; if (task.optString("result").isNotEmpty()) Text(task.optString("result"), fontSize = 13.sp) }
    } }
}

@Composable private fun MoreScreen(model: CompanionModel, state: CompanionState) {
    var endpoint by remember { mutableStateOf(model.api.endpoint) }
    var pin by remember { mutableStateOf(model.api.pin) }
    var invitation by remember { mutableStateOf(model.api.invitation) }
    var schedulePrompt by remember { mutableStateOf("") }
    var whenText by remember { mutableStateOf(LocalDateTime.now().plusHours(1).withSecond(0).withNano(0).toString()) }
    var recurrence by remember { mutableStateOf("once") }
    LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Text("Connection", fontSize = 25.sp, modifier = Modifier.padding(vertical = 12.dp))
            OutlinedTextField(endpoint, { endpoint = it }, label = { Text("Jarvis HTTPS endpoint") }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(pin, { pin = it }, label = { Text("Server fingerprint") }, modifier = Modifier.fillMaxWidth())
            if (model.api.deviceId.isEmpty()) OutlinedTextField(invitation, { invitation = it }, label = { Text("Pairing invitation") }, modifier = Modifier.fillMaxWidth())
            Button(onClick = { model.pair(endpoint, pin, invitation) }, enabled = !state.busy) { Text(if (model.api.deviceId.isEmpty()) "Pair with Jarvis" else "Connect / check approval") }
            Text("Phone fingerprint: ${model.api.fingerprint().chunked(8).joinToString(" ")}", color = Muted, fontSize = 11.sp)
            Text("Confirm this fingerprint on your Jarvis desktop to finish pairing.", color = Muted, fontSize = 12.sp)
        }
        item {
            Text("Notifications & calls", fontSize = 20.sp, modifier = Modifier.padding(top = 18.dp))
            val device = state.capabilities.optJSONObject("device")
            Row(verticalAlignment = Alignment.CenterVertically) { Text("Task notifications", Modifier.weight(1f)); Switch(device?.optBoolean("notifications") == true, { model.preferences(it, device?.optBoolean("critical_calls") == true) }, enabled = state.connected) }
            Row(verticalAlignment = Alignment.CenterVertically) { Text("Calls for critical events", Modifier.weight(1f)); Switch(device?.optBoolean("critical_calls") == true, { model.preferences(device?.optBoolean("notifications") == true, it) }, enabled = state.connected) }
            if (state.capabilities.optJSONObject("calls")?.optBoolean("push_configured") != true) Text("Background push needs the Jarvis push service configured.", color = Muted, fontSize = 12.sp)
        }
        item {
            Text("Schedules", fontSize = 20.sp, modifier = Modifier.padding(top = 18.dp))
            OutlinedTextField(schedulePrompt, { schedulePrompt = it }, label = { Text("What should Jarvis do?") }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(whenText, { whenText = it }, label = { Text("Local date/time · YYYY-MM-DDTHH:MM") }, modifier = Modifier.fillMaxWidth())
            Row { listOf("once", "daily", "weekly").forEach { value -> FilterChip(recurrence == value, { recurrence = value }, { Text(value) }, modifier = Modifier.padding(end = 6.dp)) } }
            Button(onClick = { runCatching { LocalDateTime.parse(whenText).atZone(ZoneId.systemDefault()) }.onSuccess { model.schedule(schedulePrompt, it, recurrence) } }, enabled = state.connected && schedulePrompt.isNotBlank()) { Text("Schedule on Jarvis") }
        }
        items(state.schedules) { schedule -> Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(14.dp)) { Text(schedule.optString("prompt")); Text("${schedule.optString("recurrence")} · ${if (schedule.optBoolean("enabled")) "scheduled" else "paused / complete"}", color = Muted); if (schedule.optBoolean("enabled")) TextButton(onClick = { model.pauseSchedule(schedule.getString("id")) }) { Text("Pause") } } } }
        item { Text("Call history", fontSize = 20.sp, modifier = Modifier.padding(top = 18.dp)) }
        items(state.calls) { call -> InfoCard("Jarvis · ${call.optString("state")}", call.optString("direction")) }
        item { Spacer(Modifier.height(20.dp)) }
    }
}
