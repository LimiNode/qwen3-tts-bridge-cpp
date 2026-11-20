#include <qwen_tts_bridge/text/segmentation.hpp>

#include <initializer_list>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {

using namespace qwen_tts_bridge::text;

void require(bool condition, const char* message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

void expect(std::string source, std::initializer_list<std::string> expected) {
    const auto segments = plan_speech_segments(source);
    require(segments.size() == expected.size(), "wrong speech segment count");
    std::size_t index = 0;
    std::size_t previous = 0;
    std::string recovered;
    for (const auto& text : expected) {
        const auto& segment = segments[index++];
        require(segment.begin == previous, "speech segment source gap");
        const auto actual = source.substr(segment.begin, segment.end - segment.begin);
        require(actual == text, "speech segment changed source bytes");
        recovered += actual;
        previous = segment.end;
    }
    if (!segments.empty()) {
        require(recovered == source, "speech segment source coverage incomplete");
    }
}

template<class Exception, class Operation>
void rejects(Operation operation) {
    try {
        operation();
    }
    catch (const Exception&) {
        return;
    }
    throw std::runtime_error("invalid speech segmentation input accepted");
}

} // namespace

int main() {
    try {
        expect("", {});
        expect(" \t\r\n", {});
        expect("  Hello.\r\nWorld! \t", {"  Hello.\r\n", "World! \t"});
        expect("Hello... Really?! Yes", {"Hello... ", "Really?! ", "Yes"});
        expect(u8"\u041c\u0413\u0423 \u043d\u0430\u0445\u043e\u0434\u0438\u0442\u0441\u044f \u0432 \u041c\u043e\u0441\u043a\u0432\u0435. \u0418\u043d\u0436\u0435\u043d\u0435\u0440 \u043f\u0440\u043e\u0432\u0435\u0440\u0438\u043b USB-\u043f\u043e\u0440\u0442, GPS \u0438 \u043d\u043e\u0432\u044b\u0439 \u043f\u0440\u043e\u0446\u0435\u0441\u0441\u043e\u0440.",
            {u8"\u041c\u0413\u0423 \u043d\u0430\u0445\u043e\u0434\u0438\u0442\u0441\u044f \u0432 \u041c\u043e\u0441\u043a\u0432\u0435. ",
             u8"\u0418\u043d\u0436\u0435\u043d\u0435\u0440 \u043f\u0440\u043e\u0432\u0435\u0440\u0438\u043b USB-\u043f\u043e\u0440\u0442, GPS \u0438 \u043d\u043e\u0432\u044b\u0439 \u043f\u0440\u043e\u0446\u0435\u0441\u0441\u043e\u0440."});
        expect(u8"\u0412 \u043c\u0430\u0441\u0442\u0435\u0440\u0441\u043a\u043e\u0301\u0439 \u0442\u0438\u0445\u043e. \u0417\u0430\u043c\u043e\u0301\u043a \u0437\u0430\u043a\u0440\u044b\u0442.",
            {u8"\u0412 \u043c\u0430\u0441\u0442\u0435\u0440\u0441\u043a\u043e\u0301\u0439 \u0442\u0438\u0445\u043e. ", u8"\u0417\u0430\u043c\u043e\u0301\u043a \u0437\u0430\u043a\u0440\u044b\u0442."});
        expect("Dr. A. Smith measured 3.14 volts. Ready?", {"Dr. A. Smith measured 3.14 volts. ", "Ready?"});
        expect(u8"\u042f \u0432 \u043c\u0430\u0441\u0442\u0435\u0440\u0441\u043a\u043e\u0301\u0439. \u0414\u0430.",
            {u8"\u042f \u0432 \u043c\u0430\u0441\u0442\u0435\u0440\u0441\u043a\u043e\u0301\u0439. ", u8"\u0414\u0430."});
        expect("The U.S.A. team arrived. Wait!", {"The U.S.A. team arrived. ", "Wait!"});
        expect(u8"\u0410. \u0421. \u041f\u0443\u0448\u043a\u0438\u043d \u0436\u0438\u043b \u0432 \u0433. \u041c\u043e\u0441\u043a\u0432\u0435. \u0414\u0430.",
            {u8"\u0410. \u0421. \u041f\u0443\u0448\u043a\u0438\u043d \u0436\u0438\u043b \u0432 \u0433. \u041c\u043e\u0441\u043a\u0432\u0435. ", u8"\u0414\u0430."});
        expect("He said \"Hello. World!\" Then left.", {"He said \"Hello. World!\" ", "Then left."});
        expect("He said \"Stop!\", then waited. Done.", {"He said \"Stop!\", then waited. ", "Done."});
        expect("He said 'Don't. Wait!' Then left.", {"He said 'Don't. Wait!' ", "Then left."});
        expect("Don't stop. It's fine.", {"Don't stop. ", "It's fine."});
        expect(u8"He said \u2018Don\u2019t. Wait!\u2019 Then left.",
            {u8"He said \u2018Don\u2019t. Wait!\u2019 ", "Then left."});
        expect(u8"\u00ab\u0414\u0430!\u00bb \u0414\u0430\u043b\u044c\u0448\u0435\u2026 \u0412\u0441\u0451.",
            {u8"\u00ab\u0414\u0430!\u00bb ", u8"\u0414\u0430\u043b\u044c\u0448\u0435\u2026 ", u8"\u0412\u0441\u0451."});
        expect("(One. Two.) Three.", {"(One. Two.) ", "Three."});
        expect("Open quote \"One. Two.", {"Open quote \"One. Two."});
        expect("Visit example.org. Done.", {"Visit example.org. ", "Done."});
        expect(u8"Hello.\u00a0Next.\u202fLast.", {u8"Hello.\u00a0", u8"Next.\u202f", "Last."});
        rejects<std::invalid_argument>([] { plan_speech_segments(std::string("a\0b", 3)); });
        rejects<std::invalid_argument>([] { plan_speech_segments("\xC0\x80"); });
        rejects<std::invalid_argument>([] { plan_speech_segments("\xED\xA0\x80"); });
        rejects<std::invalid_argument>([] { plan_speech_segments("\xF4\x90\x80\x80"); });
        rejects<std::invalid_argument>([] { plan_speech_segments("\xE2\x80"); });
        rejects<std::invalid_argument>([] { plan_speech_segments("Hello", {0, 5, 1}); });
        rejects<std::length_error>([] { plan_speech_segments("Hello", {4, 5, 1}); });
        rejects<std::length_error>([] { plan_speech_segments("Long no boundary", {100, 4, 2}); });
        rejects<std::length_error>([] { plan_speech_segments("One. Two.", {100, 100, 1}); });
        const auto bounded = plan_speech_segments("One. Two.", {100, 5, 2});
        require(bounded.size() == 2, "complete segments rejected at exact byte limit");
        return 0;
    }
    catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
