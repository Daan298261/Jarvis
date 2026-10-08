#include "pocket_tts_engine.h"

#include "pocket_tts_tokenizer.h"

#include "onnxruntime_cxx_api.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <limits>
#include <random>
#include <stdexcept>
#include <utility>

namespace {

constexpr int kSampleRate = 24000;
constexpr int kFrameSamples = 1920;
constexpr int kLatent = 32;
constexpr int kFlowSteps = 4;
constexpr int kMaxFrames = 500;
constexpr int kFramesAfterEos = 3;
constexpr float kEosThreshold = -4.0f;
constexpr float kTemperature = 0.7f;
constexpr int kIntraThreads = 2;

bool file_nonempty(const std::string &path) {
    std::ifstream in(path, std::ios::binary | std::ios::ate);
    return static_cast<bool>(in) && in.tellg() > 0;
}

std::string join_path(const std::string &dir, const char *name) {
    if (dir.empty()) return name;
    if (dir.back() == '/' || dir.back() == '\\') return dir + name;
    return dir + "/" + name;
}

Ort::Value zeros_like_input(Ort::Session &session, size_t index, Ort::AllocatorWithDefaultOptions &allocator) {
    auto type_info = session.GetInputTypeInfo(index);
    auto tensor = type_info.GetTensorTypeAndShapeInfo();
    auto shape = tensor.GetShape();
    for (auto &d : shape) {
        if (d < 0) d = 1;
    }
    ONNXTensorElementDataType type = tensor.GetElementType();
    size_t count = 1;
    for (auto d : shape) count *= static_cast<size_t>(d);
    if (type == ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT) {
        auto value = Ort::Value::CreateTensor<float>(allocator, shape.data(), shape.size());
        std::fill_n(value.GetTensorMutableData<float>(), count, 0.0f);
        return value;
    }
    if (type == ONNX_TENSOR_ELEMENT_DATA_TYPE_INT64) {
        auto value = Ort::Value::CreateTensor<int64_t>(allocator, shape.data(), shape.size());
        std::fill_n(value.GetTensorMutableData<int64_t>(), count, 0);
        return value;
    }
    if (type == ONNX_TENSOR_ELEMENT_DATA_TYPE_BOOL) {
        auto value = Ort::Value::CreateTensor<bool>(allocator, shape.data(), shape.size());
        std::fill_n(value.GetTensorMutableData<bool>(), count, false);
        return value;
    }
    throw std::runtime_error("Pocket TTS state tensor type is unsupported");
}

std::vector<const char *> cstr(const std::vector<std::string> &names) {
    std::vector<const char *> out;
    out.reserve(names.size());
    for (const auto &n : names) out.push_back(n.c_str());
    return out;
}

void append_wav(std::vector<uint8_t> &out, const std::vector<float> &pcm) {
    const uint32_t data_bytes = static_cast<uint32_t>(pcm.size() * 2);
    const uint32_t riff_size = 36 + data_bytes;
    out.resize(44 + data_bytes);
    auto put32 = [&](size_t at, uint32_t v) {
        out[at] = static_cast<uint8_t>(v);
        out[at + 1] = static_cast<uint8_t>(v >> 8);
        out[at + 2] = static_cast<uint8_t>(v >> 16);
        out[at + 3] = static_cast<uint8_t>(v >> 24);
    };
    auto put16 = [&](size_t at, uint16_t v) {
        out[at] = static_cast<uint8_t>(v);
        out[at + 1] = static_cast<uint8_t>(v >> 8);
    };
    std::memcpy(out.data(), "RIFF", 4);
    put32(4, riff_size);
    std::memcpy(out.data() + 8, "WAVEfmt ", 8);
    put32(16, 16);
    put16(20, 1);
    put16(22, 1);
    put32(24, kSampleRate);
    put32(28, kSampleRate * 2);
    put16(32, 2);
    put16(34, 16);
    std::memcpy(out.data() + 36, "data", 4);
    put32(40, data_bytes);
    for (size_t i = 0; i < pcm.size(); ++i) {
        float s = std::max(-1.0f, std::min(1.0f, pcm[i]));
        int16_t v = static_cast<int16_t>(std::lrintf(s * 32767.0f));
        out[44 + i * 2] = static_cast<uint8_t>(v & 0xff);
        out[44 + i * 2 + 1] = static_cast<uint8_t>((v >> 8) & 0xff);
    }
}

bool near_silent_pcm16(const std::vector<uint8_t> &wav) {
    if (wav.size() < 44 + 2) return true;
    int64_t sum = 0;
    int samples = 0;
    for (size_t i = 44; i + 1 < wav.size(); i += 2) {
        int sample = (wav[i] | (wav[i + 1] << 8));
        int16_t signed_s = static_cast<int16_t>(sample);
        sum += signed_s < 0 ? -signed_s : signed_s;
        ++samples;
    }
    if (samples == 0) return true;
    return (sum / samples) < 8;
}

}  // namespace

