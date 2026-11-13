package com.jarvis.companion

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

/**
 * Drives the S5 page. Work runs in [scope] (the companion view model's scope), so closing the page does
 * not cancel an update; [onChanged] refreshes chat / voice / off-grid state after every update or delete.
 */
class DownloadedContentController(
    private val manager: DownloadedContentManager,
    private val scope: CoroutineScope,
    private val onChanged: suspend () -> Unit,
) {
    var inventory by mutableStateOf<DownloadedInventory?>(null)
        private set
    var busyKey by mutableStateOf<String?>(null)
        private set
    var message by mutableStateOf<String?>(null)
        private set

    fun reload() = scope.launch { load() }

    private suspend fun load() {
        inventory = manager.inventory()
    }

    fun update(entry: DownloadedEntry) = run(entry) { manager.update(entry) }

    fun delete(entry: DownloadedEntry) = run(entry) { manager.delete(entry) }

    private fun run(entry: DownloadedEntry, block: suspend () -> Unit) {
        if (busyKey != null) return
        busyKey = entry.key
        message = null
        scope.launch {
            try {
                block()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                message = "${entry.title}: ${e.message ?: "failed"}"
            } finally {
                runCatching { onChanged() }
                runCatching { load() }
                busyKey = null
            }
        }
    }
}

/** More → Downloaded content: one entry point showing the total, opening the full page. */
@Composable
fun DownloadedContentSection(model: CompanionModel, offGrid: OffGridViewModel = viewModel()) {
    val state by model.state.collectAsStateWithLifecycle()
    val transfers = state.modelDownloads.values.filter { it.stage != ModelDownloadStage.READY }
    val controller = remember(model, offGrid) {
        DownloadedContentController(
            DownloadedContentManager.forManagers(model.packManager, model.voicePackManager, offGrid.manager),
            model.viewModelScope,
        ) {
            model.refreshCompanionPackStatus().join()
            model.refreshVoicePackStatus().join()
            offGrid.refresh().join()
        }
    }
    var open by remember { mutableStateOf(false) }
    LaunchedEffect(controller) { controller.reload() }
    Text("Downloaded content", fontSize = 20.sp, modifier = Modifier.padding(top = 18.dp))
    transfers.forEach { transfer ->
        Text(transfer.label, style = MaterialTheme.typography.titleSmall)
        ModelTransferFeedback(transfer, { model.cancelModelDownload(transfer.packId) }, { model.downloadModelPack(transfer.packId) })
    }
    Card(Modifier.fillMaxWidth()) {
        Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                val inv = controller.inventory
                Text(if (inv == null) "Checking storage…" else "${OffGridSelection.formatBytes(inv.totalBytes)} on this phone")
                Text("AI models, voice packs, maps and knowledge bases", fontSize = 12.sp, color = Muted)
            }
            OutlinedButton(onClick = { open = true; controller.reload() }) { Text("Manage") }
        }
    }
    if (open) {
        // Downloads started from the model / voice / off-grid sections keep moving; re-read while any runs.
        LaunchedEffect(controller.inventory) {
            if (controller.inventory?.entries?.any { it.downloading } == true) {
                kotlinx.coroutines.delay(2_000)
                controller.reload()
            }
        }
        Dialog(onDismissRequest = { open = false }, properties = DialogProperties(usePlatformDefaultWidth = false)) {
            Surface(Modifier.fillMaxSize()) {
                DownloadedContentPage(controller.inventory, controller.busyKey, controller.message,
                    onUpdate = controller::update, onDelete = controller::delete, onClose = { open = false },
                    modelDownloads = transfers, onCancelModel = model::cancelModelDownload, onResumeModel = { model.downloadModelPack(it) })
            }
        }
    }
}

