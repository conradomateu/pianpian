// Pianpian's alignment adapter; upstream neural inference remains unchanged.
// CTC spans are acoustic estimates, not manually verified phonetic boundaries.
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <limits>
#include <locale>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace pianpian {
struct Word { std::string word; double start, end; };
struct Segment { double start, end; std::string text; std::vector<Word> words; };
struct Span { int id, first, last; };  // inclusive start, exclusive end, speech frames

inline bool meta(const std::string &s) {
    return s.size() >= 3 && s[0] == '<' && s[1] == '|';
}

// Viterbi CTC forced alignment against the model's own decoded token sequence.
// As in SenseVoice output_timestamp, query frames are excluded and blank-winner
// frames get log(blank)=0. A greedy emission instant alone has no end boundary.
inline std::vector<Span> ctc_align(const std::vector<float> &logits, int frames,
        int vocab_size, int query_frames, int blank, const std::vector<int> &ids) {
    if (frames < query_frames || query_frames < 0 || vocab_size <= 0 ||
            blank < 0 || blank >= vocab_size ||
            logits.size() != static_cast<size_t>(frames) * vocab_size)
        throw std::runtime_error("invalid CTC dimensions");
    if (ids.empty()) return {};
    const int T = frames - query_frames, S = 2 * static_cast<int>(ids.size()) + 1;
    int needed = static_cast<int>(ids.size());
    for (size_t i = 0; i < ids.size(); ++i) {
        if (ids[i] < 0 || ids[i] >= vocab_size || ids[i] == blank)
            throw std::runtime_error("invalid CTC target");
        if (i && ids[i] == ids[i - 1]) ++needed;
    }
    if (needed > T) throw std::runtime_error("CTC targets cannot fit speech frames");
    const double neg = -std::numeric_limits<double>::infinity();
    std::vector<double> prev(S, neg), next(S, neg);
    std::vector<uint8_t> back(static_cast<size_t>(T) * S, 0);
    prev[0] = 0;
    for (int t = 0; t < T; ++t) {
        const float *row = logits.data() + static_cast<size_t>(t + query_frames) * vocab_size;
        int winner = 0;
        for (int v = 0; v < vocab_size; ++v) {
            if (!std::isfinite(row[v])) throw std::runtime_error("non-finite CTC logits");
            if (row[v] > row[winner]) winner = v;
        }
        double sum = 0;
        for (int v = 0; v < vocab_size; ++v) sum += std::exp(static_cast<double>(row[v]) - row[winner]);
        const double norm = row[winner] + std::log(sum);
        for (int s = 0; s < S; ++s) {
            double best = prev[s]; uint8_t jump = 0;
            if (s > 0 && prev[s - 1] > best) { best = prev[s - 1]; jump = 1; }
            if (s > 1 && s % 2 && ids[s / 2] != ids[s / 2 - 1] && prev[s - 2] > best) {
                best = prev[s - 2]; jump = 2;
            }
            const int token = s % 2 ? ids[s / 2] : blank;
            const double emission = token == blank && winner == blank ? 0.0 : row[token] - norm;
            next[s] = best + emission;
            back[static_cast<size_t>(t) * S + s] = jump;
        }
        prev.swap(next);
    }
    int state = prev[S - 1] > prev[S - 2] ? S - 1 : S - 2;
    if (!std::isfinite(prev[state])) throw std::runtime_error("CTC alignment has no valid path");
    std::vector<Span> spans;
    for (int id : ids) spans.push_back({id, T, -1});
    for (int t = T - 1; t >= 0; --t) {
        if (state % 2) {
            Span &s = spans[state / 2];
            s.first = std::min(s.first, t); s.last = std::max(s.last, t + 1);
        }
        state -= back[static_cast<size_t>(t) * S + state];
    }
    for (const Span &s : spans)
        if (s.last <= s.first) throw std::runtime_error("CTC alignment missed a token");
    return spans;
}

inline std::string json_string(const std::string &s) {
    std::ostringstream out; out << '"';
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') out << '\\' << c;
        else if (c < 32) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << static_cast<int>(c) << std::dec;
        else out << c;
    }
    out << '"'; return out.str();
}

inline int byte_piece(const std::string &s) {
    if (s.size() != 6 || s.substr(0, 3) != "<0x" || s[5] != '>') return -1;
    auto hex = [](char c) { return c >= '0' && c <= '9' ? c - '0' :
        c >= 'A' && c <= 'F' ? c - 'A' + 10 : c >= 'a' && c <= 'f' ? c - 'a' + 10 : -1; };
    int a = hex(s[3]), b = hex(s[4]); return a < 0 || b < 0 ? -1 : a * 16 + b;
}

