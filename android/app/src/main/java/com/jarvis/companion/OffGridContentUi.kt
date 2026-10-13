package com.jarvis.companion

import android.app.Application
import android.content.Context
import android.webkit.WebView
import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.maplibre.android.MapLibre
import org.maplibre.android.camera.CameraPosition
import org.maplibre.android.geometry.LatLng
import org.maplibre.android.maps.MapView

class OffGridViewModel(app: Application) : AndroidViewModel(app) {
    val manager = OffGridContentManager(
        root = OffGridContentManager.storageRoot(app),
        digestCache = VerifiedDigestCache(persist = app.getSharedPreferences("offgrid_digest", Context.MODE_PRIVATE)),
        mapStore = MapLibreMapStore(app),
    )
    private val jobs = mutableMapOf<String, Job>()
    var message by mutableStateOf<String?>(null)

    init { refresh() }

    fun refresh() = viewModelScope.launch {
        runCatching { manager.refresh() }.onFailure { message = it.message }
    }

    /** Only called after the owner confirmed a non-empty selection. Downloads run one after another. */
    fun startDownloads(ids: List<String>) {
        if (ids.isEmpty()) return
        val picked = ids.map(manager::item)
        OffGridSelection.storageBlockReason(manager.freeSpace(), picked, manager.partialBytes(picked))?.let { message = it; return }
        ids.forEach { id ->
            if (jobs[id]?.isActive == true) return@forEach
            val previous = jobs.values.lastOrNull { it.isActive }
            jobs[id] = viewModelScope.launch {
                previous?.join()
                runCatching { manager.download(id) }.onFailure { if (it !is kotlinx.coroutines.CancellationException) message = it.message }
            }
        }
    }

    fun cancel(id: String) { jobs.remove(id)?.cancel() }

    fun delete(id: String) = viewModelScope.launch {
        cancel(id)
        runCatching { manager.delete(id) }.onFailure { message = it.message }
    }
}