class PocketTtsEngine::Impl {
public:
    explicit Impl(const std::string &dir)
        : env_(ORT_LOGGING_LEVEL_ERROR, "jarvis_pocket_tts"),
          session_opts_(Ort::SessionOptions()) {
        session_opts_.SetIntraOpNumThreads(kIntraThreads);
        session_opts_.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);

        const std::string lm_main = join_path(dir, "lm_main.int8.onnx");
        const std::string lm_flow = join_path(dir, "lm_flow.int8.onnx");
        const std::string decoder = join_path(dir, "decoder.int8.onnx");
        const std::string encoder = join_path(dir, "encoder.onnx");
        const std::string conditioner = join_path(dir, "text_conditioner.onnx");
        const std::string vocab = join_path(dir, "vocab.json");
        const std::string scores = join_path(dir, "token_scores.json");
        const std::string tokenizer_model = join_path(dir, "tokenizer.model");
        const std::string manifest = join_path(dir, "manifest.json");
        for (const auto &path : {lm_main, lm_flow, decoder, encoder, conditioner, vocab, scores,
                                 tokenizer_model, manifest}) {
            if (!file_nonempty(path)) throw std::runtime_error("Missing Pocket TTS pack file: " + path);
        }

        lm_main_ = std::make_unique<Ort::Session>(env_, lm_main.c_str(), session_opts_);
        lm_flow_ = std::make_unique<Ort::Session>(env_, lm_flow.c_str(), session_opts_);
        decoder_ = std::make_unique<Ort::Session>(env_, decoder.c_str(), session_opts_);
        encoder_ = std::make_unique<Ort::Session>(env_, encoder.c_str(), session_opts_);
        conditioner_ = std::make_unique<Ort::Session>(env_, conditioner.c_str(), session_opts_);

        fill_io(*lm_main_, lm_main_in_, lm_main_out_);
        fill_io(*lm_flow_, lm_flow_in_, lm_flow_out_);
        fill_io(*decoder_, decoder_in_, decoder_out_);
        fill_io(*encoder_, encoder_in_, encoder_out_);
        fill_io(*conditioner_, conditioner_in_, conditioner_out_);
        if (encoder_in_.size() != 1 || encoder_out_.size() != 1 || encoder_in_[0] != "audio" ||
            encoder_out_[0] != "latents") {
            throw std::runtime_error("Pocket TTS encoder graph has an incompatible I/O contract");
        }
        if (conditioner_in_.size() != 1 || conditioner_out_.size() != 1 ||
            conditioner_in_[0] != "token_ids" || conditioner_out_[0] != "embeddings") {
            throw std::runtime_error("Pocket TTS text conditioner graph has an incompatible I/O contract");
        }
        if (lm_flow_in_.size() != 4 || lm_flow_out_.size() != 1 || lm_flow_in_[0] != "c") {
            throw std::runtime_error("Pocket TTS flow graph has an incompatible I/O contract");
        }
        if (lm_main_in_.size() < 20 || lm_main_out_.size() < 20 || lm_main_in_[0] != "sequence") {
            throw std::runtime_error("Pocket TTS LM main graph has an incompatible I/O contract");
        }
        if (decoder_in_.size() < 20 || decoder_out_.size() < 20 || decoder_in_[0] != "latent") {
            throw std::runtime_error("Pocket TTS decoder graph has an incompatible I/O contract");
        }

