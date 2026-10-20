package com.jarvis.companion

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import java.util.Locale

internal fun modelDownloadBytes(bytes: Long): String = when {
    bytes >= 1024L * 1024 * 1024 -> String.format(Locale.ROOT, "%.1f GiB", bytes / (1024.0 * 1024 * 1024))
    bytes >= 1024L * 1024 -> String.format(Locale.ROOT, "%.1f MiB", bytes / (1024.0 * 1024))
    bytes >= 1024 -> String.format(Locale.ROOT, "%.0f KiB", bytes / 1024.0)
    else -> "$bytes B"
}

/**
 * The same transfer remains visible on every phone model surface. [showBar] is false where the
 * surface already shows its own progress bar for this download, so one download never has two bars.
 */
@Composable
fun ModelTransferFeedback(download: ModelDownloadState, onCancel: () -> Unit, onResume: () -> Unit, showBar: Boolean = true) {
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (download.active) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
            Text(download.statusLabel, fontWeight = FontWeight.Medium,
                color = if (download.stage == ModelDownloadStage.ERROR) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary,
                modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
        }
        val fraction = download.fraction
        if (showBar && fraction != null) LinearProgressIndicator(progress = { fraction }, modifier = Modifier.fillMaxWidth())
        else if (showBar && download.active) LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        if (download.totalBytes > 0 || download.receivedBytes > 0) {
            val total = if (download.totalBytes > 0) " / ${modelDownloadBytes(download.totalBytes)}" else ""
            val speed = if (download.stage == ModelDownloadStage.DOWNLOADING && download.bytesPerSecond > 0)
                " · ${modelDownloadBytes(download.bytesPerSecond)}/s" else ""
            Text("${modelDownloadBytes(download.receivedBytes)}$total$speed", style = MaterialTheme.typography.bodySmall, color = Muted)
        }
        if (download.detail.isNotBlank()) Text(download.detail, style = MaterialTheme.typography.bodySmall)
        if (download.active) TextButton(onClick = onCancel, modifier = Modifier.heightIn(min = 48.dp)) { Text("Cancel download") }
        else if (download.stage in setOf(ModelDownloadStage.PAUSED, ModelDownloadStage.ERROR)) {
            Button(onClick = onResume, modifier = Modifier.heightIn(min = 48.dp)) {
                Text(if (download.receivedBytes > 0) "Resume download" else "Retry download")
            }
        }
    }
}

@Composable
fun ModelLibraryCards(
    packs: List<DevicePackOption>, selectedId: String, downloads: Map<String, ModelDownloadState>, busy: Boolean,
    onSelect: (String) -> Unit, onDownload: (String) -> Unit, onCancel: (String) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        packs.forEach { pack ->
            val transfer = downloads[pack.id]
            val selected = pack.id == selectedId
            Card(Modifier.fillMaxWidth(), border = if (selected) BorderStroke(1.dp, MaterialTheme.colorScheme.primary) else null) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(pack.label, style = MaterialTheme.typography.titleSmall)
                    Text(buildList {
                        if (pack.installed) add("Installed")
                        if (selected) add("Selected")
                        if (pack.sizeBytes > 0) add(modelDownloadBytes(pack.sizeBytes))
                    }.joinToString(" · "), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
                    if (pack.minRamMb > 0) Text("Needs ${modelDownloadBytes(pack.minRamMb.toLong() * 1024 * 1024)} available RAM",
                        style = MaterialTheme.typography.bodySmall, color = Muted)
                    if (pack.id == CompanionPackCatalog.ABLITERATED_06B_ID) Text("Smallest download · quicker replies, lighter answers", style = MaterialTheme.typography.bodySmall)
                    if (transfer == null && pack.resumeBytes > 0) Text("Partial download saved · ${modelDownloadBytes(pack.resumeBytes)}", style = MaterialTheme.typography.bodySmall)
                    if (transfer != null) ModelTransferFeedback(transfer, { onCancel(pack.id) }, { onDownload(pack.id) })
                    if (transfer?.active != true && transfer?.stage !in setOf(ModelDownloadStage.PAUSED, ModelDownloadStage.ERROR)) {
                        if (pack.installed) OutlinedButton(onClick = { onSelect(pack.id) }, enabled = !busy && !selected,
                            modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) { Text(if (selected) "In use" else "Use this model") }
                        else if (pack.canDownload) Button(onClick = { onDownload(pack.id) }, enabled = !busy,
                            modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) { Text(if (pack.resumeBytes > 0) "Resume download" else "Download model") }
                        else Text("Available by file import", style = MaterialTheme.typography.bodySmall, color = Muted)
                    }
                }
            }
        }
    }
}
