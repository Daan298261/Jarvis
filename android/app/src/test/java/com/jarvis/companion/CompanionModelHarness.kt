package com.jarvis.companion

import android.app.Application
import android.content.Context
import android.os.Looper
import androidx.test.core.app.ApplicationProvider
import org.junit.After
import org.junit.Before
import org.robolectric.Shadows.shadowOf
import org.robolectric.shadows.ShadowStatFs
import kotlinx.coroutines.sync.Mutex
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okio.Buffer
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

/**
 * Builds the real [CompanionModel] (on [FakeAndroidKeyStore]) around a scripted engine, so tests go through
 * `sendOffgrid`/`send`, the real `sendLock` and `downloadModelPack` instead of stand-ins.
 */
abstract class CompanionModelHarness {
    /** One engine whose next pass is chosen per test. */
    class ModeEngine : ScriptedInferenceEngine("") {
        @Volatile var mode = "ok"
        @Volatile var cancelRequests = 0
        @Volatile var released = false
        @Volatile var loadDelayMs = 0L
        override fun requestCancel() { cancelRequests++; cancelled = true }
        override fun load(modelPath: String, contextTokens: Int): String? {
            val until = System.currentTimeMillis() + loadDelayMs
            while (!cancelled && System.currentTimeMillis() < until) Thread.sleep(5)
            return super.load(modelPath, contextTokens)
        }
        override fun generate(prompt: String, maxTokens: Int, onToken: (String) -> Unit): GenerateOutcome {
            cancelled = false
            generateCalls++
            when (mode) {
                "ok" -> { onToken("Hello "); onToken("from this phone."); return GenerateOutcome() }
                "error" -> { onToken("Half an answer"); return GenerateOutcome(error = "model crashed mid-answer") }
                "hold" -> {
                    // Quiet until the test releases it (no token, so the first-token budget applies).
                    val until = System.currentTimeMillis() + 15_000
                    while (!released && !cancelled && System.currentTimeMillis() < until) Thread.sleep(5)
                    if (cancelled) return GenerateOutcome(cancelled = true)
                    onToken("Done."); return GenerateOutcome()
                }
                else -> { // "hang": a partial, then silence until asked to stop
                    onToken("Half an answer")
                    val until = System.currentTimeMillis() + 15_000
                    while (!cancelled && System.currentTimeMillis() < until) Thread.sleep(5)
                    return GenerateOutcome(cancelled = true)
                }
            }
        }
    }

    val server = MockWebServer()
    val bytes = ByteArray(96 * 1024) { (it % 251).toByte() }
    val fastId = CompanionPackCatalog.ABLITERATED_06B_ID
    val sha: String = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

    /** Points the fast 0.6B model's catalog row at the mock server (a throttled body keeps it visibly in flight). */
    fun pinFastModel(hash: String = sha, throttleMs: Long = 0) {
        server.enqueue(MockResponse().setBody(Buffer().write(bytes)).apply { if (throttleMs > 0) throttleBody(8 * 1024, throttleMs, TimeUnit.MILLISECONDS) })
        model.packManager.updateCatalog(JSONObject().put("packs", JSONArray().put(JSONObject()
            .put("id", fastId).put("label", "Fast test model").put("filename", "fast.gguf")
            .put("size_bytes", bytes.size).put("min_ram_mb", 1).put("sha256", hash)
            .put("url", server.url("/fast").toString()))))
    }

    val engine = ModeEngine()
    lateinit var context: Application
    lateinit var model: CompanionModel
    open val deadlines = LocalStallDeadlines(firstTokenMs = 5_000, idleMs = 300)

    @Before fun buildModel() {
        server.start()
        context = ApplicationProvider.getApplicationContext()
        listOf("companion_pack", "companion_pack_digest", "companion_ui", "phone_tools").forEach {
            context.getSharedPreferences(it, Context.MODE_PRIVATE).edit().clear().commit()
        }
        File(context.filesDir, "model-packs").deleteRecursively()
        CompanionModel.packManagerFactory = { app ->
            CompanionPackManager(app, engine, stallDeadlines = deadlines).also { manager ->
                val pack = CompanionPackCatalog.builtIn.first()
                manager.selectPack(pack.id)
                val file = manager.packFile(pack).apply { parentFile?.mkdirs(); writeBytes("gguf-fixture".toByteArray()) }
                // The fixture stands in for the pinned weights: record its digest as verified.
                manager.digestCache.remember(file, pack.sha256)
                ShadowStatFs.registerStats(manager.packRoot(), 1_000_000, 1_000_000, 1_000_000)
            }
        }
        model = CompanionModel(context)
        pump { model.state.value.localPackStatus == CompanionPackStatus.READY }
    }

    @After fun restoreFactory() {
        server.shutdown()
        CompanionModel.packManagerFactory = { CompanionPackManager(it) }
    }

    /** Runs the main looper (viewModelScope) until [done] holds. */
    fun pump(timeoutMs: Long = 20_000, done: () -> Boolean) {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (true) {
            // Robolectric's main looper runs on a fake clock: advance it so delayed work (the 1 s ticker) runs.
            shadowOf(Looper.getMainLooper()).idleFor(java.time.Duration.ofMillis(10))
            if (done()) return
            check(System.currentTimeMillis() < deadline) { "timed out; state=${model.state.value}" }
            Thread.sleep(10)
        }
    }

    fun settle(ms: Long) {
        val until = System.currentTimeMillis() + ms
        while (System.currentTimeMillis() < until) { shadowOf(Looper.getMainLooper()).idleFor(java.time.Duration.ofMillis(10)); Thread.sleep(10) }
    }

    fun sendLock(): Mutex = CompanionModel::class.java.getDeclaredField("sendLock")
        .apply { isAccessible = true }.get(model) as Mutex

    fun texts() = model.state.value.messages.map { it.optString("text") }
    fun assistantTexts() = model.state.value.messages.filter { it.optString("role") == "assistant" }.map { it.optString("text") }
}
