package com.jarvis.companion

import androidx.core.content.ContextCompat
import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.camera.core.CameraSelector
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.common.InputImage
import org.json.JSONObject
import java.time.LocalDateTime
import java.time.ZoneId
import java.util.concurrent.atomic.AtomicBoolean

private val Gold = Color(0xFFF5A623)
private val Ink = Color(0xFF070B12)
private val Panel = Color(0xFF111B28)
private val Muted = Color(0xFF8C9CAF)

class MainActivity : ComponentActivity() {
    private var latestIntent by mutableStateOf<Intent?>(null)
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        latestIntent = intent
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        latestIntent = intent
        setContent {
            val model: CompanionModel = viewModel()
            val state by model.state.collectAsStateWithLifecycle()
            val callState by CurrentCall.state.collectAsStateWithLifecycle()
            var tab by remember { mutableStateOf(if (model.api.endpoint.isEmpty()) "More" else "Home") }
            var draft by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf("") }
            var incomingCall by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf<String?>(null) }
            DisposableEffect(model) {
                val observer = androidx.lifecycle.LifecycleEventObserver { _, event ->
                    if (event == androidx.lifecycle.Lifecycle.Event.ON_START) model.setForeground(true)
                    if (event == androidx.lifecycle.Lifecycle.Event.ON_STOP) model.setForeground(false)
                }
                lifecycle.addObserver(observer)
                model.setForeground(lifecycle.currentState.isAtLeast(androidx.lifecycle.Lifecycle.State.STARTED))
                onDispose { lifecycle.removeObserver(observer); model.setForeground(false) }
            }
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
            var photoPath by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf<String?>(null) }
            val camera = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { saved ->
                photoPath?.let { path ->
                    val file = java.io.File(path)
                    if (saved) {
                        val uri = androidx.core.content.FileProvider.getUriForFile(this@MainActivity, "$packageName.files", file)
                        model.uploadCaptured(uri, file)
                    } else file.delete()
                }
                photoPath = null
            }
            val cameraPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
                if (granted) {
                    val folder = java.io.File(cacheDir, "camera").apply { mkdirs() }
                    val file = java.io.File.createTempFile("jarvis-photo-", ".jpg", folder)
                    photoPath = file.absolutePath
                    camera.launch(androidx.core.content.FileProvider.getUriForFile(this@MainActivity, "$packageName.files", file))
                }
            }
            val notificationPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { }
            LaunchedEffect(Unit) {
                if (android.os.Build.VERSION.SDK_INT >= 33) notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
            LaunchedEffect(latestIntent) {
                val delivered = latestIntent ?: return@LaunchedEffect
                delivered.getStringExtra("incoming_call")?.let { incomingCall = it }
                delivered.getStringExtra(Intent.EXTRA_TEXT)?.let { draft = it; tab = "Chat" }
                val shared = mutableListOf<android.net.Uri>()
                @Suppress("DEPRECATION")
                when (delivered.action) {
                    Intent.ACTION_SEND -> delivered.getParcelableExtra<android.net.Uri>(Intent.EXTRA_STREAM)?.let(shared::add)
                    Intent.ACTION_SEND_MULTIPLE -> {
                        @Suppress("DEPRECATION")
                        delivered.getParcelableArrayListExtra<android.net.Uri>(Intent.EXTRA_STREAM)?.let(shared::addAll)
                    }
                }
                // WhatsApp and other apps may also put media on ClipData.
                delivered.clipData?.let { clip ->
                    for (index in 0 until clip.itemCount) {
                        clip.getItemAt(index).uri?.let(shared::add)
                    }
                }
                shared.distinct().forEach(model::upload)
                if (shared.isNotEmpty()) tab = "Chat"
                // Consume extras so rotating the activity cannot upload the same share again.
                delivered.removeExtra(Intent.EXTRA_STREAM)
                delivered.removeExtra(Intent.EXTRA_TEXT)
                delivered.removeExtra("incoming_call")
                delivered.clipData = null
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
                        if (state.pendingMessage) Card(modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp)) {
                            var dismiss by remember { mutableStateOf(false) }
                            Column(Modifier.padding(12.dp)) {
                                Text("A message is waiting for confirmation", fontSize = 13.sp)
                                Row {
                                    TextButton(onClick = { model.retryPending() }, enabled = !state.busy) { Text("Retry safely") }
                                    TextButton(onClick = { dismiss = true }, enabled = !state.busy) { Text("Dismiss") }
                                }
                            }
                            if (dismiss) AlertDialog(onDismissRequest = { dismiss = false }, title = { Text("Dismiss pending message?") },
                                text = { Text("Jarvis may already be working on it. Check Tasks before sending it again. Dismissing does not cancel a task.") },
                                confirmButton = { TextButton(onClick = { dismiss = false; model.dismissPending() }) { Text("Dismiss") } },
                                dismissButton = { TextButton(onClick = { dismiss = false }) { Text("Keep") } })
                        }
                        if (callState.active) Card(modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp)) {
                            var routes by remember { mutableStateOf(false) }
                            Column(Modifier.padding(12.dp)) {
                                Text(callState.status, color = Gold)
                                Row {
                                    TextButton(onClick = { startService(Intent(this@MainActivity, CallService::class.java).setAction("mute")) }) { Text(if (callState.muted) "Unmute" else "Mute") }
                                    Box {
                                        TextButton(onClick = { routes = true }) { Text(callState.route.ifEmpty { "Audio" }) }
                                        DropdownMenu(routes, { routes = false }) { callState.routes.forEach { (id, name) ->
                                            DropdownMenuItem(text = { Text(name) }, onClick = {
                                                routes = false
                                                startService(Intent(this@MainActivity, CallService::class.java).setAction("route").putExtra("endpoint", id))
                                            })
                                        } }
                                    }
                                    TextButton(onClick = { startService(Intent(this@MainActivity, CallService::class.java).setAction("end")) }) { Text("Hang up") }
                                }
                            }
                        }
                        when (tab) {
                            "Home" -> {
                                Spacer(Modifier.height(12.dp))
                                Text("YOUR INTELLIGENCE, EVERYWHERE", fontSize = 10.sp, color = Muted, letterSpacing = 2.sp)
                                Box(Modifier.fillMaxWidth().weight(1f), contentAlignment = Alignment.Center) {
                                    PresenceHud(state.presenceMode, if (state.recording) "listening" else if (state.speaking) "speaking" else if (state.tasks.any { it.optString("status") in listOf("queued", "running") }) "thinking" else "idle")
                                }
                                Text(if (state.recording) "I’m listening." else if (state.speaking) "Speaking" else "What’s on your mind?", fontSize = 28.sp, fontWeight = FontWeight.Light)
                                if (state.liveTranscript.isNotEmpty()) Text(state.liveTranscript, fontSize = 14.sp, color = Gold, modifier = Modifier.padding(top = 8.dp))
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
                                    IconButton(onClick = { cameraPermission.launch(Manifest.permission.CAMERA) }) { Icon(Icons.Outlined.PhotoCamera, "Take photo") }
                                    IconButton(onClick = { mic.launch(Manifest.permission.RECORD_AUDIO) }) { Icon(if (state.recording) Icons.Outlined.Stop else Icons.Outlined.Mic, "Voice message") }
                                    Spacer(Modifier.weight(1f))
                                    Button(onClick = { model.send(draft) }, enabled = draft.isNotBlank() && !state.busy) { Text("Send"); Icon(Icons.Outlined.ArrowUpward, null) }
                                }
                            }
                            "Tasks" -> {
                                Text("Your swarm at work", fontSize = 25.sp, modifier = Modifier.padding(vertical = 12.dp))
                                LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                                    if (state.swarm.length() > 0) item { SwarmOverviewCard(state.swarm) }
                                    if (state.coding.length() > 0) item { CodingOverviewCard(state.coding) }
                                    items(state.codingDecisions, key = { "decision-${it.optString("id")}" }) { decision ->
                                        CodingDecisionCard(decision, model)
                                    }
                                    if (state.tasks.isEmpty()) item { Text("Tasks appear here as soon as Jarvis starts working.", color = Muted) }
                                    items(state.tasks, key = { "task-${it.optString("id")}" }) { task -> TaskCard(task, model) }
                                }
                            }
                            "Studio" -> StudioScreen(model, state)
                            "More" -> MoreScreen(model, state)
                        }
                    }
                }
            }
        }
    }
}

