#include "pocket_tts_tokenizer.h"

#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <type_traits>
#include <unordered_map>
#include <utility>

namespace {

constexpr float kNegInf = -1.0e30f;

std::string read_file(const std::string &path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("Cannot open " + path);
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

int hex_value(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

std::string utf8_from_codepoint(uint32_t cp) {
    std::string out;
    if (cp < 0x80) {
        out.push_back(static_cast<char>(cp));
    } else if (cp < 0x800) {
        out.push_back(static_cast<char>(0xC0 | (cp >> 6)));
        out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
    } else if (cp < 0x10000) {
        out.push_back(static_cast<char>(0xE0 | (cp >> 12)));
        out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
        out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
    } else {
        out.push_back(static_cast<char>(0xF0 | (cp >> 18)));
        out.push_back(static_cast<char>(0x80 | ((cp >> 12) & 0x3F)));
        out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
        out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
    }
    return out;
}

bool parse_json_string(const std::string &src, size_t &i, std::string &out) {
    if (i >= src.size() || src[i] != '"') return false;
    ++i;
    out.clear();
    while (i < src.size()) {
        char c = src[i++];
        if (c == '"') return true;
        if (c != '\\') {
            out.push_back(c);
            continue;
        }
        if (i >= src.size()) return false;
        char e = src[i++];
        switch (e) {
            case '"': out.push_back('"'); break;
            case '\\': out.push_back('\\'); break;
            case '/': out.push_back('/'); break;
            case 'b': out.push_back('\b'); break;
            case 'f': out.push_back('\f'); break;
            case 'n': out.push_back('\n'); break;
            case 'r': out.push_back('\r'); break;
            case 't': out.push_back('\t'); break;
            case 'u': {
                if (i + 4 > src.size()) return false;
                uint32_t cp = 0;
                for (int n = 0; n < 4; ++n) {
                    int h = hex_value(src[i++]);
                    if (h < 0) return false;
                    cp = (cp << 4) | static_cast<uint32_t>(h);
                }
                out += utf8_from_codepoint(cp);
                break;
            }
            default:
                out.push_back(e);
                break;
        }
    }
    return false;
}

void skip_ws(const std::string &src, size_t &i) {
    while (i < src.size() && std::isspace(static_cast<unsigned char>(src[i]))) ++i;
}

template <typename T>
std::unordered_map<std::string, T> parse_object_numbers(const std::string &src) {
    std::unordered_map<std::string, T> out;
    size_t i = 0;
    skip_ws(src, i);
    if (i >= src.size() || src[i] != '{') throw std::runtime_error("Tokenizer JSON is not an object");
    ++i;
    while (i < src.size()) {
        skip_ws(src, i);
        if (i < src.size() && src[i] == '}') break;
        std::string key;
        if (!parse_json_string(src, i, key)) throw std::runtime_error("Tokenizer JSON key is invalid");
        skip_ws(src, i);
        if (i >= src.size() || src[i] != ':') throw std::runtime_error("Tokenizer JSON missing colon");
        ++i;
        skip_ws(src, i);
        size_t start = i;
        if (i < src.size() && (src[i] == '-' || src[i] == '+')) ++i;
        while (i < src.size() && (std::isdigit(static_cast<unsigned char>(src[i])) || src[i] == '.' ||
                                  src[i] == 'e' || src[i] == 'E' || src[i] == '+' || src[i] == '-')) {
            ++i;
        }
        if (start == i) throw std::runtime_error("Tokenizer JSON number is invalid");
        const std::string num = src.substr(start, i - start);
        if constexpr (std::is_same<T, float>::value) {
            out.emplace(key, std::strtof(num.c_str(), nullptr));
        } else {
            out.emplace(key, static_cast<T>(std::strtol(num.c_str(), nullptr, 10)));
        }
        skip_ws(src, i);
        if (i < src.size() && src[i] == ',') {
            ++i;
            continue;
        }
        if (i < src.size() && src[i] == '}') break;
    }
    return out;
}

}  // namespace

PocketTtsTokenizer::PocketTtsTokenizer(const std::string &vocab_json, const std::string &token_scores_json)
    : byte_token_id_(256, -1), byte_token_score_(256, kNegInf) {
    const auto vocabulary = parse_object_numbers<int32_t>(read_file(vocab_json));
    const auto scores = parse_object_numbers<float>(read_file(token_scores_json));
    if (vocabulary.empty() || vocabulary.size() != scores.size()) {
        throw std::runtime_error("Pocket TTS vocabulary and score table sizes differ");
    }
    id_to_token_.assign(vocabulary.size(), {});
    for (const auto &item : vocabulary) {
        if (item.second < 0 || static_cast<size_t>(item.second) >= id_to_token_.size()) {
            throw std::runtime_error("Pocket TTS vocabulary contains an out-of-range token ID");
        }
        id_to_token_[static_cast<size_t>(item.second)] = item.first;
    }
    trie_.clear();
    add_node();
    for (const auto &item : vocabulary) {
        auto score = scores.find(item.first);
        if (score == scores.end()) {
            throw std::runtime_error("Pocket TTS token is missing its score");
        }
        int32_t node = 0;
        for (unsigned char byte : item.first) {
            if (trie_[static_cast<size_t>(node)].next[byte] < 0) {
                trie_[static_cast<size_t>(node)].next[byte] = add_node();
            }
            node = trie_[static_cast<size_t>(node)].next[byte];
        }
        trie_[static_cast<size_t>(node)].token_id = item.second;
        trie_[static_cast<size_t>(node)].score = score->second;
    }
    for (int byte = 0; byte < 256; ++byte) {
        char name[8];
        std::snprintf(name, sizeof(name), "<0x%02X>", byte);
        auto id = vocabulary.find(name);
        auto score = scores.find(name);
        if (id != vocabulary.end() && score != scores.end()) {
            byte_token_id_[static_cast<size_t>(byte)] = id->second;
            byte_token_score_[static_cast<size_t>(byte)] = score->second;
        }
    }
}

int32_t PocketTtsTokenizer::add_node() {
    trie_.emplace_back();
    return static_cast<int32_t>(trie_.size() - 1);
}

std::vector<int32_t> PocketTtsTokenizer::encode_ids(const std::string &input) const {
    std::string text;
    text.reserve(input.size() + 8);
    for (char character : input) {
        if (character == ' ') {
            text.append("\xE2\x96\x81");
        } else {
            text.push_back(character);
        }
    }
    if (text.rfind("\xE2\x96\x81", 0) != 0) {
        text.insert(0, "\xE2\x96\x81");
    }
    const int32_t length = static_cast<int32_t>(text.size());
    std::vector<float> best(static_cast<size_t>(length + 1), kNegInf);
    std::vector<int32_t> back(static_cast<size_t>(length + 1), -1);
    std::vector<int32_t> back_id(static_cast<size_t>(length + 1), -1);
    best[static_cast<size_t>(length)] = 0.0f;

    for (int32_t start = length - 1; start >= 0; --start) {
        int32_t node = 0;
        for (int32_t end = start; end < length; ++end) {
            const auto byte = static_cast<unsigned char>(text[static_cast<size_t>(end)]);
            const int32_t next = trie_[static_cast<size_t>(node)].next[byte];
            if (next < 0) break;
            node = next;
            const auto &candidate = trie_[static_cast<size_t>(node)];
            if (candidate.token_id >= 0) {
                const float score = candidate.score + best[static_cast<size_t>(end + 1)];
                if (score > best[static_cast<size_t>(start)]) {
                    best[static_cast<size_t>(start)] = score;
                    back[static_cast<size_t>(start)] = end + 1;
                    back_id[static_cast<size_t>(start)] = candidate.token_id;
                }
            }
        }
        if (back[static_cast<size_t>(start)] < 0) {
            const auto byte = static_cast<unsigned char>(text[static_cast<size_t>(start)]);
            const auto fallback_id = byte_token_id_[byte];
            if (fallback_id >= 0) {
                best[static_cast<size_t>(start)] =
                    byte_token_score_[byte] + best[static_cast<size_t>(start + 1)];
                back_id[static_cast<size_t>(start)] = fallback_id;
            }
            back[static_cast<size_t>(start)] = start + 1;
        }
    }

    std::vector<int32_t> ids;
    for (int32_t offset = 0; offset < length;) {
        const auto next = back[static_cast<size_t>(offset)];
        const auto id = back_id[static_cast<size_t>(offset)];
        if (next <= offset || id < 0) {
            throw std::runtime_error("Pocket TTS tokenizer could not reconstruct its best path");
        }
        ids.push_back(id);
        offset = next;
    }
    return ids;
}
