#include "play.hpp"

#include <initializer_list>
#include <iostream>
#include <stdexcept>

namespace {
using namespace qwen_tts_examples::play;

void require(bool condition, const char* message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

ProgramOptions parse(std::initializer_list<std::wstring> values) {
    std::vector<std::wstring> storage(values);
    std::vector<wchar_t*> arguments;
    for (auto& value : storage) {
        arguments.push_back(value.data());
    }
    return parse_options(static_cast<int>(arguments.size()), arguments.data());
}

template<typename Operation>
void rejects(Operation operation, const std::string& expected) {
    try {
        operation();
    }
    catch (const std::runtime_error& error) {
        require(std::string(error.what()).find(expected) != std::string::npos,
            "wrong option error");
        return;
    }
    throw std::runtime_error("invalid option was accepted");
}
} // namespace

int main() {
    try {
        auto options = parse({L"play", L"--mock", L"--text=\u041f\u0440\u0438\u0432\u0435\u0442",
            L"--top-k", L"12", L"--seed=42", L"--auto-fast-max-chars=100"});
        validate_options(options);
        require(options.text == u8"\u041f\u0440\u0438\u0432\u0435\u0442", "UTF-8 text changed");
        require(options.top_k == 12 && options.seed == 42, "numeric options changed");
        require(options.auto_fast_max_bytes == 100, "legacy option alias changed");
        rejects([] { parse({L"play", L"--unknown"}); }, "unknown option");
        rejects([] { parse({L"play", L"--seed"}); }, "missing value for --seed");
        rejects([&] {
            auto invalid = options;
            invalid.pcm_capture_file = "capture.wav";
            invalid.wav_capture_file = "capture.wav";
            validate_options(invalid);
        }, "must use different paths");

        rejects([&] { apply_interactive_command(options, "/temperature 0.8"); },
            "sampling overrides are disabled");
        options.sampling_overrides_supported = true;
        require(apply_interactive_command(options, "/temperature 0.8") &&
            options.temperature == 0.8, "interactive sampling update failed");
        apply_interactive_command(options, "/temperature default");
        require(!options.temperature.has_value(), "interactive reset changed");
        apply_interactive_command(options, "/voice ryan");
        require(options.speaker == "ryan" && options.voice_id.empty(), "speaker routing changed");
        options.voice_profiles_supported = true;
        apply_interactive_command(options, "/voice registered");
        require(options.voice_id == "registered" && options.speaker.empty(), "profile routing changed");
        require(!apply_interactive_command(options, "/unknown"), "unknown command was consumed");
        rejects([&] { apply_interactive_command(options, "/seed 7"); },
            "does not guarantee deterministic");
        options.deterministic_seed_supported = true;
        apply_interactive_command(options, "/seed 7");
        require(options.seed == 7, "interactive seed changed");
        apply_interactive_command(options, "/seed off");
        require(!options.seed.has_value(), "interactive seed reset changed");

        options.use_mock_worker = false;
        options.worker_executable = "worker.exe";
        options.worker_arguments = {"--runtime-profile=fast", "--max-seq-len", "1024",
            "--emit-every-frames", "4", "--decode-window-frames", "16"};
        const auto safe = make_transport_options(options, true);
        require(safe.arguments[1] == "--runtime-profile=cmp50hx-safe", "safe route changed");
        require(safe.environment_overrides.at(
            "QTB_FASTER_CODEC_RIGHT_PADDED_DECODE_WINDOW_FRAMES") == "33",
            "safe worker environment changed");
        return 0;
    }
    catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