/** More → Off-grid content: power-pylon entry, installed/in-progress items, readers. */
@Composable
fun OffGridContentSection(vm: OffGridViewModel = viewModel()) {
    val states by vm.manager.state.collectAsState()
    var picker by remember { mutableStateOf(false) }
    var readerFor by remember { mutableStateOf<OffGridItem?>(null) }
    var mapFor by remember { mutableStateOf<OffGridItem?>(null) }
    Column(Modifier.padding(top = 18.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Off-grid content", fontSize = 20.sp)
        Row(
            Modifier.fillMaxWidth().clickable(role = Role.Button, onClickLabel = "Choose off-grid content") { picker = true }
                .padding(vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Image(painterResource(R.drawable.bgp_logo), contentDescription = "Power pylon: choose off-grid content", Modifier.size(40.dp))
            Column(Modifier.weight(1f)) {
                Text("Choose offline maps & knowledge")
                Text("Pick what to keep on this phone for when the grid and network are down. Sizes are shown before anything downloads.",
                    fontSize = 12.sp, color = Muted)
            }
        }
        vm.message?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        vm.manager.catalog.filter { (states[it.id]?.status ?: OffGridStatus.MISSING) != OffGridStatus.MISSING || (states[it.id]?.partialBytes ?: 0) > 0 }
            .forEach { item ->
                val s = states[item.id] ?: OffGridItemState()
                OffGridRow(item, s,
                    onOpen = { if (item.isMap) mapFor = item else readerFor = item },
                    onCancel = { vm.cancel(item.id) },
                    onRetry = { vm.startDownloads(listOf(item.id)) },
                    onDelete = { vm.delete(item.id) })
            }
    }
    if (picker) OffGridPickerDialog(vm.manager.catalog, states, vm.manager.freeSpace(), onDismiss = { picker = false }) { ids ->
        picker = false
        vm.startDownloads(ids)
    }
    readerFor?.let { item -> ZimReaderDialog(vm, item) { readerFor = null } }
    mapFor?.let { item -> OffGridMapDialog(item) { mapFor = null } }
}

@Composable
private fun OffGridRow(item: OffGridItem, s: OffGridItemState, onOpen: () -> Unit, onCancel: () -> Unit, onRetry: () -> Unit, onDelete: () -> Unit) {
    Column(Modifier.fillMaxWidth()) {
        Text("${item.title} · ${if (item.isMap) "≈" else ""}${OffGridSelection.formatBytes(item.sizeBytes)}")
        when (s.status) {
            OffGridStatus.DOWNLOADING -> {
                LinearProgressIndicator(progress = { s.progress / 100f }, modifier = Modifier.fillMaxWidth())
                Row { Text("Downloading ${s.progress}%", Modifier.weight(1f), fontSize = 12.sp); TextButton(onClick = onCancel) { Text("Cancel") } }
            }
            OffGridStatus.READY -> Row {
                Text(if (item.isMap) "Ready offline" else "Ready offline · verified", Modifier.weight(1f), fontSize = 12.sp, color = Muted)
                TextButton(onClick = onOpen) { Text("Open") }
                TextButton(onClick = onDelete) { Text("Delete") }
            }
            OffGridStatus.ERROR -> {
                Text(s.error ?: "Download failed", color = MaterialTheme.colorScheme.error, fontSize = 12.sp)
                Row { TextButton(onClick = onRetry) { Text("Retry") }; TextButton(onClick = onDelete) { Text("Delete") } }
            }
            OffGridStatus.MISSING -> Row {
                Text("Paused at ${s.progress}%", Modifier.weight(1f), fontSize = 12.sp, color = Muted)
                TextButton(onClick = onRetry) { Text("Resume") }
                TextButton(onClick = onDelete) { Text("Delete") }
            }
        }
    }
}

/** Multi-select picker grouped by category; nothing downloads until the confirm step. */
@Composable
fun OffGridPickerDialog(
    catalog: List<OffGridItem>,
    states: Map<String, OffGridItemState>,
    freeBytes: Long,
    onDismiss: () -> Unit,
    onConfirm: (List<String>) -> Unit,
) {
    val selected = remember { mutableStateListOf<String>() }
    var confirming by remember { mutableStateOf(false) }
    val picked = catalog.filter { it.id in selected }
    if (confirming) {
        val block = OffGridSelection.storageBlockReason(freeBytes, picked)
        AlertDialog(
            onDismissRequest = { confirming = false },
            title = { Text("Download ${picked.size} item${if (picked.size == 1) "" else "s"}?") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    picked.forEach { Text("• ${it.title}: ${if (it.isMap) "≈" else ""}${OffGridSelection.formatBytes(it.sizeBytes)}") }
                    Text("Total: ${OffGridSelection.formatBytes(OffGridSelection.totalBytes(picked))} · free: ${OffGridSelection.formatBytes(freeBytes)}")
                    if (OffGridSelection.needsLargeConfirm(picked)) Text("This is a large download. Use Wi-Fi; downloads resume if interrupted.", color = MaterialTheme.colorScheme.error)
                    block?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                }
            },
            confirmButton = { Button(onClick = { onConfirm(selected.toList()) }, enabled = block == null) { Text("Download") } },
            dismissButton = { TextButton(onClick = { confirming = false }) { Text("Back") } },
        )
        return
    }
    Dialog(onDismissRequest = onDismiss, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxWidth().padding(16.dp), shape = MaterialTheme.shapes.large) {
            Column(Modifier.padding(16.dp)) {
                Text("Off-grid content", fontSize = 20.sp)
                Text("Select what to download. Only selected items are downloaded.", fontSize = 12.sp, color = Muted)
                LazyColumn(Modifier.weight(1f, fill = false).heightIn(max = 520.dp)) {
                    OffGridCategory.entries.forEach { cat ->
                        val rows = catalog.filter { it.category == cat }
                        if (rows.isEmpty()) return@forEach
                        item { Text(cat.label, fontSize = 16.sp, modifier = Modifier.padding(top = 12.dp)) }
                        items(rows, key = { it.id }) { item ->
                            val ready = states[item.id]?.status == OffGridStatus.READY
                            Row(Modifier.fillMaxWidth().clickable(enabled = !ready) {
                                if (item.id in selected) selected.remove(item.id) else selected.add(item.id)
                            }, verticalAlignment = Alignment.CenterVertically) {
                                Checkbox(checked = ready || item.id in selected, enabled = !ready, onCheckedChange = {
                                    if (it) selected.add(item.id) else selected.remove(item.id)
                                })
                                Column(Modifier.weight(1f)) {
                                    Text(item.title)
                                    Text("${if (item.isMap) "≈" else ""}${OffGridSelection.formatBytes(item.sizeBytes)}${if (ready) " · installed" else ""} · ${item.description}",
                                        fontSize = 12.sp, color = Muted)
                                }
                            }
                        }
                    }
                }
                Spacer(Modifier.padding(4.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = onDismiss) { Text("Close") }
                    Button(onClick = { confirming = true }, enabled = picked.isNotEmpty()) {
                        Text(if (picked.isEmpty()) "Select items" else "Download ${OffGridSelection.formatBytes(OffGridSelection.totalBytes(picked))}")
                    }
                }
            }
        }
    }
}

