package com.jarvis.companion

import kotlin.math.PI
import kotlin.math.asinh
import kotlin.math.floor
import kotlin.math.tan

/**
 * RFC-0216 S2: pinned allowlist of off-grid content. Nothing here is downloaded until the owner picks it.
 *
 * - ZIM rows (Kiwix knowledge bases) are single immutable, dated files on download.kiwix.org with the
 *   SHA-256 Kiwix publishes next to each file (`<file>.sha256`) and the exact byte size.
 * - Map rows are MapLibre offline tile-pyramid regions (RFC option B, "region-download flow that estimates
 *   size before commit"): OpenFreeMap vector tiles, no API key, stored in MapLibre's app-private offline DB.
 *   A tile pyramid has no single file to hash, so map rows carry style URL + bounds + measured estimate.
 */
enum class OffGridCategory(val label: String) {
    MAPS("Offline maps"),
    WIKIPEDIA("Wikipedia"),
    MEDICAL("Medical"),
    SURVIVAL("Survival & preparedness"),
}

data class OffGridMapRegion(
    val west: Double, val south: Double, val east: Double, val north: Double,
    val minZoom: Int, val maxZoom: Int,
) {
    val centerLat: Double get() = (south + north) / 2
    val centerLon: Double get() = (west + east) / 2
}

data class OffGridItem(
    val id: String,
    val title: String,
    val category: OffGridCategory,
    /** Exact bytes for ZIMs; measured estimate for map regions. */
    val sizeBytes: Long,
    /** SHA-256 of the ZIM file; blank for map regions (tile pyramid). */
    val sha256: String,
    /** ZIM download URL, or MapLibre style URL for map regions. */
    val url: String,
    val version: String = "",
    val description: String = "",
    val mapRegion: OffGridMapRegion? = null,
) {
    val isMap: Boolean get() = mapRegion != null
    val fileName: String get() = url.substringAfterLast('/')
}

object OffGridContentCatalog {
    const val MAP_STYLE_URL = "https://tiles.openfreemap.org/styles/liberty"
    private const val KIWIX = "https://download.kiwix.org/zim"

    private fun zim(id: String, title: String, cat: OffGridCategory, path: String, size: Long, sha: String, desc: String) =
        OffGridItem(id, title, cat, size, sha, "$KIWIX/$path", version = Regex("\\d{4}-\\d{2}").find(path)?.value ?: "", description = desc)

    private fun map(id: String, title: String, region: OffGridMapRegion, estimate: Long) =
        OffGridItem(id, title, OffGridCategory.MAPS, estimate, "", MAP_STYLE_URL,
            description = "Street map, zoom ${region.minZoom}–${region.maxZoom} (OpenFreeMap / OpenStreetMap)", mapRegion = region)

    val builtIn: List<OffGridItem> = listOf(
        // Estimates: OpenFreeMap tiles sampled per zoom level (Oct 2026), gzip as stored by MapLibre.
        map("map-nl", "Netherlands map", OffGridMapRegion(3.31, 50.75, 7.23, 53.56, 0, 14), 1_200_000_000L),
        map("map-be", "Belgium map", OffGridMapRegion(2.54, 49.49, 6.41, 51.51, 0, 14), 600_000_000L),
        map("map-lu", "Luxembourg map", OffGridMapRegion(5.73, 49.44, 6.53, 50.19, 0, 14), 67_000_000L),
        zim("zim-wikipedia-en-100", "Wikipedia: top 100 articles (English)", OffGridCategory.WIKIPEDIA,
            "wikipedia/wikipedia_en_100_2026-08.zim", 333_429_922L,
            "2eb7fd115bfb8644a08a9482f01f52b507428b1b8a30129fead92f7b6715440b", "The 100 most-read articles, with images"),
        zim("zim-wikipedia-en-top-mini", "Wikipedia: top articles, compact (English)", OffGridCategory.WIKIPEDIA,
            "wikipedia/wikipedia_en_top_mini_2026-09.zim", 296_858_160L,
            "9e75b5f03b4ff61864772d811bd9715c9cdc27a429229abb779aaa3cc3aa8e05", "Most-read articles, intro sections only"),
        zim("zim-wikipedia-en-medicine", "Wikipedia: medicine (English, no images)", OffGridCategory.MEDICAL,
            "wikipedia/wikipedia_en_medicine_nopic_2026-10.zim", 1_047_708_415L,
            "718fadad40b3491be3fa8f95181a948e4d726f97a79a14e0ef1b90c6b2b03625", "All WikiProject Medicine articles"),
        zim("zim-wikem", "WikEM emergency medicine (no images)", OffGridCategory.MEDICAL,
            "other/wikem_en_all_nopic_2026-07.zim", 346_946_448L,
            "831c6cad5dac7c51fe3cc12d226d8bd411b3883c8c83643f2c167d12928f5dd5", "Emergency-medicine reference"),
        zim("zim-medicine-guides", "Medical guides (zimgit)", OffGridCategory.MEDICAL,
            "other/zimgit-medicine_en_2024-08.zim", 70_179_585L,
            "a86c31b93e9800aae2cd812ef18cbf9c087a7537784c62fbc259db7f9f9d18c0", "Field medicine and first-aid books"),
        zim("zim-post-disaster", "Post-disaster resources (zimgit)", OffGridCategory.SURVIVAL,
            "other/zimgit-post-disaster_en_2024-05.zim", 644_665_513L,
            "0ba9bb358b768b94eb0d7920752fe356bf097de514ee61843f3a4da6cce174f8", "Shelter, sanitation, power, rebuilding"),
        zim("zim-water", "Water purification (zimgit)", OffGridCategory.SURVIVAL,
            "other/zimgit-water_en_2024-08.zim", 20_924_451L,
            "392c7bc970a44fddd61dd17f6eabf1f4e21936f2d5c27c83093e1dc475cb56b6", "Finding, storing and treating water"),
        zim("zim-food-preparation", "Food preparation & preservation (zimgit)", OffGridCategory.SURVIVAL,
            "other/zimgit-food-preparation_en_2025-04.zim", 97_822_565L,
            "db92c6c9dac14ff30f1cbc15aa834a7c012c6e87d4ff0519f33a0902ab6e732b", "Cooking and preserving without power"),
        zim("zim-knots", "Knots (zimgit)", OffGridCategory.SURVIVAL,
            "other/zimgit-knots_en_2024-08.zim", 27_945_133L,
            "7c3120b19fc2dc190b5ebfee01af54150136643d7b9d29d7fa9a6ba29787a57b", "Illustrated knot guides"),
        zim("zim-survivors", "Survivor guides (survivors.com)", OffGridCategory.SURVIVAL,
            "other/survivors_en_all_maxi_2026-09.zim", 137_661_255L,
            "ff3921fa8faae22821f9abd9be8cbd151bfdeaf7144003f9d29e6c05be581f08", "Survival skills reference"),
        zim("zim-trueprepper", "TruePrepper preparedness guides", OffGridCategory.SURVIVAL,
            "other/trueprepper.com_en_all_2026-05.zim", 1_423_584_895L,
            "64ddae8ca29ca24db23fae403f12af510f3f3119e09933974e91c899b41be940", "Emergency preparedness articles"),
    )

