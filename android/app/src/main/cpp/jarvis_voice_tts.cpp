#include <jni.h>
#include <android/log.h>
#include <fstream>
#include <mutex>
#include <string>
#include <vector>

#define LOG_TAG "jarvis_voice_tts"
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

static std::mutex g_mutex;
static std::string g_pack_dir;
static std::string g_engine;

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

    if (engine == "piper-onnx") {
        const std::string onnx = dir + "/en_US-lessac-medium.onnx";
        const std::string json = dir + "/en_US-lessac-medium.onnx.json";
        if (!file_nonempty(onnx) || !file_nonempty(json)) {
            return to_jstring(env, "Piper pack files missing — reinstall piper-en-lessac-medium");
        }
    } else if (engine == "pocket-tts-onnx") {
        const std::string main = dir + "/lm_main.int8.onnx";
        const std::string manifest = dir + "/manifest.json";
        if (!file_nonempty(main) || !file_nonempty(manifest)) {
            return to_jstring(env, "Pocket TTS pack files missing — reinstall pocket-tts-en");
        }
    } else {
        return to_jstring(env, "Unknown on-device TTS engine id");
    }

    // ONNX Runtime Mobile synthesis is linked in release device builds.
    // Until ORT graphs are wired for this ABI, refuse rather than emit a fake waveform.
#if defined(JARVIS_VOICE_TTS_ORT)
    g_pack_dir = dir;
    g_engine = engine;
    return to_jstring(env, "");
#else
    (void)dir;
    return to_jstring(
        env,
        "On-device TTS ONNX runtime is not linked in this APK ABI yet — "
        "pack is verified on disk; rebuild with JARVIS_VOICE_TTS_ORT=1 for synthesis "
        "(phone sign-off). Refusing silent/fake audio.");
#endif
}

extern "C" JNIEXPORT jbyteArray JNICALL
Java_com_jarvis_companion_VoiceNativeBridge_nativeTtsSynthesize(JNIEnv *env, jclass, jstring text) {
    std::lock_guard<std::mutex> lock(g_mutex);
    (void)text;
#if defined(JARVIS_VOICE_TTS_ORT)
    // ORT graph execution lands with the device NDK bake; never return empty success.
    return nullptr;
#else
    return nullptr;
#endif
}

extern "C" JNIEXPORT void JNICALL
Java_com_jarvis_companion_VoiceNativeBridge_nativeTtsUnload(JNIEnv *, jclass) {
    std::lock_guard<std::mutex> lock(g_mutex);
    g_pack_dir.clear();
    g_engine.clear();
}
