package com.jarvis.companion

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import com.k2fsa.sherpa.onnx.*
import java.io.File

@RunWith(AndroidJUnit4::class)
class LocalAssistantRuntimeTest {
    @Test fun verifiedQwenModelLoadsAndStreamsNativeTokens() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val file = File(context.filesDir, "model-packs/runtime-test.gguf")
        // Provision the pinned 0.6B file with adb run-as before this optional hardware test.
        assumeTrue("Provision the pinned 0.6B GGUF for live inference", file.isFile)
        assertEquals("405ecd904c83015cabaf2f30a8ecb52b5d71711752a78a363f7abad5fa1b5c97", defaultFileSha256(file))
        val engine = LlamaCppInferenceEngine()
        assertTrue(engine.isRuntimeAvailable())
        assertNull(engine.load(file.absolutePath, 2048))
        val tokens = mutableListOf<String>()
        try {
            val result = engine.generate("Reply with a short greeting.", 48) { tokens.add(it) }
            assertNull(result.error)
            assertFalse(result.cancelled)
            assertTrue("Native token callbacks must stream", tokens.size > 1)
            assertTrue(tokens.joinToString("").isNotBlank())
        } finally { engine.unload() }
    }

    @Test fun bundledWakeModelInitializesAndSilenceDoesNotActivate() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val spotter = KeywordSpotter(context.assets, KeywordSpotterConfig(
            featConfig = FeatureConfig(sampleRate = 16000, featureDim = 80),
            modelConfig = OnlineModelConfig(transducer = OnlineTransducerModelConfig(
                encoder = "wake/encoder.onnx", decoder = "wake/decoder.onnx", joiner = "wake/joiner.onnx"),
                tokens = "wake/tokens.txt", numThreads = 1, provider = "cpu", modelingUnit = "cjkchar"),
            keywordsFile = "wake/keywords.txt"))
        val stream = spotter.createStream()
        try {
            stream.acceptWaveform(FloatArray(16000), 16000)
            while (spotter.isReady(stream)) spotter.decode(stream)
            assertTrue(spotter.getResult(stream).keyword.isBlank())
        } finally { stream.release(); spotter.release() }
    }
}
