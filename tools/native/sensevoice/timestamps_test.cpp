#include "timestamps.h"
#include <iostream>

static void check(bool value) { if (!value) throw std::runtime_error("timestamp test failed"); }
static std::vector<float> logits(std::vector<int> ids, int vocab = 4) {
    std::vector<float> result(ids.size() * vocab, -8);
    for (size_t i = 0; i < ids.size(); ++i) result[i * vocab + ids[i]] = 8;
    return result;
}
int main() {
    using namespace pianpian;
    // Four query frames cannot shift the acoustic times. Repeated labels need a blank.
    auto spans = ctc_align(logits({3,3,3,3,1,1,0,1,1,0}), 10, 4, 4, 0, {1,1});
    check(spans.size() == 2 && spans[0].first == 0 && spans[0].last == 2);
    check(spans[1].first == 3 && spans[1].last == 5);
    check(ctc_align(logits({0,0}), 2, 4, 0, 0, {}).empty());
    bool rejected = false;
    try { ctc_align(logits({1,1}), 2, 4, 0, 0, {1,1}); } catch (const std::runtime_error &) { rejected = true; }
    check(rejected);
    auto out = segment(spans, {"", "你", "好", "<|zh|>"}, 7.0, 0.36);
    check(out.text == "你你" && out.words.size() == 2);
    check(std::abs(out.words[0].start - 7.0) < 1e-9 && std::abs(out.words[0].end - 7.09) < 1e-9);
    check(std::abs(out.words[1].start - 7.15) < 1e-9 && std::abs(out.words[1].end - 7.27) < 1e-9);
    auto bytes = segment({{0,0,1},{1,1,2},{2,2,3},{3,3,4}}, {"<0xE4>","<0xBD>","<0xA0>","好"}, 0, 0.21);
    check(bytes.text == "你好" && bytes.words.size() == 2 && bytes.words[0].end <= bytes.words[1].start);
    check(std::abs(bytes.words[0].end - 0.15) < 1e-9 && std::abs(bytes.words[1].end - 0.21) < 1e-9);
    auto english = segment({{0,0,2},{1,2,4},{2,4,5},{3,5,6}}, {"▁hel","lo","▁","world"}, 0, 1);
    check(english.text == "hello world" && english.words.size() == 2 && english.words[0].word == "hello");
    check(segment({{0,0,1}}, {"<|zh|>"}, 0, 1).text.empty());
    check(json_string("a\"\\\n") == "\"a\\\"\\\\\\u000a\"");
    check(json({}).find("\"segments\":[]") != std::string::npos);
    rejected = false;
    try { segment({{0,0,1}}, {"<0xFF>"}, 0, 1); } catch (const std::runtime_error &) { rejected = true; }
    check(rejected);
    std::cout << "CTC, repeated labels, blanks, query offset, Unicode, byte fallback and JSON passed\n";
}