        tokenizer_ = std::make_unique<PocketTtsTokenizer>(vocab, scores);
        voice_embedding_ = create_voice_embedding();
        auto voice_shape = voice_embedding_.GetTensorTypeAndShapeInfo().GetShape();
        if (voice_shape.size() != 3 || voice_shape[0] != 1 || voice_shape[2] != 1024) {
            throw std::runtime_error("Pocket TTS fixed voice embedding has an unexpected shape");
        }
        voice_tokens_ = static_cast<int>(voice_shape[1]);
        auto cache_info = lm_main_->GetInputTypeInfo(2).GetTensorTypeAndShapeInfo().GetShape();
        if (cache_info.size() != 5 || cache_info[2] <= 0) {
            throw std::runtime_error("Pocket TTS LM cache input has an unexpected shape");
        }
        lm_cache_length_ = static_cast<int>(cache_info[2]);
        encoder_.reset();
    }

    Ort::Value clone_f32(const Ort::Value &src) {
        auto info = src.GetTensorTypeAndShapeInfo();
        auto shape = info.GetShape();
        const size_t n = info.GetElementCount();
        auto dst = Ort::Value::CreateTensor<float>(allocator_, shape.data(), shape.size());
        std::memcpy(dst.GetTensorMutableData<float>(), src.GetTensorData<float>(), n * sizeof(float));
        return dst;
    }

    Ort::Value empty_seq_tensor() {
        auto mem = Ort::MemoryInfo::CreateCpu(OrtDeviceAllocator, OrtMemTypeDefault);
        std::vector<int64_t> shape{1, 0, kLatent};
        return Ort::Value::CreateTensor<float>(mem, empty_storage_, 0, shape.data(), shape.size());
    }

    Ort::Value empty_text_tensor() {
        auto mem = Ort::MemoryInfo::CreateCpu(OrtDeviceAllocator, OrtMemTypeDefault);
        std::vector<int64_t> shape{1, 0, 1024};
        return Ort::Value::CreateTensor<float>(mem, empty_storage_, 0, shape.data(), shape.size());
    }

    std::vector<uint8_t> synthesize(const std::string &text) {
        if (text.empty()) return {};
        const auto ids32 = tokenizer_->encode_ids(text);
        if (ids32.empty()) return {};
        const int remaining = lm_cache_length_ - voice_tokens_ - static_cast<int>(ids32.size());
        if (remaining <= 0) throw std::runtime_error("Pocket TTS text exceeds the LM cache");
        const int frame_limit = std::min(kMaxFrames, remaining);

        std::vector<int64_t> ids(ids32.begin(), ids32.end());
        std::vector<int64_t> token_shape{1, static_cast<int64_t>(ids.size())};
        auto mem = Ort::MemoryInfo::CreateCpu(OrtDeviceAllocator, OrtMemTypeDefault);
        Ort::Value token_tensor = Ort::Value::CreateTensor<int64_t>(
            mem, ids.data(), ids.size(), token_shape.data(), token_shape.size());
        auto cond_in = cstr(conditioner_in_);
        auto cond_out = cstr(conditioner_out_);
        auto cond_outputs = conditioner_->Run(
            Ort::RunOptions{nullptr}, cond_in.data(), &token_tensor, 1, cond_out.data(), cond_out.size());
        Ort::Value text_embedding = std::move(cond_outputs[0]);

        auto lm_state = initial_state(*lm_main_, 2);
        {
            auto empty_seq = empty_seq_tensor();
            auto voice = clone_f32(voice_embedding_);
            run_lm(std::move(empty_seq), std::move(voice), lm_state);
        }
        {
            auto empty_seq = empty_seq_tensor();
            run_lm(std::move(empty_seq), std::move(text_embedding), lm_state);
        }

        auto decoder_state = initial_state(*decoder_, 1);
        std::vector<float> current(kLatent, std::numeric_limits<float>::quiet_NaN());
        std::vector<float> noise(kLatent, 0.0f);
        std::mt19937 rng{std::random_device{}()};
        std::normal_distribution<float> dist(0.0f, std::sqrt(kTemperature));

        std::vector<float> pcm;
        pcm.reserve(static_cast<size_t>(frame_limit) * kFrameSamples);
        int eos_frame = -1;
        for (int frame = 0; frame < frame_limit; ++frame) {
            std::vector<int64_t> seq_shape{1, 1, kLatent};
            Ort::Value sequence = Ort::Value::CreateTensor<float>(
                mem, current.data(), current.size(), seq_shape.data(), seq_shape.size());
            auto empty_text = empty_text_tensor();
            auto lm_out = run_lm(std::move(sequence), std::move(empty_text), lm_state);
            const float eos = lm_out.second.GetTensorData<float>()[0];
            if (eos_frame < 0 && eos > kEosThreshold) eos_frame = frame;
            if (eos_frame >= 0 && frame >= eos_frame + kFramesAfterEos) break;

            for (float &n : noise) n = dist(rng);
            current = run_flow(lm_out.first, noise);
            std::vector<int64_t> latent_shape{1, 1, kLatent};
            Ort::Value latent = Ort::Value::CreateTensor<float>(
                mem, current.data(), current.size(), latent_shape.data(), latent_shape.size());
            Ort::Value audio = run_decoder(std::move(latent), decoder_state);
            auto count = audio.GetTensorTypeAndShapeInfo().GetElementCount();
            if (count != static_cast<size_t>(kFrameSamples)) {
                throw std::runtime_error("Pocket TTS decoder did not return one 1,920-sample frame");
            }
            const float *samples = audio.GetTensorData<float>();
            pcm.insert(pcm.end(), samples, samples + count);
        }
        if (pcm.empty()) return {};
        std::vector<uint8_t> wav;
        append_wav(wav, pcm);
        if (near_silent_pcm16(wav)) return {};
        return wav;
    }