@Composable private fun PresenceHud(mode: String, phase: String) {
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
            setLayerType(android.view.View.LAYER_TYPE_HARDWARE, null)
            val loader = androidx.webkit.WebViewAssetLoader.Builder()
                .addPathHandler("/assets/", androidx.webkit.WebViewAssetLoader.AssetsPathHandler(context)).build()
            web = this
            setBackgroundColor(android.graphics.Color.TRANSPARENT)
            settings.javaScriptEnabled = true
            settings.allowFileAccess = false
            settings.allowContentAccess = false
            settings.domStorageEnabled = false
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView, request: android.webkit.WebResourceRequest) = true
                override fun shouldInterceptRequest(view: WebView, request: android.webkit.WebResourceRequest): android.webkit.WebResourceResponse? {
                    return loader.shouldInterceptRequest(request.url)
                        ?: android.webkit.WebResourceResponse("text/plain", "UTF-8", java.io.ByteArrayInputStream(ByteArray(0)))
                }
            }
            loadUrl("https://appassets.androidplatform.net/assets/orb/index.html")
        }
    }, update = {
        it.evaluateJavascript("window.setJarvisAppearance && window.setJarvisAppearance(${JSONObject.quote(mode)})", null)
        it.evaluateJavascript("window.setJarvisPhase && window.setJarvisPhase(${JSONObject.quote(phase)})", null)
    })
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

