#include <jni.h>
#include <android/log.h>
#include <algorithm>
#include <atomic>
#include <cstdint>
#include <mutex>
#include <string>
#include <vector>

#include "llama.h"

#define LOG_TAG "jarvis_llama"
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

static std::mutex g_mutex;
static llama_model *g_model = nullptr;
static llama_context *g_ctx = nullptr;
static std::string g_loaded_path;
static int g_loaded_context = 0;
static std::atomic<bool> g_llama_cancel{false};
static std::atomic<uint64_t> g_llama_epoch{0};

static std::string jstring_to_std(JNIEnv *env, jstring value) {
    if (!value) return {};
    jclass string_class = env->FindClass("java/lang/String");
    jmethodID get_bytes = env->GetMethodID(string_class, "getBytes", "(Ljava/lang/String;)[B");
    jstring encoding = env->NewStringUTF("UTF-8");
    auto bytes = (jbyteArray)env->CallObjectMethod(value, get_bytes, encoding);
    if (!bytes) return {};
    std::string out(env->GetArrayLength(bytes), '\0');
    env->GetByteArrayRegion(bytes, 0, out.size(), reinterpret_cast<jbyte *>(out.data()));
    env->DeleteLocalRef(bytes); env->DeleteLocalRef(encoding); env->DeleteLocalRef(string_class);
    return out;
}