private:
    struct State {
        std::vector<Ort::Value> values;
    };

    void fill_io(Ort::Session &session, std::vector<std::string> &inputs, std::vector<std::string> &outputs) {
        Ort::AllocatorWithDefaultOptions allocator;
        const size_t in_count = session.GetInputCount();
        const size_t out_count = session.GetOutputCount();
        inputs.clear();
        outputs.clear();
        for (size_t i = 0; i < in_count; ++i) {
            auto name = session.GetInputNameAllocated(i, allocator);
            inputs.emplace_back(name.get());
        }
        for (size_t i = 0; i < out_count; ++i) {
            auto name = session.GetOutputNameAllocated(i, allocator);
            outputs.emplace_back(name.get());
        }
    }

    State initial_state(Ort::Session &session, size_t first_state) {
        State state;
        const size_t count = session.GetInputCount();
        for (size_t i = first_state; i < count; ++i) {
            state.values.push_back(zeros_like_input(session, i, allocator_));
        }
        return state;
    }

    std::pair<Ort::Value, Ort::Value> run_lm(Ort::Value sequence, Ort::Value embedding, State &state) {
        std::vector<Ort::Value> inputs;
        inputs.reserve(2 + state.values.size());
        inputs.push_back(std::move(sequence));
        inputs.push_back(std::move(embedding));
        for (auto &v : state.values) inputs.push_back(std::move(v));
        auto in_names = cstr(lm_main_in_);
        auto out_names = cstr(lm_main_out_);
        auto outputs = lm_main_->Run(Ort::RunOptions{nullptr}, in_names.data(), inputs.data(),
                                     inputs.size(), out_names.data(), out_names.size());
        State next;
        next.values.reserve(outputs.size() - 2);
        for (size_t i = 2; i < outputs.size(); ++i) next.values.push_back(std::move(outputs[i]));
        state = std::move(next);
        return {std::move(outputs[0]), std::move(outputs[1])};
    }

    std::vector<float> run_flow(Ort::Value &conditioning, const std::vector<float> &noise) {
        std::vector<float> latent = noise;
        auto mem = Ort::MemoryInfo::CreateCpu(OrtDeviceAllocator, OrtMemTypeDefault);
        float start = 0.0f;
        float end = 0.0f;
        std::vector<int64_t> scalar{1, 1};
        std::vector<int64_t> latent_shape{1, kLatent};
        const float dt = 1.0f / static_cast<float>(kFlowSteps);
        auto in_names = cstr(lm_flow_in_);
        auto out_names = cstr(lm_flow_out_);
        for (int step = 0; step < kFlowSteps; ++step) {
            start = static_cast<float>(step) / static_cast<float>(kFlowSteps);
            end = start + dt;
            Ort::Value s_tensor = Ort::Value::CreateTensor<float>(mem, &start, 1, scalar.data(), scalar.size());
            Ort::Value t_tensor = Ort::Value::CreateTensor<float>(mem, &end, 1, scalar.data(), scalar.size());
            Ort::Value x_tensor = Ort::Value::CreateTensor<float>(
                mem, latent.data(), latent.size(), latent_shape.data(), latent_shape.size());
            std::vector<Ort::Value> feeds;
            feeds.push_back(clone_f32(conditioning));
            feeds.push_back(std::move(s_tensor));
            feeds.push_back(std::move(t_tensor));
            feeds.push_back(std::move(x_tensor));
            auto outputs = lm_flow_->Run(Ort::RunOptions{nullptr}, in_names.data(), feeds.data(),
                                         feeds.size(), out_names.data(), out_names.size());
            const float *direction = outputs[0].GetTensorData<float>();
            auto count = outputs[0].GetTensorTypeAndShapeInfo().GetElementCount();
            if (count != latent.size()) throw std::runtime_error("Pocket TTS flow graph returned an unexpected shape");
            for (size_t i = 0; i < latent.size(); ++i) latent[i] += direction[i] * dt;
        }
        return latent;
    }

    Ort::Value run_decoder(Ort::Value latent, State &state) {
        std::vector<Ort::Value> inputs;
        inputs.reserve(1 + state.values.size());
        inputs.push_back(std::move(latent));
        for (auto &v : state.values) inputs.push_back(std::move(v));
        auto in_names = cstr(decoder_in_);
        auto out_names = cstr(decoder_out_);
        auto outputs = decoder_->Run(Ort::RunOptions{nullptr}, in_names.data(), inputs.data(),
                                     inputs.size(), out_names.data(), out_names.size());
        State next;
        next.values.reserve(outputs.size() - 1);
        for (size_t i = 1; i < outputs.size(); ++i) next.values.push_back(std::move(outputs[i]));
        state = std::move(next);
        return std::move(outputs[0]);
    }

    Ort::Value create_voice_embedding() {
        auto mem = Ort::MemoryInfo::CreateCpu(OrtDeviceAllocator, OrtMemTypeDefault);
        float placeholder = 0.0f;
        std::vector<int64_t> shape{1, 1, 1};
        Ort::Value audio = Ort::Value::CreateTensor<float>(mem, &placeholder, 1, shape.data(), shape.size());
        auto in_names = cstr(encoder_in_);
        auto out_names = cstr(encoder_out_);
        auto outputs = encoder_->Run(Ort::RunOptions{nullptr}, in_names.data(), &audio, 1, out_names.data(),
                                     out_names.size());
        return std::move(outputs[0]);
    }

    Ort::Env env_;
    Ort::SessionOptions session_opts_;
    Ort::AllocatorWithDefaultOptions allocator_;
    std::unique_ptr<Ort::Session> lm_main_;
    std::unique_ptr<Ort::Session> lm_flow_;
    std::unique_ptr<Ort::Session> decoder_;
    std::unique_ptr<Ort::Session> encoder_;
    std::unique_ptr<Ort::Session> conditioner_;
    std::vector<std::string> lm_main_in_, lm_main_out_;
    std::vector<std::string> lm_flow_in_, lm_flow_out_;
    std::vector<std::string> decoder_in_, decoder_out_;
    std::vector<std::string> encoder_in_, encoder_out_;
    std::vector<std::string> conditioner_in_, conditioner_out_;
    std::unique_ptr<PocketTtsTokenizer> tokenizer_;
    Ort::Value voice_embedding_{nullptr};
    float empty_storage_[1] = {0.0f};
    int voice_tokens_ = 0;
    int lm_cache_length_ = 0;
};

PocketTtsEngine::PocketTtsEngine(const std::string &pack_directory)
    : impl_(std::make_unique<Impl>(pack_directory)) {}

PocketTtsEngine::~PocketTtsEngine() = default;

std::vector<uint8_t> PocketTtsEngine::synthesize(const std::string &text) {
    return impl_->synthesize(text);
}
