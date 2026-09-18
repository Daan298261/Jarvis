#include <jni.h>
#include <android/log.h>
#include <mutex>
#include <string>
#include <vector>

#include "llama.h"

#define LOG_TAG "jarvis_llama"
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

static std::mutex g_mutex;
static llama_model *g_model = nullptr;
static llama_context *g_ctx = nullptr;

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
Java_com_jarvis_companion_CompanionNativeBridge_nativeLoad(JNIEnv *env, jclass, jstring modelPath, jint contextTokens) {
    std::lock_guard<std::mutex> lock(g_mutex);
    const std::string path = jstring_to_std(env, modelPath);
    if (path.empty()) return to_jstring(env, "error:Model path is empty");

    if (g_ctx) {
        llama_free(g_ctx);
        g_ctx = nullptr;
    }
    if (g_model) {
        llama_model_free(g_model);
        g_model = nullptr;
    }

    llama_backend_init();
    llama_model_params mparams = llama_model_default_params();
    g_model = llama_model_load_from_file(path.c_str(), mparams);
    if (!g_model) {
        return to_jstring(env, "error:Could not load GGUF model");
    }

    llama_context_params cparams = llama_context_default_params();
    cparams.n_ctx = contextTokens > 0 ? contextTokens : 2048;
    cparams.n_threads = 4;
    cparams.n_threads_batch = 4;
    g_ctx = llama_init_from_model(g_model, cparams);
    if (!g_ctx) {
        llama_model_free(g_model);
        g_model = nullptr;
        return to_jstring(env, "error:Could not create llama context (insufficient RAM?)");
    }
    return to_jstring(env, "");
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_jarvis_companion_CompanionNativeBridge_nativeGenerate(JNIEnv *env, jclass, jstring prompt, jint maxTokens) {
    std::lock_guard<std::mutex> lock(g_mutex);
    if (!g_model || !g_ctx) {
        return to_jstring(env, "error:Model is not loaded");
    }
    const std::string user = jstring_to_std(env, prompt);
    if (user.empty()) return to_jstring(env, "error:Prompt is empty");

    const llama_vocab *vocab = llama_model_get_vocab(g_model);
    std::vector<llama_token> tokens;
    tokens.resize(user.size() + 8);
    const int n = llama_tokenize(vocab, user.c_str(), (int)user.size(), tokens.data(), (int)tokens.size(), true, true);
    if (n < 0) {
        return to_jstring(env, "error:Tokenization failed");
    }
    tokens.resize((size_t)n);

    llama_batch batch = llama_batch_get_one(tokens.data(), (int32_t)tokens.size());
    if (llama_decode(g_ctx, batch) != 0) {
        return to_jstring(env, "error:Decode failed");
    }

    std::string out;
    const int limit = maxTokens > 0 ? maxTokens : 256;
    llama_sampler *sampler = llama_sampler_chain_init(llama_sampler_chain_default_params());
    llama_sampler_chain_add(sampler, llama_sampler_init_temp(0.7f));
    llama_sampler_chain_add(sampler, llama_sampler_init_dist(0));

    for (int i = 0; i < limit; ++i) {
        const llama_token next = llama_sampler_sample(sampler, g_ctx, -1);
        if (llama_vocab_is_eog(vocab, next)) break;
        char piece[256];
        const int piece_len = llama_token_to_piece(vocab, next, piece, sizeof(piece), 0, true);
        if (piece_len > 0) out.append(piece, (size_t)piece_len);
        tokens = {next};
        batch = llama_batch_get_one(tokens.data(), 1);
        if (llama_decode(g_ctx, batch) != 0) break;
    }
    llama_sampler_free(sampler);
    return to_jstring(env, out);
}

extern "C" JNIEXPORT void JNICALL
Java_com_jarvis_companion_CompanionNativeBridge_nativeUnload(JNIEnv *, jclass) {
    std::lock_guard<std::mutex> lock(g_mutex);
    if (g_ctx) {
        llama_free(g_ctx);
        g_ctx = nullptr;
    }
    if (g_model) {
        llama_model_free(g_model);
        g_model = nullptr;
    }
    llama_backend_free();
}