@Composable private fun VoicePicker(state: CompanionState, select: (String) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    val selected = state.voiceProfiles.firstOrNull { it.optString("id") == state.selectedVoice }
    Box {
        TextButton(onClick = { expanded = true }, enabled = state.voiceProfiles.isNotEmpty()) {
            Icon(Icons.Outlined.GraphicEq, null, Modifier.size(16.dp))
            Text("  ${selected?.optString("display_name") ?: "Voice"}  ▾", maxLines = 1)
        }
        DropdownMenu(expanded, { expanded = false }) {
            state.voiceProfiles.forEach { voice ->
                DropdownMenuItem(
                    text = { Text(voice.optString("display_name") + if (!voice.optBoolean("available")) " · unavailable" else "") },
                    enabled = voice.optBoolean("available"),
                    onClick = { select(voice.getString("id")); expanded = false },
                )
            }
        }
    }
}

@Composable private fun InfoCard(title: String, text: String) {
    Card(Modifier.fillMaxWidth().padding(vertical = 6.dp)) { Column(Modifier.padding(18.dp)) { Text(title, fontWeight = FontWeight.SemiBold); Text(text, color = Muted, fontSize = 13.sp, modifier = Modifier.padding(top = 8.dp)) } }
}

@Composable private fun StudioScreen(model: CompanionModel, state: CompanionState) {
    var studio by remember { mutableStateOf<JSONObject?>(null) }
    var loadError by remember { mutableStateOf<String?>(null) }
    var refreshing by remember { mutableStateOf(false) }
    suspend fun loadStudio() {
        refreshing = true
        loadError = null
        try {
            studio = model.fetchStudioStatus()
        } catch (error: Exception) {
            loadError = error.message ?: "Could not reach Jarvis."
            if (studio == null) {
                val fallback = state.capabilities.optJSONObject("studio")
                if (fallback != null && fallback.length() > 0) studio = fallback
            }
        } finally {
            refreshing = false
        }
    }
    LaunchedEffect(state.connected, state.capabilities) { loadStudio() }
    val available = studio?.optBoolean("available") == true
    val detail = studio?.optString("detail").orEmpty().ifEmpty {
        if (available) "BlackGrid Multimedia Studio is connected." else "Generation is not available yet."
    }
    val provider = studio?.optString("provider", "blackgrid") ?: "blackgrid"
    val operations = studio?.optJSONArray("operations")?.let { array ->
        (0 until array.length()).mapNotNull { index -> array.optString(index).takeIf { it.isNotEmpty() } }
    } ?: emptyList()
    Column(Modifier.fillMaxWidth()) {
        Spacer(Modifier.height(32.dp))
        Icon(Icons.Outlined.AutoAwesome, null, Modifier.size(48.dp), tint = Gold)
        Text("Creative studio", fontSize = 30.sp, modifier = Modifier.padding(top = 20.dp))
        Text("Images · motion · voice via $provider", color = Muted, modifier = Modifier.padding(vertical = 12.dp))
        Card(
            Modifier.fillMaxWidth().padding(vertical = 6.dp),
            colors = CardDefaults.cardColors(containerColor = if (available) Color(0xFF15261F) else Color(0xFF1A1520)),
        ) {
            Column(Modifier.padding(18.dp)) {
                Text(
                    if (available) "● CONNECTED" else "○ NOT CONNECTED",
                    color = if (available) Color(0xFF74DCCD) else Gold,
                    fontSize = 11.sp,
                    letterSpacing = 1.sp,
                )
                Text("BlackGrid Studio", fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 10.dp))
                Text(detail, color = Muted, fontSize = 13.sp, modifier = Modifier.padding(top = 8.dp))
                if (loadError != null && studio == null) {
                    Text(loadError.orEmpty(), color = Color(0xFFE8A87C), fontSize = 12.sp, modifier = Modifier.padding(top = 8.dp))
                }
            }
        }
        if (available && operations.isNotEmpty()) {
            InfoCard(
                "Available when connected",
                operations.joinToString(" · "),
            )
        }
        if (!available) {
            InfoCard(
                "Generation",
                "Creative tools stay read-only until Jarvis reports studio.available=true. No local preview engine runs on the phone.",
            )
        }
        Button(
            onClick = { model.action { loadStudio() } },
            enabled = !refreshing && !state.busy,
            modifier = Modifier.padding(top = 8.dp),
        ) { Text(if (refreshing) "Refreshing…" else "Refresh status") }
        if (!state.connected) {
            Text("Connect on the More tab to load live studio status from Jarvis.", color = Muted, fontSize = 12.sp, modifier = Modifier.padding(top = 8.dp))
        }
    }
}

