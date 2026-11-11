#include <qwen_tts_bridge/audio.hpp>

#include "play.hpp"

#include "common/cli_parsing.hpp"

#include <iostream>
#include <stdexcept>

namespace qwen_tts_examples::play {

using qwen_tts_examples::cli::parse_double;
using qwen_tts_examples::cli::parse_int;
using qwen_tts_examples::cli::parse_u32;
using qwen_tts_examples::cli::parse_u64;
void print_interactive_status(const ProgramOptions& options) {
    if (options.auto_profile) {
        std::cout << "profile=auto (fast <= " << options.auto_fast_max_bytes
                  << " non-space UTF-8 bytes, safe above)\n";
    }
    std::cout << "speaker=" << (options.speaker.empty() ? "<worker default>" : options.speaker)
              << ", voice_id=" << (options.voice_id.empty() ? "<none>" : options.voice_id)
              << ", language=" << options.language
              << ", style=" << (options.instruction.empty() ? "<none>" : options.instruction)
              << "\n";
    std::cout << "sampling: temperature="
              << (options.temperature.has_value() ? std::to_string(options.temperature.value()) : "<worker default>")
              << ", top_k="
              << (options.top_k.has_value() ? std::to_string(options.top_k.value()) : "<worker default>")
              << ", top_p="
              << (options.top_p.has_value() ? std::to_string(options.top_p.value()) : "<worker default>")
              << ", repetition_penalty="
              << (options.repetition_penalty.has_value() ? std::to_string(options.repetition_penalty.value()) : "<worker default>")
              << ", do_sample=";
    if (!options.do_sample.has_value()) {
        std::cout << "<worker default>";
    }
    else {
        std::cout << (options.do_sample.value() ? "on" : "off");
    }
    std::cout << ", seed="
              << (options.seed.has_value() ? std::to_string(options.seed.value()) : "<worker default>")
              << '\n';
    std::cout << "worker capabilities: sampling_overrides="
              << (options.sampling_overrides_supported ? "true" : "false")
              << ", deterministic_seed="
              << (options.deterministic_seed_supported ? "true" : "false")
              << ", voice_clone="
              << (options.voice_clone_supported ? "true" : "false")
              << ", voice_profiles="
              << (options.voice_profiles_supported ? "true" : "false")
              << '\n';
    if (!options.reference_audio_path.empty()) {
        std::cout << "voice clone: reference_audio=" << options.reference_audio_path
                  << ", mode=" << (options.x_vector_only ? "x_vector_only" : "icl")
                  << '\n';
    }
}

bool has_sampling_overrides(const ProgramOptions& options) {
    return options.temperature.has_value() ||
           options.top_k.has_value() ||
           options.top_p.has_value() ||
           options.repetition_penalty.has_value() ||
           options.do_sample.has_value();
}

void require_sampling_overrides_supported(const ProgramOptions& options) {
    if (!options.sampling_overrides_supported) {
        throw std::runtime_error(
            "sampling overrides are disabled by the active worker profile; "
            "use the StyleExperiment launcher profile");
    }
}

void require_deterministic_seed_supported(const ProgramOptions& options) {
    if (!options.deterministic_seed_supported) {
        throw std::runtime_error(
            "the active worker profile does not guarantee deterministic explicit seeds");
    }
}

bool apply_interactive_command(ProgramOptions& options, const std::string& line) {
    const auto split = line.find(' ');
    const std::string command = line.substr(0, split);
    const std::string value = split == std::string::npos ? "" : line.substr(split + 1);

    if (command == "/voice") {
        if (value.empty()) {
            std::cerr << "usage: /voice <name>\n";
        }
        else if (options.voice_profiles_supported) {
            options.voice_id = value;
            options.speaker.clear();
            print_interactive_status(options);
        }
        else {
            options.speaker = value;
            options.voice_id.clear();
            print_interactive_status(options);
        }
        return true;
    }
    if (command == "/voices") {
        if (!options.voice_profiles_supported) {
            std::cout << "the active worker has no registered voice profiles\n";
        }
        else if (options.voice_ids.empty()) {
            std::cout << "the voice registry is empty\n";
        }
        else {
            std::cout << "registered voice profiles:\n";
            for (const std::string& voice_id : options.voice_ids) {
                std::cout << "  " << voice_id << '\n';
            }
        }
        return true;
    }
    if (command == "/language") {
        if (value.empty()) {
            std::cerr << "usage: /language <name>\n";
        }
        else {
            options.language = value;
            print_interactive_status(options);
        }
        return true;
    }
    if (command == "/style") {
        options.instruction = value;
        print_interactive_status(options);
        return true;
    }
    if (command == "/temperature") {
        if (value == "default") {
            options.temperature.reset();
        }
        else {
            require_sampling_overrides_supported(options);
            const double temperature = parse_double(value, "/temperature");
            if (temperature <= 0.0 || temperature > 2.0) {
                throw std::runtime_error("/temperature must be in the interval (0, 2]");
            }
            options.temperature = temperature;
        }
        print_interactive_status(options);
        return true;
    }
    if (command == "/top-k") {
        if (value == "default") {
            options.top_k.reset();
        }
        else {
            require_sampling_overrides_supported(options);
            const std::uint32_t top_k = parse_u32(value, "/top-k");
            if (top_k == 0) {
                throw std::runtime_error("/top-k must be greater than zero");
            }
            options.top_k = top_k;
        }
        print_interactive_status(options);
        return true;
    }
    if (command == "/top-p") {
        if (value == "default") {
            options.top_p.reset();
        }
        else {
            require_sampling_overrides_supported(options);
            const double top_p = parse_double(value, "/top-p");
            if (top_p <= 0.0 || top_p > 1.0) {
                throw std::runtime_error("/top-p must be in the interval (0, 1]");
            }
            options.top_p = top_p;
        }
        print_interactive_status(options);
        return true;
    }
    if (command == "/repetition-penalty") {
        if (value == "default") {
            options.repetition_penalty.reset();
        }
        else {
            require_sampling_overrides_supported(options);
            const double repetition_penalty = parse_double(value, "/repetition-penalty");
            if (repetition_penalty < 1.0 || repetition_penalty > 2.0) {
                throw std::runtime_error("/repetition-penalty must be in the interval [1, 2]");
            }
            options.repetition_penalty = repetition_penalty;
        }
        print_interactive_status(options);
        return true;
    }
    if (command == "/sample") {
        if (value == "on") {
            require_sampling_overrides_supported(options);
            options.do_sample = true;
        }
        else if (value == "off") {
            require_sampling_overrides_supported(options);
            options.do_sample = false;
        }
        else if (value == "default") {
            options.do_sample.reset();
        }
        else {
            std::cerr << "usage: /sample <on|off|default>\n";
            return true;
        }
        print_interactive_status(options);
        return true;
    }
    if (command == "/seed") {
        if (value == "default" || value == "off") {
            options.seed.reset();
        }
        else {
            require_deterministic_seed_supported(options);
            options.seed = parse_u64(value, "/seed");
        }
        print_interactive_status(options);
        return true;
    }
    if (command == "/sampling") {
        print_interactive_status(options);
        return true;
    }
    return false;
}


} // namespace qwen_tts_examples::play