/** Stateless page: sections per kind with subtotals, per-row Update/Delete, both behind a confirm. */
@Composable
fun DownloadedContentPage(
    inventory: DownloadedInventory?,
    busyKey: String?,
    message: String?,
    onUpdate: (DownloadedEntry) -> Unit,
    onDelete: (DownloadedEntry) -> Unit,
    onClose: () -> Unit,
    modelDownloads: List<ModelDownloadState> = emptyList(),
    onCancelModel: (String) -> Unit = {},
    onResumeModel: (String) -> Unit = {},
) {
    var confirmDelete by remember { mutableStateOf<DownloadedEntry?>(null) }
    var confirmUpdate by remember { mutableStateOf<DownloadedEntry?>(null) }
    Column(Modifier.padding(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Downloaded content", fontSize = 20.sp, modifier = Modifier.weight(1f))
            TextButton(onClick = onClose) { Text("Close") }
        }
        if (inventory == null) {
            Text("Checking storage…", color = Muted)
            LinearProgressIndicator(Modifier.fillMaxWidth().padding(top = 8.dp))
            return@Column
        }
        Text("Total: ${OffGridSelection.formatBytes(inventory.totalBytes)}", fontSize = 16.sp)
        message?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        inventory.errors.forEach { Text(it, color = MaterialTheme.colorScheme.error, fontSize = 12.sp) }
        LazyColumn(Modifier.fillMaxWidth().padding(top = 8.dp)) {
            items(modelDownloads, key = { "transfer-${it.packId}" }) { transfer ->
                Text(transfer.label, style = MaterialTheme.typography.titleSmall)
                ModelTransferFeedback(transfer, { onCancelModel(transfer.packId) }, { onResumeModel(transfer.packId) })
            }
            ContentKind.entries.forEach { kind ->
                val rows = inventory.entries.filter { it.kind == kind }
                item(key = "h-${kind.name}") {
                    Text("${kind.label} · ${OffGridSelection.formatBytes(inventory.bytesOf(kind))}", fontSize = 16.sp,
                        color = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(top = 14.dp, bottom = 4.dp))
                    if (rows.isEmpty()) Text("Nothing downloaded", color = Muted, fontSize = 12.sp)
                }
                items(rows, key = { it.key }) { e ->
                    Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
                        Text("${e.title} · ${OffGridSelection.formatBytes(e.bytes)}")
                        Text(stateLabel(e.state) + " · " + e.detail, fontSize = 12.sp,
                            color = if (e.state == ContentState.CURRENT) Muted else MaterialTheme.colorScheme.error)
                        if (busyKey == e.key || e.downloading) LinearProgressIndicator(Modifier.fillMaxWidth().padding(vertical = 4.dp))
                        if (e.downloading) Text("Downloading…", fontSize = 12.sp, color = Muted)
                        val actionable = busyKey == null && !e.downloading
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            if (e.updateBytes > 0L) TextButton(onClick = { confirmUpdate = e }, enabled = actionable) { Text("Update") }
                            TextButton(onClick = { confirmDelete = e }, enabled = actionable) { Text("Delete") }
                        }
                    }
                }
            }
        }
    }
    confirmDelete?.let { e ->
        AlertDialog(
            onDismissRequest = { confirmDelete = null },
            title = { Text("Delete ${e.title}?") },
            text = { Text("Frees ${OffGridSelection.formatBytes(e.bytes)}. ${deleteConsequence(e.kind)}") },
            confirmButton = { Button(onClick = { confirmDelete = null; onDelete(e) }) { Text("Delete") } },
            dismissButton = { TextButton(onClick = { confirmDelete = null }) { Text("Cancel") } },
        )
    }
    confirmUpdate?.let { e ->
        AlertDialog(
            onDismissRequest = { confirmUpdate = null },
            title = { Text("Update ${e.title}?") },
            text = { Text("Downloads up to ${OffGridSelection.formatBytes(e.updateBytes)} and checks it against the catalogue checksum. " +
                "The current copy stays until the new one verifies.") },
            confirmButton = { Button(onClick = { confirmUpdate = null; onUpdate(e) }) { Text("Update") } },
            dismissButton = { TextButton(onClick = { confirmUpdate = null }) { Text("Cancel") } },
        )
    }
}

private fun stateLabel(s: ContentState) = when (s) {
    ContentState.CURRENT -> "Up to date"
    ContentState.UPDATE_AVAILABLE -> "Update available"
    ContentState.FAILED_VERIFICATION -> "Failed verification"
    ContentState.PARTIAL -> "Incomplete"
    ContentState.RETIRED -> "Not in catalogue"
}

private fun deleteConsequence(kind: ContentKind) = when (kind) {
    ContentKind.MODEL -> "Offline chat stops working until a model is downloaded again."
    ContentKind.VOICE -> "ANZU falls back to this phone's built-in speech engines."
    ContentKind.MAP -> "This region is no longer available offline."
    ContentKind.KNOWLEDGE -> "This knowledge base can no longer be opened offline."
}