@Composable private fun SwarmOverviewCard(swarm: JSONObject) {
    val nodes = swarm.optJSONArray("nodes")?.objects() ?: emptyList()
    val workers = swarm.optJSONArray("workers")?.objects() ?: emptyList()
    val available = workers.count { it.optBoolean("available") }
    Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(16.dp)) {
        Text("SWARM · ${swarm.optString("mode", "unknown").uppercase()}", color = Gold, fontSize = 10.sp)
        Text("${nodes.size} node${if (nodes.size == 1) "" else "s"} · $available/${workers.size} workers available",
            fontWeight = FontWeight.Medium, modifier = Modifier.padding(vertical = 8.dp))
        nodes.take(4).forEach { node ->
            val seen = node.optString("last_seen_at").take(19).replace('T', ' ')
            Text("${node.optString("hostname", node.optString("id"))} · ${node.optString("status", "unknown")}${if (seen.isNotEmpty()) " · seen $seen" else ""}",
                color = Muted, fontSize = 12.sp, modifier = Modifier.padding(vertical = 2.dp))
        }
        workers.take(6).forEach { worker ->
            Text("${worker.optString("name", worker.optString("kind", worker.optString("id", "Worker")))} · ${worker.optString("status", "unknown")}",
                color = if (worker.optBoolean("available")) MaterialTheme.colorScheme.onSurface else Muted, fontSize = 12.sp,
                modifier = Modifier.padding(vertical = 2.dp))
        }
    } }
}

@Composable private fun CodingOverviewCard(coding: JSONObject) {
    val workers = coding.optJSONArray("workers")?.objects() ?: emptyList()
    Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(16.dp)) {
        Text("CODING WORKERS", color = Gold, fontSize = 10.sp)
        workers.forEach { worker ->
            Text(worker.optString("name", worker.optString("id")), fontWeight = FontWeight.Medium,
                modifier = Modifier.padding(top = 8.dp))
            Text(worker.optString("status", "unknown"), color = Muted, fontSize = 12.sp)
        }
    } }
}

@Composable private fun CodingDecisionCard(decision: JSONObject, model: CompanionModel) {
    var responding by remember { mutableStateOf(false) }
    var resolution by remember(decision.optString("id")) { mutableStateOf("") }
    Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = Color(0xFF242018))) {
        Column(Modifier.padding(16.dp)) {
            Text("CODING DECISION", color = Gold, fontSize = 10.sp)
            Text(decision.optString("title"), fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 8.dp))
            Text(decision.optString("detail"), color = Muted, fontSize = 12.sp, modifier = Modifier.padding(top = 6.dp))
            TextButton(onClick = { responding = true }) { Text("Respond") }
        }
    }
    if (responding) AlertDialog(
        onDismissRequest = { responding = false },
        title = { Text("Resolve coding decision") },
        text = { OutlinedTextField(resolution, { resolution = it.take(2000) }, label = { Text("Instructions for Jarvis") }, minLines = 3) },
        confirmButton = { TextButton(onClick = {
            responding = false
            model.resolveCodingDecision(decision.getString("id"), resolution.trim())
        }, enabled = resolution.isNotBlank()) { Text("Resolve") } },
        dismissButton = { TextButton(onClick = { responding = false }) { Text("Cancel") } },
    )
}

