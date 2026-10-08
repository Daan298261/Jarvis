#pragma once

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
    std::vector<uint8_t> synthesize(const std::string &text);

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};