// Each byte retains its acoustic owner. Decode UTF-8 before creating words so
// fallback byte tokens never leak invalid UTF-8 into JSON or subtitle offsets.
inline Segment segment(const std::vector<Span> &spans, const std::vector<std::string> &vocab,
        double offset, double duration) {
    if (!std::isfinite(offset) || !std::isfinite(duration) || offset < 0 || duration < 0)
        throw std::runtime_error("invalid segment time");
    struct Byte { unsigned char value; double start, end; int owner; };
    std::vector<Byte> bytes;
    for (size_t i = 0; i < spans.size(); ++i) {
        const Span &s = spans[i];
        if (s.id < 0 || s.id >= static_cast<int>(vocab.size())) throw std::runtime_error("token outside vocabulary");
        std::string piece = vocab[s.id];
        if (meta(piece)) continue;
        double a = std::clamp(s.first * 0.06 - 0.03, 0.0, duration);
        double b = std::clamp(s.last * 0.06 - 0.03, 0.0, duration);
        if (b <= a) throw std::runtime_error("empty acoustic token interval");
        int raw = byte_piece(piece);
        if (raw >= 0) piece = std::string(1, static_cast<char>(raw));
        for (unsigned char c : piece) bytes.push_back({c, offset + a, offset + b, static_cast<int>(i)});
    }
    Segment result{offset, offset + duration, "", {}};
    bool boundary = true;
    int previous_owner = -1;
    uint32_t previous_cp = 0;
    auto latin = [](uint32_t c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9'); };
    for (size_t i = 0; i < bytes.size();) {
        const size_t begin = i; unsigned char lead = bytes[i].value;
        size_t count = lead < 0x80 ? 1 : lead >= 0xc2 && lead <= 0xdf ? 2 :
            lead >= 0xe0 && lead <= 0xef ? 3 : lead >= 0xf0 && lead <= 0xf4 ? 4 : 0;
        if (!count || i + count > bytes.size()) throw std::runtime_error("invalid UTF-8 token sequence");
        uint32_t cp = lead & (count == 1 ? 0x7f : count == 2 ? 0x1f : count == 3 ? 0x0f : 0x07);
        std::string character; double a = bytes[i].start, b = bytes[i].end;
        for (size_t j = 0; j < count; ++j) {
            const Byte &v = bytes[i + j];
            if (j) { if ((v.value & 0xc0) != 0x80) throw std::runtime_error("invalid UTF-8 continuation"); cp = (cp << 6) | (v.value & 0x3f); }
            character += static_cast<char>(v.value); a = std::min(a, v.start); b = std::max(b, v.end);
        }
        if ((count == 2 && cp < 0x80) || (count == 3 && cp < 0x800) || (count == 4 && cp < 0x10000) ||
                cp > 0x10ffff || (cp >= 0xd800 && cp <= 0xdfff)) throw std::runtime_error("invalid Unicode scalar");
        i += count;
        if (cp == 0x2581 || cp == ' ' || cp == '\t' || cp == '\n' || cp == '\r') { boundary = true; continue; }
        if (boundary && !result.text.empty()) result.text += ' ';
        result.text += character;
        const bool join = !boundary && !result.words.empty() &&
            (previous_owner == bytes[begin].owner || (latin(previous_cp) && latin(cp)));
        if (join) { result.words.back().word += character; result.words.back().end = b; }
        else result.words.push_back({character, a, b});
        previous_owner = bytes[begin].owner; previous_cp = cp; boundary = false;
    }
    // Adjacent words may share the same model token (mixed scripts/byte pieces).
    // They stay grouped above; no uniform timing interpolation is introduced.
    return result;
}

inline std::string json(const std::vector<Segment> &segments) {
    std::ostringstream out; out.imbue(std::locale::classic()); out << std::fixed << std::setprecision(6);
    out << "{\"timestamp_method\":\"sensevoice_ctc_viterbi_v1\",\"segments\":[";
    for (size_t i = 0; i < segments.size(); ++i) {
        if (i) out << ',';
        const auto &s = segments[i];
        out << "{\"start\":" << s.start << ",\"end\":" << s.end << ",\"text\":" << json_string(s.text) << ",\"words\":[";
        for (size_t j = 0; j < s.words.size(); ++j) {
            if (j) out << ',';
            const auto &w = s.words[j];
            out << "{\"word\":" << json_string(w.word) << ",\"start\":" << w.start << ",\"end\":" << w.end << '}';
        }
        out << "]}";
    }
    out << "]}\n"; return out.str();
}
}  // namespace pianpian