@Composable private fun TaskCard(task: JSONObject, model: CompanionModel) {
    var expanded by remember { mutableStateOf(false) }
    Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(16.dp)) {
        Text(task.optString("status").uppercase() + if (task.optBoolean("stale")) " · NO RECENT PROGRESS" else "", color = Gold, fontSize = 10.sp)
        Text(task.optString("title"), fontWeight = FontWeight.Medium, modifier = Modifier.padding(vertical = 8.dp))
        Text(task.optString("activity"), color = Muted, fontSize = 12.sp)
        Text("${task.optString("worker")} · ${task.optString("node")} · ${task.optDouble("elapsed_seconds").toInt()}s", color = Muted, fontSize = 11.sp, modifier = Modifier.padding(top = 8.dp))
        task.optJSONObject("approval")?.let { approval ->
            Text("Approval required", color = Gold, modifier = Modifier.padding(top = 12.dp))
            Text(approval.optString("action"), fontSize = 12.sp)
            Row {
                TextButton(onClick = { model.approve(task.getString("id"), approval.getString("token"), true) }) { Text("Approve this action") }
                TextButton(onClick = { model.approve(task.getString("id"), approval.getString("token"), false) }) { Text("Reject") }
            }
        }
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
    var pairingCode by remember { mutableStateOf(model.api.invitation) }
    var scannerOpen by remember { mutableStateOf(false) }
    var scanError by remember { mutableStateOf<String?>(null) }
    var schedulePrompt by remember { mutableStateOf("") }
    var whenText by remember { mutableStateOf(LocalDateTime.now().plusHours(1).withSecond(0).withNano(0).toString()) }
    var recurrence by remember { mutableStateOf("once") }
    var editingSchedule by remember { mutableStateOf<String?>(null) }
    val qrPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) scannerOpen = true
        else scanError = "Camera permission is needed to scan the desktop pairing QR code. You can still enter the code manually."
    }
    LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Text("Connection", fontSize = 25.sp, modifier = Modifier.padding(vertical = 12.dp))
            OutlinedTextField(endpoint, { endpoint = it }, label = { Text("Jarvis HTTPS endpoint") }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(pin, { pin = it }, label = { Text("Server fingerprint") }, modifier = Modifier.fillMaxWidth())
            if (model.api.deviceId.isEmpty()) OutlinedTextField(
                pairingCode,
                { pairingCode = CompanionCodeValidator.normalize(it) },
                label = { Text("6-digit pairing code") },
                singleLine = true,
                keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(keyboardType = androidx.compose.ui.text.input.KeyboardType.NumberPassword),
                modifier = Modifier.fillMaxWidth(),
            )
            if (model.api.deviceId.isEmpty()) {
                Button(
                    onClick = {
                        scanError = null
                        if (ContextCompat.checkSelfPermission(model.getApplication(), Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
                            scannerOpen = true
                        } else qrPermission.launch(Manifest.permission.CAMERA)
                    },
                    enabled = !state.busy,
                    modifier = Modifier.padding(top = 8.dp),
                ) { Text("Scan desktop QR") }
                scanError?.let { Text(it, color = MaterialTheme.colorScheme.error, fontSize = 12.sp) }
            }
            Button(onClick = { model.pair(endpoint, pin, pairingCode) },
                enabled = !state.busy && (model.api.deviceId.isNotEmpty() || CompanionCodeValidator.isComplete(pairingCode))) {
                Text(if (model.api.deviceId.isEmpty()) "Pair with Jarvis" else "Connect / check approval")
            }
            Text("Phone fingerprint: ${model.api.fingerprint().chunked(8).joinToString(" ")}", color = Muted, fontSize = 11.sp)
            Text("Confirm this fingerprint on your Jarvis desktop to finish pairing.", color = Muted, fontSize = 12.sp)
        }

        if (scannerOpen) item {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Scan the pairing QR shown on your Jarvis desktop", fontWeight = FontWeight.Medium)
                    PairingQrScanner(
                        onScanned = { value ->
                            runCatching { CompanionPairingQrParser.parse(value) }
                                .onSuccess { invitation ->
                                    endpoint = invitation.endpoint
                                    pin = invitation.serverPin
                                    pairingCode = invitation.code
                                    scannerOpen = false
                                }
                                .onFailure { error -> scanError = error.message ?: "That QR code is not a valid Jarvis pairing invitation." }
                        },
                        onDismiss = { scannerOpen = false },
                    )
                    TextButton(onClick = { scannerOpen = false }) { Text("Cancel scanner") }
                }
            }
        }

        item {
            Text("WhatsApp", fontSize = 20.sp, modifier = Modifier.padding(top = 18.dp))
            Text(
                "Save Jarvis as a WhatsApp contact on this phone so you can message the linked desktop session.",
                color = Muted,
                fontSize = 12.sp,
            )
            val contactsPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
                if (granted) model.addJarvisWhatsAppContact()
            }
            Button(
                onClick = {
                    if (androidx.core.content.ContextCompat.checkSelfPermission(
                            model.getApplication(),
                            Manifest.permission.WRITE_CONTACTS,
                        ) == android.content.pm.PackageManager.PERMISSION_GRANTED
                    ) model.addJarvisWhatsAppContact()
                    else contactsPermission.launch(Manifest.permission.WRITE_CONTACTS)
                },
                enabled = state.connected && !state.busy,
            ) { Text("Add Jarvis on WhatsApp") }
        }

        item {
            Text("Notifications & calls", fontSize = 20.sp, modifier = Modifier.padding(top = 18.dp))
            val device = state.capabilities.optJSONObject("device")
            Row(verticalAlignment = Alignment.CenterVertically) { Text("Task notifications", Modifier.weight(1f)); Switch(device?.optBoolean("notifications") == true, { model.preferences(it, device?.optBoolean("critical_calls") == true) }, enabled = state.connected) }
            Row(verticalAlignment = Alignment.CenterVertically) { Text("Calls for critical events", Modifier.weight(1f)); Switch(device?.optBoolean("critical_calls") == true, { model.preferences(device?.optBoolean("notifications") == true, it) }, enabled = state.connected) }
            if (state.capabilities.optJSONObject("calls")?.optBoolean("push_configured") != true) Text("Background push needs the Jarvis push service configured.", color = Muted, fontSize = 12.sp)
        }
        item {
            Text("Voice & presence", fontSize = 20.sp, modifier = Modifier.padding(top = 18.dp))
            Text("Presence", color = Muted, fontSize = 12.sp, modifier = Modifier.padding(top = 8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(state.presenceMode == "orb", { model.selectPresence("orb") }, { Text("Glowing orb") })
                FilterChip(state.presenceMode == "humanoid", { model.selectPresence("humanoid") }, { Text("Humanoid HUD") })
            }
            Text("Server voice", color = Muted, fontSize = 12.sp, modifier = Modifier.padding(top = 12.dp))
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.weight(1f)) { VoicePicker(state, model::selectVoice) }
                OutlinedButton(onClick = { model.previewVoice(state.selectedVoice) },
                    enabled = state.connected && state.selectedVoice.isNotEmpty() && !state.busy) { Text("Preview") }
            }
            val voice = state.capabilities.optJSONObject("voice")
            Text("Speech recognition · ${if (voice?.optBoolean("stt_ready") == true) "ready" else "unavailable"}  ·  Speech output · ${if (voice?.optBoolean("tts_ready") == true) "ready" else "unavailable"}",
                color = Muted, fontSize = 12.sp)
            Text(
                if (voice?.optBoolean("realtime") == true) "Realtime duplex voice is available over pinned TLS. Clip STT/TTS remains the fallback."
                else "Audio is processed by your paired Jarvis host and transported through pinned TLS.",
                color = Muted, fontSize = 11.sp, modifier = Modifier.padding(top = 6.dp),
            )
        }
        item {
            Text("Schedules", fontSize = 20.sp, modifier = Modifier.padding(top = 18.dp))
            OutlinedTextField(schedulePrompt, { schedulePrompt = it }, label = { Text("What should Jarvis do?") }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(whenText, { whenText = it }, label = { Text("Local date/time · YYYY-MM-DDTHH:MM") }, modifier = Modifier.fillMaxWidth())
            Row { listOf("once", "daily", "weekly").forEach { value -> FilterChip(recurrence == value, { recurrence = value }, { Text(value) }, modifier = Modifier.padding(end = 6.dp)) } }
            Button(onClick = { runCatching { LocalDateTime.parse(whenText).atZone(ZoneId.systemDefault()) }.onSuccess {
                model.schedule(editingSchedule, schedulePrompt, it, recurrence)
                editingSchedule = null
            } }, enabled = state.connected && schedulePrompt.isNotBlank()) { Text(if (editingSchedule == null) "Schedule on Jarvis" else "Save schedule") }
            if (editingSchedule != null) TextButton(onClick = { editingSchedule = null; schedulePrompt = "" }) { Text("Cancel editing") }
        }
        items(state.schedules) { schedule -> Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(14.dp)) {
            Text(schedule.optString("prompt"))
            val next = runCatching { java.time.Instant.ofEpochSecond(schedule.getLong("next_run")).atZone(ZoneId.systemDefault()).toLocalDateTime() }.getOrNull()
            Text("${schedule.optString("recurrence")} · ${if (schedule.optBoolean("enabled")) "scheduled" else "paused / complete"}${next?.let { " · $it" } ?: ""}", color = Muted)
            Row {
                TextButton(onClick = {
                    editingSchedule = schedule.getString("id")
                    schedulePrompt = schedule.optString("prompt")
                    recurrence = schedule.optString("recurrence", "once")
                    next?.let { whenText = it.withSecond(0).withNano(0).toString() }
                }) { Text("Edit") }
                if (schedule.optBoolean("enabled")) TextButton(onClick = { model.pauseSchedule(schedule.getString("id")) }) { Text("Pause") }
                else TextButton(onClick = { model.resumeSchedule(schedule.getString("id")) }) { Text("Resume") }
            }
        } } }
        item { Text("Call history", fontSize = 20.sp, modifier = Modifier.padding(top = 18.dp)) }
        items(state.calls) { call -> InfoCard("Jarvis · ${call.optString("state")}", call.optString("direction")) }
        item { Spacer(Modifier.height(20.dp)) }
    }
}

