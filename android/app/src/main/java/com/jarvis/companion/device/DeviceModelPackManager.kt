package com.jarvis.companion.device

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.util.concurrent.TimeUnit

class DeviceModelPackManager(
    context: Context,
    private val scope: CoroutineScope,
    private val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .build(),
) {
    private val appContext = context.applicationContext
    private val prefs = appContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    private val packDir = File(appContext.filesDir, "device-models").apply { mkdirs() }
    private val mutable = MutableStateFlow(DevicePackUiState())
    val state: StateFlow<DevicePackUiState> = mutable.asStateFlow()
    private var downloadJob: Job? = null

    init {
        refreshDiskState()
    }

    fun refreshDiskState() {
        val packId = prefs.getString(KEY_SELECTED_PACK, DeviceModelPackCatalog.defaultPack.id)
            ?: DeviceModelPackCatalog.defaultPack.id
        val descriptor = DeviceModelPackCatalog.find(packId) ?: DeviceModelPackCatalog.defaultPack
        val file = packFile(descriptor)
        val bytes = if (file.isFile) file.length() else 0L
        val current = mutable.value
        if (current.status == DevicePackStatus.DOWNLOADING) return
        val status = when {
            current.status == DevicePackStatus.RUNNING -> DevicePackStatus.RUNNING
            bytes > 0 && file.isFile -> DevicePackStatus.READY
            current.error != null -> DevicePackStatus.ERROR
            else -> DevicePackStatus.MISSING
        }
        mutable.value = DevicePackUiState(
            status = status,
            selectedPack = descriptor,
            bytesOnDisk = bytes,
            downloadProgress = null,
            error = if (status == DevicePackStatus.ERROR) current.error else null,
        )
    }

    fun selectPack(packId: String) {
        val descriptor = DeviceModelPackCatalog.find(packId) ?: return
        prefs.edit().putString(KEY_SELECTED_PACK, descriptor.id).apply()
        refreshDiskState()
    }

    fun downloadSelectedPack() {
        val descriptor = mutable.value.selectedPack
        if (downloadJob?.isActive == true) return
        downloadJob = scope.launch {
            mutable.value = mutable.value.copy(
                status = DevicePackStatus.DOWNLOADING,
                downloadProgress = 0f,
                error = null,
            )
            val target = packFile(descriptor)
            val partial = File(target.parentFile, "${target.name}.partial")
            try {
                withContext(Dispatchers.IO) {
                    partial.parentFile?.mkdirs()
                    val request = Request.Builder().url(descriptor.downloadUrl).get().build()
                    http.newCall(request).execute().use { response ->
                        if (!response.isSuccessful) error("Download failed (${response.code})")
                        val body = response.body ?: error("Empty download body")
                        val total = body.contentLength().takeIf { it > 0 } ?: descriptor.expectedBytes
                        body.byteStream().use { input ->
                            partial.outputStream().use { output ->
                                val buffer = ByteArray(65536)
                                var readTotal = 0L
                                while (true) {
                                    val count = input.read(buffer)
                                    if (count < 0) break
                                    output.write(buffer, 0, count)
                                    readTotal += count
                                    val progress = if (total > 0) (readTotal.toFloat() / total).coerceIn(0f, 1f) else null
                                    mutable.value = mutable.value.copy(downloadProgress = progress)
                                }
                            }
                        }
                    }
                    if (!partial.renameTo(target)) {
                        partial.copyTo(target, overwrite = true)
                        partial.delete()
                    }
                }
                mutable.value = DevicePackUiState(
                    status = DevicePackStatus.READY,
                    selectedPack = descriptor,
                    bytesOnDisk = target.length(),
                    downloadProgress = null,
                    error = null,
                )
            } catch (error: Exception) {
                partial.delete()
                mutable.value = mutable.value.copy(
                    status = DevicePackStatus.ERROR,
                    downloadProgress = null,
                    error = error.message ?: "Download failed",
                )
            }
        }
    }

    fun deleteSelectedPack() {
        downloadJob?.cancel()
        downloadJob = null
        DeviceModelInference.unload()
        val descriptor = mutable.value.selectedPack
        packFile(descriptor).delete()
        File(packDir, "${descriptor.filename}.partial").delete()
        mutable.value = DevicePackUiState(
            status = DevicePackStatus.MISSING,
            selectedPack = descriptor,
            bytesOnDisk = 0,
            downloadProgress = null,
            error = null,
        )
    }

    fun markRunning(running: Boolean) {
        val base = mutable.value
        if (running && base.status == DevicePackStatus.READY) {
            mutable.value = base.copy(status = DevicePackStatus.RUNNING)
        } else if (!running && base.status == DevicePackStatus.RUNNING) {
            mutable.value = base.copy(status = DevicePackStatus.READY)
        }
    }

    fun packPath(): File? {
        val file = packFile(mutable.value.selectedPack)
        return file.takeIf { it.isFile && it.length() > 0 }
    }

    private fun packFile(descriptor: DeviceModelPackDescriptor): File =
        File(packDir, descriptor.filename)

    companion object {
        private const val PREFS = "device_model_pack"
        private const val KEY_SELECTED_PACK = "selected_pack_id"
    }
}
