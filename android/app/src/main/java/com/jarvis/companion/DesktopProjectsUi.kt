package com.jarvis.companion

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@Composable
fun DesktopProjectsButton(state: CompanionState, model: CompanionModel, openChat: () -> Unit) {
    var show by remember { mutableStateOf(false) }
    var name by remember { mutableStateOf("") }
    var rename by remember { mutableStateOf<String?>(null) }
    var editing by remember { mutableStateOf(false) }
    val selected = state.desktopProjects.firstOrNull { it.optString("id") == state.desktopProjectId }
    TextButton(onClick = { show = true }) { Text(selected?.optString("name") ?: "Projects & chats") }
    if (show) AlertDialog(
        onDismissRequest = { show = false },
        title = { Text("Projects & chats") },
        text = { Column {
            Text(if (state.connected) "Synced with your desktop" else "Saved project list · reconnect to open desktop chats", color = Muted)
            LazyColumn(Modifier.fillMaxWidth().heightIn(max = 400.dp)) {
                item { TextButton(onClick = { model.selectDesktopProject("") }) { Text("All chats") } }
                items(state.desktopProjects, key = { it.optString("id") }) { project ->
                    val id = project.optString("id")
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        TextButton(onClick = { model.selectDesktopProject(id) }) { Text("▸ ${project.optString("name")}") }
                        TextButton(enabled = state.connected, onClick = { rename = id; name = project.optString("name"); editing = true }) { Text("Rename") }
                    }
                    if (id == state.desktopProjectId) {
                        TextButton(enabled = state.connected, onClick = { model.selectDesktopProject(id); model.openConversation(null); show = false; openChat() }) { Text("New chat in this project") }
                        if (state.conversationId != null && !LocalConversationStore.isLocal(state.conversationId)) {
                            TextButton(enabled = state.connected, onClick = { model.moveChatToProject(id) }) { Text("Move current chat here") }
                        }
                        val ids = project.optJSONArray("conversationIds")
                        val chats = state.conversations.filter { chat -> chat.optString("project_id") == id || (0 until (ids?.length() ?: 0)).any { ids?.optString(it) == chat.optString("id") } }
                        chats.forEach { chat ->
                            TextButton(enabled = state.connected, onClick = { model.openConversation(chat.optString("id")); show = false; openChat() }) { Text(chat.optString("title").ifBlank { "Chat" }) }
                        }
                        if (chats.isEmpty()) Text("No chats in this project yet", color = Muted, modifier = Modifier.padding(12.dp))
                    }
                }
                if (state.desktopProjectId.isEmpty()) items(state.conversations, key = { it.optString("id") }) { chat ->
                    TextButton(enabled = state.connected, onClick = { model.openConversation(chat.optString("id")); show = false; openChat() }) { Text(chat.optString("title").ifBlank { "Chat" }) }
                }
            }
        } },
        confirmButton = { TextButton(enabled = state.connected, onClick = { rename = null; name = ""; editing = true }) { Text("New project") } },
        dismissButton = { TextButton(onClick = { show = false }) { Text("Close") } },
    )
    if (editing) AlertDialog(onDismissRequest = { editing = false }, title = { Text(if (rename == null) "New project" else "Rename project") },
        text = { OutlinedTextField(name, { name = it }, label = { Text("Project name") }, singleLine = true) },
        confirmButton = { TextButton(enabled = name.isNotBlank() && state.connected, onClick = {
            rename?.let { model.renameDesktopProject(it, name.trim()) } ?: model.createDesktopProject(name.trim())
            editing = false
        }) { Text("Save") } }, dismissButton = { TextButton(onClick = { editing = false }) { Text("Cancel") } })
}
