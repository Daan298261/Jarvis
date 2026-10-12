package com.jarvis.companion

import android.os.Bundle
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/**
 * Manual device/emulator sign-off for the offline pack (RFC-0204): loads a real GGUF
 * through the shipped llama.cpp JNI runtime and generates a short reply.
 *
 *   adb push Qwen3.5-2B-heretic-Q4_K_M.gguf /data/local/tmp/
 *   adb shell "run-as com.jarvis.companion sh -c 'mkdir -p files/model-packs && \
 *     cp /data/local/tmp/Qwen3.5-2B-heretic-Q4_K_M.gguf files/model-packs/'"     # debug build
 *   adb shell am instrument -w -r -e class com.jarvis.companion.OnDeviceModelLoadTest \
 *     -e modelPath /data/user/0/com.jarvis.companion/files/model-packs/Qwen3.5-2B-heretic-Q4_K_M.gguf \
 *     com.jarvis.companion.test/androidx.test.runner.AndroidJUnitRunner
 *
 * Without -e modelPath it uses the app's own pack location (files/model-packs/<filename>),
 * i.e. where an in-app download lands. Skips (assumption) when no model is present,
 * so CI without weights is unaffected. Reports load time and tok/s as instrumentation status.
 */
@RunWith(AndroidJUnit4::class)
class OnDeviceModelLoadTest {
    @Test
    fun defaultPackLoadsAndGenerates() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val pack = CompanionPackCatalog.builtIn.first { it.recommended }
        val path = InstrumentationRegistry.getArguments().getString("modelPath")
            ?: File(File(context.filesDir, "model-packs"), pack.filename).absolutePath
        assumeTrue("model not present at $path", File(path).isFile)

        val engine = LlamaCppInferenceEngine()
        assertTrue("native runtime missing from APK", engine.isRuntimeAvailable())
        val loadStart = System.nanoTime()
        assertNull(engine.load(path, OfflinePromptPlanner.N_CTX_MIN))
        val loadMs = (System.nanoTime() - loadStart) / 1_000_000
        try {
            val reply = StringBuilder()
            val genStart = System.nanoTime()
            val outcome = engine.generate("user: Reply with one short friendly sentence.\nassistant:", 32) { reply.append(it) }
            val genSec = (System.nanoTime() - genStart) / 1e9
            assertNull(outcome.error)
            assertTrue("empty reply", reply.isNotBlank())
            // tokenize() includes the chat-template wrapper; subtract its fixed cost.
            val tokens = (engine.tokenize(reply.toString()) - engine.tokenize("")).coerceAtLeast(1)
            instrumentation.sendStatus(0, Bundle().apply {
                putString("model", File(path).name)
                putLong("load_ms", loadMs)
                putString("tokens_per_second", "%.2f".format(tokens / genSec))
                putString("reply", reply.toString().take(200))
            })
        } finally {
            engine.unload()
        }
    }
}
