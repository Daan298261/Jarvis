#pragma once

#include <cstdint>
#include <string>
#include <vector>

// SentencePiece-compatible tokenizer for soniqo Pocket-TTS-100M-ONNX-INT8
// (vocab.json + token_scores.json). tokenizer.model is required on disk but
// the JSON tables are the runtime vocabulary, matching the published pack.
class PocketTtsTokenizer {
public:
    PocketTtsTokenizer(const std::string &vocab_json, const std::string &token_scores_json);
    std::vector<int32_t> encode_ids(const std::string &text) const;

private:
    struct TrieNode {
        int32_t token_id = -1;
        float score = 0.0f;
        int32_t next[256];
        TrieNode() {
            for (int i = 0; i < 256; ++i) next[i] = -1;
        }
    };

    void build_trie();
    int32_t add_node();

    std::vector<TrieNode> trie_;
    std::vector<std::string> id_to_token_;
    std::vector<int32_t> byte_token_id_;
    std::vector<float> byte_token_score_;
};