@Composable
private fun ZimReaderDialog(vm: OffGridViewModel, item: OffGridItem, onClose: () -> Unit) {
    val context = LocalContext.current
    var book by remember { mutableStateOf<ZimBook?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var query by remember { mutableStateOf("") }
    var hits by remember { mutableStateOf<List<ZimHit>>(emptyList()) }
    var page by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(item.id) {
        error = ZimNative.ensureLoaded(context)
        if (error == null) error = runCatching {
            val file = vm.manager.verifiedZim(item.id)
            book = withContext(Dispatchers.IO) { ZimBook(file) }
            page = book?.mainPath
        }.exceptionOrNull()?.let { it.message ?: "Could not open ${item.title}" }
    }
    LaunchedEffect(query, book) {
        val b = book ?: return@LaunchedEffect
        hits = withContext(Dispatchers.IO) { runCatching { b.search(query) }.getOrDefault(emptyList()) }
    }
    DisposableEffect(Unit) { onDispose { book?.close() } }
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize()) {
            Column(Modifier.padding(12.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(item.title, Modifier.weight(1f), fontSize = 18.sp)
                    TextButton(onClick = onClose) { Text("Close") }
                }
                error?.let { Text(it, color = MaterialTheme.colorScheme.error); return@Column }
                val b = book ?: run { Text("Opening…"); return@Column }
                OutlinedTextField(query, { query = it }, Modifier.fillMaxWidth(), label = { Text("Search offline") }, singleLine = true)
                if (query.isNotBlank()) {
                    LazyColumn(Modifier.weight(1f)) {
                        if (hits.isEmpty()) item { Text("No matches", color = Muted) }
                        items(hits) { hit ->
                            Column(Modifier.fillMaxWidth().clickable { page = hit.path; query = "" }.padding(vertical = 8.dp)) {
                                Text(hit.title)
                                if (hit.snippet.isNotBlank()) Text(hit.snippet.replace(Regex("<[^>]+>"), ""), fontSize = 12.sp, color = Muted, maxLines = 2)
                            }
                        }
                    }
                } else {
                    val start = page
                    if (start == null) Text("This archive has no main page; search above.", color = Muted)
                    else AndroidView(
                        factory = { ctx -> WebView(ctx).apply { ZimWebViewClient.configure(this); webViewClient = ZimWebViewClient(b) { error = it } } },
                        update = { web -> val url = ZimUrls.forPath(start); if (web.url != url) web.loadUrl(url) },
                        modifier = Modifier.weight(1f).fillMaxWidth(),
                    )
                }
            }
        }
    }
}

@Composable
private fun OffGridMapDialog(item: OffGridItem, onClose: () -> Unit) {
    val context = LocalContext.current
    val region = item.mapRegion ?: return
    val mapView = remember {
        MapLibre.getInstance(context.applicationContext)
        MapView(context).apply { onCreate(null) }
    }
    DisposableEffect(mapView) {
        mapView.onStart(); mapView.onResume()
        onDispose { mapView.onPause(); mapView.onStop(); mapView.onDestroy() }
    }
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize()) {
            Column {
                Row(Modifier.padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(item.title, Modifier.weight(1f), fontSize = 18.sp)
                    TextButton(onClick = onClose) { Text("Close") }
                }
                AndroidView(factory = {
                    mapView.apply {
                        getMapAsync { map ->
                            map.setStyle(item.url)
                            map.setMinZoomPreference(region.minZoom.toDouble())
                            map.setMaxZoomPreference(region.maxZoom.toDouble())
                            map.cameraPosition = CameraPosition.Builder()
                                .target(LatLng(region.centerLat, region.centerLon)).zoom(7.0).build()
                        }
                    }
                }, modifier = Modifier.fillMaxSize())
            }
        }
    }
}
