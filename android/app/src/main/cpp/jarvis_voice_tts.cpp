#include <jni.h>
#include <android/log.h>
#include <atomic>
#include <cstdint>
#include <exception>
#include <fstream>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

#if defined(JARVIS_VOICE_TTS_ORT)
#include "pocket_tts_engine.h"
#endif

#define LOG_TAG "jarvis_voice_tts"
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

static std::mutex g_mutex;
static std::string g_pack_dir;
static std::string g_engine;
static std::atomic<bool> g_tts_cancel{false};
static std::atomic<uint64_t> g_tts_epoch{0};
#if defined(JARVIS_VOICE_TTS_ORT)
static std::unique_ptr<PocketTtsEngine> g_pocket;
#endif

static std::string jstring_to_std(JNIEnv *env, jstring value) {
    if (!value) return {};
    const char *chars = env->GetStringUTFChars(value, nullptr);
    std::string out(chars ? chars : "");
    if (chars) env->ReleaseStringUTFChars(value, chars);
    return out;
}

static jstring to_jstring(JNIEnv *env, const std::string &value) {
    return env->NewStringUTF(value.c_str());
}

static bool file_nonempty(const std::string &path) {
    std::ifstream in(path, std::ios::binary | std::ios::ate);
    if (!in) return false;
    return in.tellg() > 0;
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_jarvis_companion_VoiceNativeBridge_nativeTtsLoad(
    JNIEnv *env, jclass, jstring packDirectory, jstring engineId) {
    std::lock_guard<std::mutex> lock(g_mutex);
    const std::string dir = jstring_to_std(env, packDirectory);
    const std::string engine = jstring_to_std(env, engineId);
    if (dir.empty()) return to_jstring(env, "TTS pack directory is empty");
    if (engine != "pocket-tts-onnx") {
        return to_jstring(env, "Unknown on-device TTS engine id");
    }
    g_tts_cancel.store(false);

#if defined(JARVIS_VOICE_TTS_ORT)
    if (g_pocket && g_pack_dir == dir && g_engine == engine) {
        return to_jstring(env, "");
    }
    g_pocket.reset();
#endif
    g_pack_dir.clear();
    g_engine.clear();

    const std::string required[] = {
        dir + "/lm_main.int8.onnx",
        dir + "/lm_flow.int8.onnx",
        dir + "/decoder.int8.onnx",
        dir + "/encoder.onnx",
        dir + "/text_conditioner.onnx",
        dir + "/manifest.json",
        dir + "/vocab.json",
        dir + "/token_scores.json",
        dir + "/tokenizer.model",
    };
    for (const auto &path : required) {
        if (!file_nonempty(path)) {
            return to_jstring(env, "Pocket TTS pack files missing — reinstall pocket-tts-en");
        }
    }

#if defined(JARVIS_VOICE_TTS_ORT)
    try {
        g_pocket = std::make_unique<PocketTtsEngine>(dir);
    } catch (const std::exception &ex) {
        LOGE("Pocket TTS load failed: %s", ex.what());
        return to_jstring(env, std::string("Pocket TTS ONNX failed to load: ") + ex.what());
    }
    g_pack_dir = dir;
    g_engine = engine;
    return to_jstring(env, "");
#else
    return to_jstring(
        env,
        "On-device TTS ONNX runtime is not linked in this APK ABI yet — "
        "rebuild with JARVIS_BUILD_VOICE_NATIVE=ON (JARVIS_VOICE_TTS_ORT). Refusing silent/fake audio.");
#endif
}

extern "C" JNIEXPORT jbyteArray JNICALL
Java_com_jarvis_companion_VoiceNativeBridge_nativeTtsSynthesize(JNIEnv *env, jclass, jstring text) {
    const uint64_t epoch = g_tts_epoch.load(std::memory_order_acquire);
    std::lock_guard<std::mutex> lock(g_mutex);
    if (g_tts_epoch.load(std::memory_order_relaxed) != epoch) {
        return env->NewByteArray(0);
    }
    g_tts_cancel.store(false, std::memory_order_relaxed);
    if (g_tts_epoch.load(std::memory_order_relaxed) != epoch ||
        g_tts_cancel.load(std::memory_order_relaxed)) {
        return env->NewByteArray(0);
    }
    const std::string utterance = jstring_to_std(env, text);
    if (utterance.empty()) return nullptr;

#if defined(JARVIS_VOICE_TTS_ORT)
    if (g_engine == "pocket-tts-onnx") {
        if (!g_pocket) return nullptr;
        try {
            const std::vector<uint8_t> wav = g_pocket->synthesize(utterance, &g_tts_cancel);
            if (g_tts_epoch.load(std::memory_order_relaxed) != epoch ||
                g_tts_cancel.load(std::memory_order_relaxed)) {
                // Non-null empty array: cancelled, never a synth failure.
                return env->NewByteArray(0);
            }
            if (wav.size() <= 44) return nullptr;
            jbyteArray out = env->NewByteArray(static_cast<jsize>(wav.size()));
            if (!out) return nullptr;
            env->SetByteArrayRegion(out, 0, static_cast<jsize>(wav.size()),
                                    reinterpret_cast<const jbyte *>(wav.data()));
            return out;
        } catch (const std::exception &ex) {
            LOGE("Pocket TTS synthesize failed: %s", ex.what());
            return nullptr;
        }
    }
    return nullptr;
#else
    (void)g_engine;
    return nullptr;
#endif
}

extern "C" JNIEXPORT void JNICALL
Java_com_jarvis_companion_VoiceNativeBridge_nativeTtsUnload(JNIEnv *, jclass) {
    std::lock_guard<std::mutex> lock(g_mutex);
    g_pack_dir.clear();
    g_engine.clear();
    g_tts_cancel.store(false);
#if defined(JARVIS_VOICE_TTS_ORT)
    g_pocket.reset();
#endif
}

extern "C" JNIEXPORT void JNICALL
Java_com_jarvis_companion_VoiceNativeBridge_nativeTtsCancel(JNIEnv *, jclass) {
    g_tts_cancel.store(true);
    g_tts_epoch.fetch_add(1, std::memory_order_acq_rel);
}
