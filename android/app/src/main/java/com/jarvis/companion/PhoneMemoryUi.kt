package com.jarvis.companion

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

data class PhoneMemorySnapshot(
    val projectId: String = "",
    val project: JSONObject = JSONObject(),
    val projects: List<JSONObject> = emptyList(),
    val chats: List<JSONObject> = emptyList(),
    val loaded: Boolean = false,
)

@Composable fun PhoneAnswerOptions(model: CompanionModel, onMemory: (() -> Unit)? = null) {
    val memory by model.phoneMemoryUi.collectAsStateWithLifecycle()
    val quick by model.quickAnswers.collectAsStateWithLifecycle()
    val status by model.quickStatus.collectAsStateWithLifecycle()
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        FilterChip(quick, { model.quickAnswers(true) }, { Text("Quick") })
        FilterChip(!quick, { model.quickAnswers(false) }, { Text("Detailed") })
        if (onMemory != null) TextButton(onClick = onMemory) { Text(if (memory.projectId.isBlank()) "Memory" else memory.project.optString("name", "Memory").take(16)) }
    }
    if (status.isNotBlank()) Text(status, style = MaterialTheme.typography.labelSmall, color = Muted)
}

@Composable fun PhoneMemorySettings(model: CompanionModel) {
    val state by model.state.collectAsStateWithLifecycle()
    val snapshot by model.phoneMemoryUi.collectAsStateWithLifecycle()
    val enabled by model.memoryEnabled.collectAsStateWithLifecycle()
    val warm by model.keepModelWarm.collectAsStateWithLifecycle()
    val engine by model.decisionEngine.collectAsStateWithLifecycle()
    val cloud by model.jevCloudAllowed.collectAsStateWithLifecycle()
    val scope = rememberCoroutineScope()
    LaunchedEffect(Unit) { model.refreshPhoneMemory() }
    val key = snapshot.projectId + snapshot.project.toString()
    var notes by remember(key) { mutableStateOf(snapshot.project.optString("notes")) }
    var instructions by remember(key) { mutableStateOf(snapshot.project.optString("instructions")) }
    var projectName by remember { mutableStateOf("") }
    var menu by remember { mutableStateOf(false) }
    var inspect by remember { mutableStateOf<String?>(null) }
    var messages by remember { mutableStateOf(emptyList<JSONObject>()) }
    var summary by remember { mutableStateOf("") }
    var page by remember { mutableIntStateOf(0) }
    var loadError by remember { mutableStateOf("") }
    var delete by remember { mutableStateOf<String?>(null) }
    var search by remember { mutableStateOf("") }
    var hits by remember { mutableStateOf(emptyList<JSONObject>()) }
    LaunchedEffect(snapshot.projectId) { hits = emptyList(); inspect = null; page = 0; search = "" }
    LaunchedEffect(inspect, page) {
        inspect?.let { id ->
            runCatching { withContext(Dispatchers.IO) {
                model.phoneMemory.messages(id, 40, page * 40) to model.phoneMemory.summary(id)?.optJSONArray("excerpts")?.objects().orEmpty()
            } }.onSuccess { (rows, excerpts) -> messages = rows; summary = excerpts.joinToString("\n") { "${it.optString("sender")}: ${it.optString("text")}" }; loadError = "" }
                .onFailure { loadError = "Cannot read archive: ${it.message}" }
        }
    }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Memory & speed", style = MaterialTheme.typography.titleLarge)
        PhoneAnswerOptions(model)
        Text("Quick prefers the smallest installed Abliterated/Heretic model and shorter answers. Detailed keeps your model selection.", color = Muted)
        val fastId = CompanionPackCatalog.ABLITERATED_06B_ID
        val fastTransfer = state.modelDownloads[fastId]
        // Pack files are stat'ed on IO (packFileSnapshot), never during composition.
        val fastInstalled by produceState(false, state.modelDownloads, state.localPackStatus) {
            value = model.packManager.packFileSnapshot().installed[fastId] == true
        }
        OutlinedButton(onClick = model::installFastPhoneModel, enabled = !state.busy) { Text("Download fast 0.6B model · 397 MB") }
        if (fastTransfer != null && fastTransfer.stage != ModelDownloadStage.READY) ModelTransferFeedback(fastTransfer,
            { model.cancelModelDownload(fastId) }, { model.installFastPhoneModel() })
        if (fastInstalled) Text("Fast 0.6B model is ready · Quick answers can use it", color = MaterialTheme.colorScheme.primary)
        Row { Text("Keep phone model warm for 30 seconds", Modifier.weight(1f)); Switch(warm, model::keepModelWarm) }
        Text("Uses more RAM between replies. Released when ANZU goes into the background or Android reports memory pressure.", color = Muted)
        Text("Optional decision routing", style = MaterialTheme.typography.titleMedium)
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            listOf("local" to "Phone", "laya" to "Laya · PC", "jev" to "Jev · cloud").forEach { (id, label) ->
                FilterChip(engine == id, { model.decisionEngine(id) }, { Text(label) })
            }
        }
        Text("Laya/Jev choose Quick or Detailed; a chat model writes the answer. They require your paired desktop. Offline always uses the phone.", color = Muted)
        if (engine == "jev") {
            Row { Text("Allow Jev to receive this question for routing", Modifier.weight(1f)); Switch(cloud, model::allowJevCloud) }
            Text("Only the latest question (up to 512 characters) is sent; saved memory stays on the phone. Your desktop must also allow Jev.", color = Muted)
        }
        Row { Text("Use saved memory in phone answers", Modifier.weight(1f)); Switch(enabled, model::memoryEnabled) }
        Text("Chats are archived encrypted on this phone. Only selected notes, instructions and relevant quotes enter the prompt; no extra embedding model runs. Desktop chat uses its own memory.", color = Muted)
        Box {
            OutlinedButton(onClick = { menu = true }, enabled = !state.busy && snapshot.loaded) { Text("Project: ${snapshot.project.optString("name", "All chats")}") }
            DropdownMenu(menu, { menu = false }) {
                DropdownMenuItem(text = { Text("All chats") }, onClick = { menu = false; model.selectMemoryProject("") })
                snapshot.projects.forEach { project -> DropdownMenuItem(text = { Text(project.optString("name")) }, onClick = { menu = false; model.selectMemoryProject(project.getString("id")) }) }
            }
        }
        Text("Switching projects starts a new conversation. Project history stays separate; global owner notes/instructions apply everywhere.", color = Muted)
        OutlinedTextField(projectName, { projectName = it.take(100) }, label = { Text("New project") }, modifier = Modifier.fillMaxWidth())
        TextButton(onClick = { model.createMemoryProject(projectName); projectName = "" }, enabled = projectName.isNotBlank() && !state.busy && snapshot.loaded) { Text("Create project") }
        OutlinedTextField(notes, { notes = it.take(8000) }, label = { Text("Notes") }, modifier = Modifier.fillMaxWidth(), maxLines = 5, enabled = snapshot.loaded)
        OutlinedTextField(instructions, { instructions = it.take(4000) }, label = { Text("Specific instructions") }, modifier = Modifier.fillMaxWidth(), maxLines = 5, enabled = snapshot.loaded)
        Button(onClick = { model.savePhoneMemory(snapshot.project.optString("name", "All chats"), notes, instructions) }, enabled = snapshot.loaded && !state.busy) { Text("Save memory") }
        Text("Saved chats and summaries", style = MaterialTheme.typography.titleMedium)
        OutlinedTextField(search, { search = it.take(200) }, label = { Text("Search this project's saved messages") }, modifier = Modifier.fillMaxWidth())
        TextButton(onClick = {
            val projectId = snapshot.projectId
            val query = search
            scope.launch {
                runCatching { withContext(Dispatchers.IO) { model.phoneMemory.recall(query, projectId, null, 8) } }
                    .onSuccess { if (snapshot.projectId == projectId) hits = it }
                    .onFailure { if (snapshot.projectId == projectId) loadError = it.message.orEmpty() }
            }
        }, enabled = search.isNotBlank() && snapshot.loaded) { Text("Search") }
        hits.forEach { hit -> TextButton(onClick = { inspect = hit.optString("chat_id"); page = 0 }) { Text("${hit.optString("sender")}: ${hit.optString("text").take(120)}") } }
        snapshot.chats.take(30).forEach { chat -> Row {
            TextButton(onClick = { inspect = chat.getString("id"); page = 0 }, modifier = Modifier.weight(1f)) { Text("${chat.optString("title")} · ${chat.optInt("message_count")} messages") }
            TextButton(onClick = { delete = chat.getString("id") }, enabled = !state.busy && snapshot.loaded) { Text("Forget") }
        } }
        if (loadError.isNotBlank()) Text(loadError, color = MaterialTheme.colorScheme.error)
    }
    if (inspect != null) AlertDialog(onDismissRequest = { inspect = null }, title = { Text("Saved chat") }, text = {
        Column {
            Text("Chat ID: $inspect\nProject: ${snapshot.project.optString("name", "All chats")}")
            LazyColumn(Modifier.heightIn(max = 430.dp)) {
                if (page == 0 && summary.isNotBlank()) item { Text("Summary (quoted extracts, not new facts):\n$summary") }
                items(messages) { message -> Text("${message.optString("role")} · ${message.optString("id")}\n${message.optString("text")}\n", Modifier.padding(vertical = 6.dp)) }
            }
            Row {
                TextButton(onClick = { page-- }, enabled = page > 0) { Text("Previous") }
                TextButton(onClick = { page++ }, enabled = messages.size == 40) { Text("Next") }
            }
        }
    }, confirmButton = { TextButton(onClick = { inspect = null }) { Text("Close") } })
    delete?.let { id -> AlertDialog(onDismissRequest = { delete = null }, title = { Text("Forget saved chat?") }, text = { Text("Remove this phone's messages, summary and recall index. This does not delete an existing desktop copy.") },
        confirmButton = { TextButton(onClick = { delete = null; model.forgetMemoryChat(id) }, enabled = !state.busy && snapshot.loaded) { Text("Forget") } },
        dismissButton = { TextButton(onClick = { delete = null }) { Text("Keep") } }) }
}
