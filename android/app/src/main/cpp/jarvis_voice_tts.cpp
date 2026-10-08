#include <jni.h>
#include <android/log.h>
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

#if defined(JARVIS_VOICE_TTS_ORT)
    g_pocket.reset();
#endif
    g_pack_dir.clear();
    g_engine.clear();

    if (engine == "piper-onnx") {
        const std::string onnx = dir + "/en_US-lessac-medium.onnx";
        const std::string json = dir + "/en_US-lessac-medium.onnx.json";
        if (!file_nonempty(onnx) || !file_nonempty(json)) {
            return to_jstring(env, "Piper pack files missing — reinstall piper-en-lessac-medium");
        }
        g_pack_dir = dir;
        g_engine = engine;
        return to_jstring(env, "");
    }
    if (engine != "pocket-tts-onnx") {
        return to_jstring(env, "Unknown on-device TTS engine id");
    }

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
    std::lock_guard<std::mutex> lock(g_mutex);
    const std::string utterance = jstring_to_std(env, text);
    if (utterance.empty()) return nullptr;

#if defined(JARVIS_VOICE_TTS_ORT)
    if (g_engine == "pocket-tts-onnx") {
        if (!g_pocket) return nullptr;
        try {
            const std::vector<uint8_t> wav = g_pocket->synthesize(utterance);
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
    if (g_engine == "piper-onnx") {
        // Piper is a documented fallback pack, not the grid-down success path.
        LOGE("Piper synthesis is not the RFC-0204 grid-down voice; Pocket TTS is required");
        return nullptr;
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
#if defined(JARVIS_VOICE_TTS_ORT)
    g_pocket.reset();
#endif
}
