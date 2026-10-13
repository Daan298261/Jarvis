package com.jarvis.companion

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import org.maplibre.android.MapLibre
import org.maplibre.android.geometry.LatLng
import org.maplibre.android.geometry.LatLngBounds
import org.maplibre.android.offline.OfflineManager
import org.maplibre.android.offline.OfflineRegion
import org.maplibre.android.offline.OfflineRegionError
import org.maplibre.android.offline.OfflineRegionStatus
import org.maplibre.android.offline.OfflineTilePyramidRegionDefinition
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/** Maps MapLibre's region status onto the off-grid status model. Pure for tests. */
object OffGridMapStatus {
    fun of(complete: Boolean, active: Boolean, completed: Long, required: Long, error: String? = null): OffGridItemState {
        val pct = OffGridContentManager.progressOf(completed, required).coerceAtMost(if (complete) 100 else 99)
        return when {
            error != null -> OffGridItemState(OffGridStatus.ERROR, pct, error)
            complete -> OffGridItemState(OffGridStatus.READY, 100)
            active -> OffGridItemState(OffGridStatus.DOWNLOADING, pct)
            else -> OffGridItemState(OffGridStatus.MISSING, pct)
        }
    }
}

/** MapLibre offline tile-pyramid regions, keyed by catalog id stored as region metadata (main thread API). */
class MapLibreMapStore(context: Context) : OffGridMapStore {
    private val app = context.applicationContext
    private val manager: OfflineManager by lazy {
        MapLibre.getInstance(app)
        OfflineManager.getInstance(app).apply { setOfflineMapboxTileCountLimit(TILE_LIMIT) }
    }

    private suspend fun regions(): Map<String, OfflineRegion> = withContext(Dispatchers.Main) {
        suspendCancellableCoroutine { cont ->
            manager.listOfflineRegions(object : OfflineManager.ListOfflineRegionsCallback {
                override fun onList(offlineRegions: Array<OfflineRegion>?) {
                    cont.resume(offlineRegions.orEmpty().associateBy { String(it.metadata, Charsets.UTF_8) })
                }
                override fun onError(error: String) { cont.resumeWithException(IllegalStateException("Offline maps: $error")) }
            })
        }
    }

    private suspend fun status(region: OfflineRegion): OfflineRegionStatus = withContext(Dispatchers.Main) {
        suspendCancellableCoroutine { cont ->
            region.getStatus(object : OfflineRegion.OfflineRegionStatusCallback {
                override fun onStatus(status: OfflineRegionStatus) { cont.resume(status) }
                override fun onError(error: String) { cont.resumeWithException(IllegalStateException("Offline maps: $error")) }
            })
        }
    }

    override suspend fun states(items: List<OffGridItem>): Map<String, OffGridItemState> {
        val existing = regions()
        return items.associate { item ->
            val r = existing[item.id]
            item.id to if (r == null) OffGridItemState() else status(r).let {
                OffGridMapStatus.of(it.isComplete, false, it.completedResourceCount, it.requiredResourceCount)
            }
        }
    }

    private suspend fun create(item: OffGridItem): OfflineRegion = withContext(Dispatchers.Main) {
        val r = item.mapRegion!!
        val definition = OfflineTilePyramidRegionDefinition(
            item.url,
            LatLngBounds.Builder().include(LatLng(r.north, r.east)).include(LatLng(r.south, r.west)).build(),
            r.minZoom.toDouble(), r.maxZoom.toDouble(), app.resources.displayMetrics.density,
        )
        suspendCancellableCoroutine { cont ->
            manager.createOfflineRegion(definition, item.id.toByteArray(Charsets.UTF_8), object : OfflineManager.CreateOfflineRegionCallback {
                override fun onCreate(offlineRegion: OfflineRegion) { cont.resume(offlineRegion) }
                override fun onError(error: String) { cont.resumeWithException(IllegalStateException("Offline maps: $error")) }
            })
        }
    }

    override suspend fun download(item: OffGridItem, onState: (OffGridItemState) -> Unit) {
        val region = regions()[item.id] ?: create(item)
        withContext(Dispatchers.Main) {
            try {
                suspendCancellableCoroutine<Unit> { cont ->
                    region.setObserver(object : OfflineRegion.OfflineRegionObserver {
                        override fun onStatusChanged(status: OfflineRegionStatus) {
                            val s = OffGridMapStatus.of(status.isComplete, true, status.completedResourceCount, status.requiredResourceCount)
                            onState(s)
                            if (status.isComplete && cont.isActive) {
                                region.setDownloadState(OfflineRegion.STATE_INACTIVE)
                                cont.resume(Unit)
                            }
                        }
                        override fun onError(error: OfflineRegionError) {
                            // Connection errors are retried by MapLibre itself; surface others.
                            if (error.reason == OfflineRegionError.REASON_CONNECTION) return
                            region.setDownloadState(OfflineRegion.STATE_INACTIVE)
                            onState(OffGridItemState(OffGridStatus.ERROR, error = "Map download failed: ${error.message}. Tap Retry to resume."))
                            if (cont.isActive) cont.resume(Unit)
                        }
                        override fun mapboxTileCountLimitExceeded(limit: Long) {
                            region.setDownloadState(OfflineRegion.STATE_INACTIVE)
                            onState(OffGridItemState(OffGridStatus.ERROR, error = "This map region needs more than $limit tiles."))
                            if (cont.isActive) cont.resume(Unit)
                        }
                    })
                    region.setDownloadState(OfflineRegion.STATE_ACTIVE)
                    cont.invokeOnCancellation { region.setDownloadState(OfflineRegion.STATE_INACTIVE) }
                }
            } finally {
                region.setObserver(object : OfflineRegion.OfflineRegionObserver {
                    override fun onStatusChanged(status: OfflineRegionStatus) {}
                    override fun onError(error: OfflineRegionError) {}
                    override fun mapboxTileCountLimitExceeded(limit: Long) {}
                })
            }
        }
    }

    override suspend fun pause(item: OffGridItem) {
        regions()[item.id]?.let { withContext(Dispatchers.Main) { it.setDownloadState(OfflineRegion.STATE_INACTIVE) } }
    }

    override suspend fun delete(item: OffGridItem) {
        val region = regions()[item.id] ?: return
        withContext(Dispatchers.Main) {
            suspendCancellableCoroutine<Unit> { cont ->
                region.delete(object : OfflineRegion.OfflineRegionDeleteCallback {
                    override fun onDelete() { cont.resume(Unit) }
                    override fun onError(error: String) { cont.resumeWithException(IllegalStateException("Offline maps: $error")) }
                })
            }
        }
    }

    companion object {
        /** Netherlands z0-14 is ~50k tiles plus glyph/sprite resources. */
        const val TILE_LIMIT = 200_000L
    }
}