    /** Throws on any row that cannot be downloaded and verified. Empty URL is a failure (RFC-0108/0140 rule). */
    fun validate(items: List<OffGridItem>, scheme: String = "https://") {
        require(items.map { it.id }.toSet().size == items.size) { "Duplicate off-grid ids" }
        items.forEach { item ->
            require(item.url.isNotBlank()) { "Off-grid item ${item.id} has empty url" }
            require(item.url.startsWith(scheme)) { "Off-grid item ${item.id} url is not HTTPS" }
            require(item.sizeBytes > 0) { "Off-grid item ${item.id} has no size" }
            if (item.isMap) {
                val r = item.mapRegion!!
                require(r.west < r.east && r.south < r.north && r.minZoom in 0..r.maxZoom && r.maxZoom <= 16) {
                    "Off-grid map ${item.id} has bad bounds/zoom"
                }
                require(OffGridMapMath.tileCount(r) <= OffGridMapMath.MAX_REGION_TILES) {
                    "Off-grid map ${item.id} needs ${OffGridMapMath.tileCount(r)} tiles (limit ${OffGridMapMath.MAX_REGION_TILES})"
                }
            } else {
                require(item.category != OffGridCategory.MAPS) { "ZIM ${item.id} filed under maps" }
                require(item.sha256.matches(Regex("[0-9a-f]{64}"))) { "Off-grid item ${item.id} missing real sha256" }
                require(item.url.endsWith(".zim")) { "Off-grid item ${item.id} is not a ZIM file" }
            }
        }
    }

    init { validate(builtIn) }
}

/**
 * Web-mercator tile math that enforces the per-region tile cap: [OffGridContentCatalog.validate] rejects
 * catalogue regions above [MAX_REGION_TILES], and MapLibreMapStore refuses to create one before download.
 */
object OffGridMapMath {
    /** MapLibre's offline tile-count limit is raised to this; regions above it are refused before download. */
    const val MAX_REGION_TILES = 200_000L

    private fun tileX(lon: Double, z: Int): Long = floor((lon + 180.0) / 360.0 * (1L shl z)).toLong().coerceIn(0, (1L shl z) - 1)
    private fun tileY(lat: Double, z: Int): Long {
        val r = Math.toRadians(lat.coerceIn(-85.0511, 85.0511))
        return floor((1.0 - asinh(tan(r)) / PI) / 2.0 * (1L shl z)).toLong().coerceIn(0, (1L shl z) - 1)
    }

    fun tileCount(region: OffGridMapRegion): Long = (region.minZoom..region.maxZoom).sumOf { z ->
        (tileX(region.east, z) - tileX(region.west, z) + 1) * (tileY(region.south, z) - tileY(region.north, z) + 1)
    }
}

/** What the picker shows and enforces before anything downloads. */
object OffGridSelection {
    /** RFC-0216 S2: combined selections above this need an explicit confirm listing every size. */
    const val LARGE_SELECTION_BYTES = 500L * 1000 * 1000
    const val STORAGE_MARGIN_BYTES = PackDownloadPlan.STORAGE_MARGIN_BYTES

    fun totalBytes(items: Collection<OffGridItem>): Long = items.sumOf { it.sizeBytes }

    fun needsLargeConfirm(items: Collection<OffGridItem>): Boolean = totalBytes(items) > LARGE_SELECTION_BYTES

    /** Null when there is room; otherwise owner-facing copy. [alreadyOnDisk] = resumable partial bytes. */
    fun storageBlockReason(freeBytes: Long, items: Collection<OffGridItem>, alreadyOnDisk: Long = 0L): String? {
        val need = (totalBytes(items) - alreadyOnDisk).coerceAtLeast(0L) + STORAGE_MARGIN_BYTES
        if (freeBytes >= need) return null
        return "Not enough storage: this selection needs about ${formatBytes(need)} free, the phone has ${formatBytes(freeBytes)}. Deselect something or free up space."
    }

    fun formatBytes(bytes: Long): String = when {
        bytes >= 1_000_000_000L -> "%.1f GB".format(bytes / 1_000_000_000.0)
        bytes >= 1_000_000L -> "%.0f MB".format(bytes / 1_000_000.0)
        else -> "%.0f KB".format(bytes / 1_000.0)
    }
}
