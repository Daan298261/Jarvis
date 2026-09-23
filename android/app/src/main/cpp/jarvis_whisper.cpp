#include <jni.h>
#include <android/log.h>
#include <mutex>
#include <string>
#include <vector>

#include "whisper.h"

#define LOG_TAG "jarvis_whisper"
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

static std::mutex g_mutex;
static struct whisper_context *g_ctx = nullptr;

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

extern "C" JNIEXPORT jstring JNICALL
Java_com_jarvis_companion_VoiceNativeBridge_nativeWhisperLoad(JNIEnv *env, jclass, jstring modelPath) {
    std::lock_guard<std::mutex> lock(g_mutex);
    const std::string path = jstring_to_std(env, modelPath);
    if (path.empty()) return to_jstring(env, "Model path is empty");

    if (g_ctx) {
        whisper_free(g_ctx);
        g_ctx = nullptr;
    }

    whisper_context_params cparams = whisper_context_default_params();
    g_ctx = whisper_init_from_file_with_params(path.c_str(), cparams);
    if (!g_ctx) {
        return to_jstring(env, "Could not load whisper model (ABI/storage/RAM?)");
    }
    return to_jstring(env, "");
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_jarvis_companion_VoiceNativeBridge_nativeWhisperTranscribe(
    JNIEnv *env, jclass, jbyteArray pcm16le, jint sampleRate) {
    std::lock_guard<std::mutex> lock(g_mutex);
    if (!g_ctx) return to_jstring(env, "error:Whisper model is not loaded");
    if (!pcm16le) return to_jstring(env, "error:Empty PCM buffer");

    const jsize nbytes = env->GetArrayLength(pcm16le);
    if (nbytes < 2) return to_jstring(env, "error:PCM buffer too short");

    jbyte *bytes = env->GetByteArrayElements(pcm16le, nullptr);
    if (!bytes) return to_jstring(env, "error:Could not read PCM buffer");

    const size_t n_samples = (size_t)nbytes / 2;
    std::vector<float> pcm(n_samples);
    for (size_t i = 0; i < n_samples; ++i) {
        const int16_t sample = (int16_t)((uint8_t)bytes[2 * i] | ((uint8_t)bytes[2 * i + 1] << 8));
        pcm[i] = sample / 32768.0f;
    }
    env->ReleaseByteArrayElements(pcm16le, bytes, JNI_ABORT);

    if (sampleRate != WHISPER_SAMPLE_RATE) {
        // Product path captures 16 kHz PCM; refuse silent resample soft-fail.
        return to_jstring(env, "error:On-device STT requires 16 kHz PCM16LE");
    }

    whisper_full_params wparams = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
    wparams.print_progress = false;
    wparams.print_special = false;
    wparams.print_realtime = false;
    wparams.print_timestamps = false;
    wparams.single_segment = true;
    wparams.max_tokens = 256;
    wparams.language = "en";

    if (whisper_full(g_ctx, wparams, pcm.data(), (int)pcm.size()) != 0) {
        return to_jstring(env, "error:whisper_full failed");
    }

    std::string text;
    const int n_segments = whisper_full_n_segments(g_ctx);
    for (int i = 0; i < n_segments; ++i) {
        const char *seg = whisper_full_get_segment_text(g_ctx, i);
        if (seg) text += seg;
    }
    if (text.empty()) return to_jstring(env, "error:On-device STT produced no text");
    return to_jstring(env, text);
}

extern "C" JNIEXPORT void JNICALL
Java_com_jarvis_companion_VoiceNativeBridge_nativeWhisperUnload(JNIEnv *, jclass) {
    std::lock_guard<std::mutex> lock(g_mutex);
    if (g_ctx) {
        whisper_free(g_ctx);
        g_ctx = nullptr;
    }
}
