#pragma once

#include <atomic>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

// Streaming Pocket TTS for soniqo/Pocket-TTS-100M-ONNX-INT8 v1.0.0.
// Graphs: tokenizer JSON tables, text_conditioner, encoder (fixed Alba),
// lm_main, lm_flow (Euler), decoder → 24 kHz PCM16 WAV.
class PocketTtsEngine {
public:
    explicit PocketTtsEngine(const std::string &pack_directory);
    ~PocketTtsEngine();

    PocketTtsEngine(const PocketTtsEngine &) = delete;
    PocketTtsEngine &operator=(const PocketTtsEngine &) = delete;

    // PCM16 WAV with header. Empty on failure — never a silent success buffer.
    // [cancel] is checked once per decoder frame so Stop can abort without waiting
    // on the JNI mutex.
    std::vector<uint8_t> synthesize(const std::string &text, const std::atomic<bool> *cancel = nullptr);

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};