@OptIn(ExperimentalGetImage::class)
@Composable private fun PairingQrScanner(onScanned: (String) -> Unit, onDismiss: () -> Unit) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val previewView = remember { PreviewView(context) }
    val cameraProvider = remember { ProcessCameraProvider.getInstance(context) }
    val barcodeScanner = remember { BarcodeScanning.getClient() }
    val mainExecutor = remember { ContextCompat.getMainExecutor(context) }
    val delivered = remember { AtomicBoolean(false) }

    DisposableEffect(cameraProvider, lifecycleOwner) {
        cameraProvider.addListener({
            val provider = runCatching { cameraProvider.get() }.getOrElse {
                onDismiss()
                return@addListener
            }
            val preview = Preview.Builder().build().also { it.surfaceProvider = previewView.surfaceProvider }
            val analysis = ImageAnalysis.Builder()
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .build()
            analysis.setAnalyzer(mainExecutor) { imageProxy ->
                val image = imageProxy.image
                if (image == null) {
                    imageProxy.close()
                    return@setAnalyzer
                }
                barcodeScanner.process(InputImage.fromMediaImage(image, imageProxy.imageInfo.rotationDegrees))
                    .addOnSuccessListener { barcodes ->
                        val raw = barcodes.firstOrNull { !it.rawValue.isNullOrBlank() }?.rawValue
                        if (raw != null && delivered.compareAndSet(false, true)) onScanned(raw)
                    }
                    .addOnCompleteListener { imageProxy.close() }
            }
            runCatching {
                provider.unbindAll()
                provider.bindToLifecycle(lifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis)
            }.onFailure { onDismiss() }
        }, mainExecutor)
        onDispose {
            cameraProvider.addListener({ runCatching { cameraProvider.get().unbindAll() } }, mainExecutor)
            barcodeScanner.close()
        }
    }
    AndroidView(factory = { previewView }, modifier = Modifier.fillMaxWidth().height(300.dp))
}