static jstring to_jstring(JNIEnv *env, const std::string &value) {
    jclass string_class = env->FindClass("java/lang/String");
    jmethodID constructor = env->GetMethodID(string_class, "<init>", "([BLjava/lang/String;)V");
    jbyteArray bytes = env->NewByteArray(value.size());
    env->SetByteArrayRegion(bytes, 0, value.size(), reinterpret_cast<const jbyte *>(value.data()));
    jstring encoding = env->NewStringUTF("UTF-8");
    auto result = (jstring)env->NewObject(string_class, constructor, bytes, encoding);
    env->DeleteLocalRef(bytes); env->DeleteLocalRef(encoding); env->DeleteLocalRef(string_class);
    return result;
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_jarvis_companion_CompanionNativeBridge_nativeLoad(JNIEnv *env, jclass, jstring modelPath, jint contextTokens) {
    std::lock_guard<std::mutex> lock(g_mutex);
    g_llama_cancel.store(false);
    const std::string path = jstring_to_std(env, modelPath);
    if (path.empty()) return to_jstring(env, "error:Model path is empty");
    if (g_model && g_ctx && g_loaded_path == path && g_loaded_context == contextTokens) return to_jstring(env, "");

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
    mparams.load_mode = LLAMA_LOAD_MODE_MMAP;
    g_model = llama_model_load_from_file(path.c_str(), mparams);
    if (!g_model) {
        return to_jstring(env, "error:Could not load GGUF model");
    }

    llama_context_params cparams = llama_context_default_params();
    int n_ctx = contextTokens > 0 ? contextTokens : 2048;
    if (n_ctx < 2048) n_ctx = 2048;
    if (n_ctx > 4096) n_ctx = 4096;
    cparams.n_ctx = n_ctx;
    cparams.n_batch = 128;
    cparams.n_ubatch = 64;
    cparams.n_threads = 4;
    cparams.n_threads_batch = 4;
    g_ctx = llama_init_from_model(g_model, cparams);
    if (!g_ctx) {
        llama_model_free(g_model);
        g_model = nullptr;
        return to_jstring(env, "error:Could not create llama context (insufficient RAM?)");
    }
    g_loaded_path = path;
    g_loaded_context = contextTokens;
    return to_jstring(env, "");
}

extern "C" JNIEXPORT jint JNICALL
Java_com_jarvis_companion_CompanionNativeBridge_nativeTokenize(JNIEnv *env, jclass, jstring text) {
    std::lock_guard<std::mutex> lock(g_mutex);
    if (!g_model) return -1;
    const std::string user = jstring_to_std(env, text);
    if (user.empty()) return 0;
    const llama_vocab *vocab = llama_model_get_vocab(g_model);
    std::vector<llama_token> tokens(user.size() + 8);
    int n = llama_tokenize(vocab, user.c_str(), (int)user.size(), tokens.data(), (int)tokens.size(), true, true);
    if (n < 0) {
        tokens.resize((size_t)(-n));
        n = llama_tokenize(vocab, user.c_str(), (int)user.size(), tokens.data(), (int)tokens.size(), true, true);
    }
    return n < 0 ? -1 : n;
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_jarvis_companion_CompanionNativeBridge_nativeGenerate(JNIEnv *env, jclass, jstring prompt, jint maxTokens, jint batchSize, jobject listener) {
    const uint64_t epoch = g_llama_epoch.load(std::memory_order_acquire);
    std::lock_guard<std::mutex> lock(g_mutex);
    if (g_llama_epoch.load(std::memory_order_relaxed) != epoch) {
        return to_jstring(env, "error:cancelled");
    }
    g_llama_cancel.store(false, std::memory_order_relaxed);
    if (g_llama_epoch.load(std::memory_order_relaxed) != epoch ||
        g_llama_cancel.load(std::memory_order_relaxed)) {
        return to_jstring(env, "error:cancelled");
    }
    if (!g_model || !g_ctx) {
        return to_jstring(env, "error:Model is not loaded");
    }
    // llama.cpp >= 2025-06 replaced the KV-cache API with the memory API (also covers recurrent/hybrid models such as Qwen3.5).
    llama_memory_clear(llama_get_memory(g_ctx), true);
    std::string user = jstring_to_std(env, prompt);
    if (user.empty()) return to_jstring(env, "error:Prompt is empty");
    const char *tmpl = llama_model_chat_template(g_model, nullptr);
    if (!tmpl) return to_jstring(env, "error:Model has no supported chat template");
    const std::string content = user;
    llama_chat_message message = {"user", content.c_str()};
    int required = llama_chat_apply_template(tmpl, &message, 1, true, nullptr, 0);
    if (required <= 0) return to_jstring(env, "error:Unsupported model chat template");
    std::vector<char> formatted(required + 1);
    int written = llama_chat_apply_template(tmpl, &message, 1, true, formatted.data(), formatted.size());
    if (written <= 0 || written > required) return to_jstring(env, "error:Chat template failed");
    user.assign(formatted.data(), written);
    char architecture[128] = {};
    llama_model_meta_val_str(g_model, "general.architecture", architecture, sizeof(architecture));
    if (std::string(architecture).find("qwen3") == 0) user += "<think>\n\n</think>\n\n";
    jclass listener_class = env->GetObjectClass(listener);
    jmethodID callback = env->GetMethodID(listener_class, "onToken", "(Ljava/lang/String;)V");
    if (!callback) return to_jstring(env, "error:Missing token listener");

    const llama_vocab *vocab = llama_model_get_vocab(g_model);
    std::vector<llama_token> tokens;
    tokens.resize(user.size() + 8);
    int n = llama_tokenize(vocab, user.c_str(), (int)user.size(), tokens.data(), (int)tokens.size(), true, true);
    if (n < 0) {
        tokens.resize((size_t)(-n));
        n = llama_tokenize(vocab, user.c_str(), (int)user.size(), tokens.data(), (int)tokens.size(), true, true);
    }
    if (n < 0) {
        return to_jstring(env, "error:Tokenization failed");
    }
    tokens.resize((size_t)n);

    const int n_ctx = (int)llama_n_ctx(g_ctx);
    const int n_batch = batchSize > 0 ? std::min(batchSize, 128) : 128;
    if (n >= n_ctx) {
        return to_jstring(env, "error:Prompt exceeds context");
    }

    for (int offset = 0; offset < n; ) {
        if (g_llama_epoch.load(std::memory_order_relaxed) != epoch ||
            g_llama_cancel.load(std::memory_order_relaxed)) {
            return to_jstring(env, "error:cancelled");
        }
        const int take = std::min(n_batch, n - offset);
        llama_batch batch = llama_batch_get_one(tokens.data() + offset, take);
        if (llama_decode(g_ctx, batch) != 0) {
            return to_jstring(env, "error:Decode failed");
        }
        offset += take;
    }

    std::string out;
    const int limit = maxTokens > 0 ? maxTokens : 256;
    llama_sampler *sampler = llama_sampler_chain_init(llama_sampler_chain_default_params());
    llama_sampler_chain_add(sampler, llama_sampler_init_temp(0.7f));
    llama_sampler_chain_add(sampler, llama_sampler_init_dist(0));

    bool truncated = false;
    bool saw_eog = false;
    std::string pending_utf8;
    int n_past = n;
    for (int i = 0; i < limit; ++i) {
        if (g_llama_epoch.load(std::memory_order_relaxed) != epoch ||
            g_llama_cancel.load(std::memory_order_relaxed)) {
            llama_sampler_free(sampler);
            return to_jstring(env, "error:cancelled");
        }
        if (n_past + 1 >= n_ctx) {
            truncated = true;
            break;
        }
        const llama_token next = llama_sampler_sample(sampler, g_ctx, -1);
        if (llama_vocab_is_eog(vocab, next)) {
            saw_eog = true;
            break;
        }
        char piece[256];
        const int piece_len = llama_token_to_piece(vocab, next, piece, sizeof(piece), 0, true);
        if (piece_len > 0) {
            out.append(piece, (size_t)piece_len);
            pending_utf8.append(piece, (size_t)piece_len);
            size_t complete = 0;
            for (size_t pos = 0; pos < pending_utf8.size();) {
                unsigned char c = (unsigned char)pending_utf8[pos];
                size_t length = c < 0x80 ? 1 : (c < 0xe0 ? 2 : (c < 0xf0 ? 3 : 4));
                if (pos + length > pending_utf8.size()) break;
                pos += length;
                complete = pos;
            }
            if (complete) {
                jstring chunk = to_jstring(env, pending_utf8.substr(0, complete));
                env->CallVoidMethod(listener, callback, chunk);
                env->DeleteLocalRef(chunk);
                pending_utf8.erase(0, complete);
                if (env->ExceptionCheck()) { llama_sampler_free(sampler); return nullptr; }
            }
        }
        llama_token one = next;
        llama_batch batch = llama_batch_get_one(&one, 1);
        if (llama_decode(g_ctx, batch) != 0) {
            truncated = true;
            break;
        }
        n_past += 1;
    }
    llama_sampler_free(sampler);
    if (!saw_eog && !truncated) truncated = true;
    if (truncated) return to_jstring(env, std::string("truncated:") + out);
    return to_jstring(env, out);
}

extern "C" JNIEXPORT void JNICALL
Java_com_jarvis_companion_CompanionNativeBridge_nativeGenerateCancel(JNIEnv *, jclass) {
    g_llama_cancel.store(true);
    g_llama_epoch.fetch_add(1, std::memory_order_acq_rel);
}

extern "C" JNIEXPORT void JNICALL
Java_com_jarvis_companion_CompanionNativeBridge_nativeUnload(JNIEnv *, jclass) {
    std::lock_guard<std::mutex> lock(g_mutex);
    g_llama_cancel.store(false);
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
