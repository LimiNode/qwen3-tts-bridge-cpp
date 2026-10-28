#include "prepared_voice_reference.hpp"

#include "runtime_manifest.hpp"

#include <nlohmann/json.hpp>

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>
#include <limits>
#include <stdexcept>

namespace qwen_tts_bridge::native_worker {
namespace {

using Json = nlohmann::json;

constexpr int kSchemaVersion = 1;
constexpr int kPreprocessingVersion = 1;
constexpr int kSampleRate = 24000;
constexpr int kRvqCodeBits = 11;
constexpr std::int32_t kMaxRvqCode = (1 << kRvqCodeBits) - 1;
constexpr std::uintmax_t kMaxSpeakerBytes = 16u * 1024u * 1024u;
constexpr std::uintmax_t kMaxRvqBytes = 256u * 1024u * 1024u;

bool is_safe_relative_path(const std::filesystem::path& path) {
    if (path.empty() || path.is_absolute() || path.has_root_name() || path.has_root_directory()) {
        return false;
    }
    for (const auto& part : path) {
        if (part == ".." || part == ".") {
            return false;
        }
    }
    return true;
}

void reject_reparse_point(const std::filesystem::path& path) {
    const DWORD attributes = GetFileAttributesW(path.c_str());
    if (attributes != INVALID_FILE_ATTRIBUTES &&
        (attributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0) {
        throw std::runtime_error("prepared voice path must not be a reparse point: " + path.u8string());
    }
}

void reject_reparse_ancestors(std::filesystem::path path) {
    path = std::filesystem::absolute(path);
    for (auto current = path; !current.empty(); current = current.parent_path()) {
        reject_reparse_point(current);
        const auto parent = current.parent_path();
        if (parent == current) {
            break;
        }
    }
}

std::string required_string(const Json& object, const char* name) {
    const auto value = object.find(name);
    if (value == object.end() || !value->is_string() || value->get_ref<const std::string&>().empty()) {
        throw std::runtime_error(std::string("prepared voice manifest requires non-empty ") + name);
    }
    return value->get<std::string>();
}

int required_integer(const Json& object, const char* name) {
    const auto value = object.find(name);
    if (value == object.end() || !value->is_number_integer()) {
        throw std::runtime_error(std::string("prepared voice manifest requires integer ") + name);
    }
    return value->get<int>();
}

std::uintmax_t required_size(const Json& object, const char* name) {
    const auto value = object.find(name);
    if (value == object.end() || !value->is_number_unsigned()) {
        throw std::runtime_error(std::string("prepared voice manifest requires unsigned ") + name);
    }
    return value->get<std::uintmax_t>();
}

std::filesystem::path artifact_path(
    const std::filesystem::path& manifest_path,
    const std::string& relative_path) {
    const auto relative = std::filesystem::u8path(relative_path);
    if (!is_safe_relative_path(relative)) {
        throw std::runtime_error("prepared voice artifact path must be relative without traversal");
    }
    const auto path = std::filesystem::absolute(manifest_path.parent_path() / relative).lexically_normal();
    reject_reparse_ancestors(path);
    return path;
}

std::vector<unsigned char> read_bounded_file(
    const std::filesystem::path& path,
    std::uintmax_t expected_size,
    std::uintmax_t maximum_size) {
    reject_reparse_ancestors(path);
    if (!std::filesystem::is_regular_file(path)) {
        throw std::runtime_error("prepared voice artifact is missing: " + path.u8string());
    }
    const auto size = std::filesystem::file_size(path);
    if (size == 0 || size != expected_size || size > maximum_size ||
        size > static_cast<std::uintmax_t>((std::numeric_limits<std::streamsize>::max)())) {
        throw std::runtime_error("prepared voice artifact size mismatch: " + path.u8string());
    }
    std::vector<unsigned char> bytes(static_cast<std::size_t>(size));
    std::ifstream input(path, std::ios::binary);
    if (!input || !input.read(
            reinterpret_cast<char*>(bytes.data()),
            static_cast<std::streamsize>(bytes.size()))) {
        throw std::runtime_error("unable to read prepared voice artifact: " + path.u8string());
    }
    return bytes;
}

std::vector<unsigned char> pack_codes(const std::vector<std::int32_t>& codes) {
    const std::size_t total_bits = codes.size() * static_cast<std::size_t>(kRvqCodeBits);
    std::vector<unsigned char> output((total_bits + 7u) / 8u, 0);
    std::uint64_t accumulator = 0;
    int bits = 0;
    std::size_t output_index = 0;
    for (const auto code : codes) {
        if (code < 0 || code > kMaxRvqCode) {
            throw std::runtime_error("prepared voice RVQ code is outside the 11-bit range");
        }
        accumulator |= static_cast<std::uint64_t>(code) << bits;
        bits += kRvqCodeBits;
        while (bits >= 8) {
            output[output_index++] = static_cast<unsigned char>(accumulator & 0xffu);
            accumulator >>= 8;
            bits -= 8;
        }
    }
    if (bits > 0) {
        output[output_index] = static_cast<unsigned char>(accumulator & 0xffu);
    }
    return output;
}

std::vector<std::int32_t> unpack_codes(
    const std::vector<unsigned char>& bytes,
    std::size_t count) {
    std::vector<std::int32_t> codes(count);
    std::uint64_t accumulator = 0;
    int bits = 0;
    std::size_t input_index = 0;
    for (auto& code : codes) {
        while (bits < kRvqCodeBits) {
            if (input_index >= bytes.size()) {
                throw std::runtime_error("prepared voice RVQ stream is truncated");
            }
            accumulator |= static_cast<std::uint64_t>(bytes[input_index++]) << bits;
            bits += 8;
        }
        code = static_cast<std::int32_t>(accumulator & kMaxRvqCode);
        accumulator >>= kRvqCodeBits;
        bits -= kRvqCodeBits;
    }
    return codes;
}

void write_bytes(const std::filesystem::path& path, const void* data, std::size_t size) {
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output || !output.write(static_cast<const char*>(data), static_cast<std::streamsize>(size))) {
        throw std::runtime_error("unable to write prepared voice artifact: " + path.u8string());
    }
    output.close();
    if (!output) {
        throw std::runtime_error("unable to finish prepared voice artifact: " + path.u8string());
    }
}

void remove_if_exists(const std::filesystem::path& path) noexcept {
    std::error_code error;
    std::filesystem::remove(path, error);
}

void validate_context(const PreparedVoiceReferenceContext& context) {
    if (context.engine_commit.empty() || context.abi_version <= 0 ||
        context.num_codebooks <= 0 || context.talker_sha256.size() != 64 ||
        context.codec_sha256.size() != 64 || context.source_audio_sha256.size() != 64) {
        throw std::runtime_error("prepared voice context is incomplete");
    }
    reject_reparse_ancestors(context.manifest_path);
}

} // namespace

std::filesystem::path resolve_prepared_manifest_path(
    const std::filesystem::path& registry_directory,
    const std::string& relative_path) {
    const auto relative = std::filesystem::u8path(relative_path);
    if (!is_safe_relative_path(relative)) {
        throw std::runtime_error("native_reference.manifest_path must be relative without traversal");
    }
    const auto root = std::filesystem::absolute(registry_directory).lexically_normal();
    const auto resolved = std::filesystem::absolute(root / relative).lexically_normal();
    const auto within_root = resolved.lexically_relative(root);
    if (!is_safe_relative_path(within_root)) {
        throw std::runtime_error("native_reference.manifest_path escapes the registry directory");
    }
    reject_reparse_ancestors(resolved);
    return resolved;
}

PreparedVoiceReferenceData load_prepared_voice_reference(
    const PreparedVoiceReferenceContext& context) {
    validate_context(context);
    std::ifstream input(context.manifest_path, std::ios::binary);
    if (!input) {
        throw std::runtime_error("prepared voice manifest is missing: " + context.manifest_path.u8string());
    }
    Json root;
    try {
        input >> root;
    }
    catch (const std::exception& error) {
        throw std::runtime_error(std::string("invalid prepared voice manifest: ") + error.what());
    }
    if (!root.is_object() || required_integer(root, "schema_version") != kSchemaVersion ||
        required_string(root, "format") != "qwen3-tts-native-voice-reference") {
        throw std::runtime_error("unsupported prepared voice manifest format");
    }
    if (root.value("reference_text", std::string{}) != context.reference_text ||
        root.value("x_vector_only", !context.x_vector_only) != context.x_vector_only ||
        required_string(root, "source_wav_sha256") != context.source_audio_sha256) {
        throw std::runtime_error("prepared voice source or transcript identity mismatch");
    }
    const auto& engine = root.at("engine");
    if (!engine.is_object() || required_string(engine, "name") != "qwentts.cpp" ||
        required_string(engine, "commit") != context.engine_commit ||
        required_integer(engine, "abi_version") != context.abi_version) {
        throw std::runtime_error("prepared voice engine identity mismatch");
    }
    const auto& models = root.at("models");
    if (!models.is_object() || required_string(models, "talker_sha256") != context.talker_sha256 ||
        required_string(models, "codec_sha256") != context.codec_sha256) {
        throw std::runtime_error("prepared voice model identity mismatch");
    }
    const auto& preprocessing = root.at("preprocessing");
    const int expected_silence = context.x_vector_only ? 0 : 12000;
    if (!preprocessing.is_object() || required_integer(preprocessing, "version") != kPreprocessingVersion ||
        required_integer(preprocessing, "sample_rate") != kSampleRate ||
        required_integer(preprocessing, "channels") != 1 ||
        required_integer(preprocessing, "icl_trailing_silence_samples") != expected_silence) {
        throw std::runtime_error("prepared voice preprocessing identity mismatch");
    }

    const auto& speaker = root.at("speaker");
    const int speaker_dim = required_integer(speaker, "dimension");
    const auto speaker_size = required_size(speaker, "size_bytes");
    if (speaker_dim <= 0 || speaker_size != static_cast<std::uintmax_t>(speaker_dim) * sizeof(float)) {
        throw std::runtime_error("prepared voice speaker dimensions are invalid");
    }
    const auto speaker_path = artifact_path(context.manifest_path, required_string(speaker, "path"));
    if (sha256_file(speaker_path) != required_string(speaker, "sha256")) {
        throw std::runtime_error("prepared voice speaker SHA-256 mismatch");
    }
    const auto speaker_bytes = read_bounded_file(speaker_path, speaker_size, kMaxSpeakerBytes);

    PreparedVoiceReferenceData result;
    result.speaker_embedding.resize(static_cast<std::size_t>(speaker_dim));
    std::memcpy(result.speaker_embedding.data(), speaker_bytes.data(), speaker_bytes.size());
    if (std::any_of(result.speaker_embedding.begin(), result.speaker_embedding.end(),
                    [](float value) { return !std::isfinite(value); })) {
        throw std::runtime_error("prepared voice speaker embedding contains NaN or Inf");
    }
    result.num_codebooks = context.num_codebooks;

    const auto rvq = root.find("rvq");
    if (context.x_vector_only) {
        if (rvq == root.end() || !rvq->is_null()) {
            throw std::runtime_error("x-vector-only prepared voice must not contain RVQ data");
        }
    }
    else {
        if (rvq == root.end() || !rvq->is_object()) {
            throw std::runtime_error("ICL prepared voice requires RVQ data");
        }
        const int codebooks = required_integer(*rvq, "codebooks");
        const int frames = required_integer(*rvq, "frames");
        const int bits = required_integer(*rvq, "bits_per_code");
        if (codebooks != context.num_codebooks || frames <= 0 || bits != kRvqCodeBits) {
            throw std::runtime_error("prepared voice RVQ layout is incompatible");
        }
        const std::size_t code_count = static_cast<std::size_t>(codebooks) * static_cast<std::size_t>(frames);
        if (code_count > (std::numeric_limits<std::size_t>::max)() / kRvqCodeBits) {
            throw std::runtime_error("prepared voice RVQ dimensions are too large");
        }
        const std::uintmax_t expected_bytes = (code_count * kRvqCodeBits + 7u) / 8u;
        const auto rvq_size = required_size(*rvq, "size_bytes");
        if (rvq_size != expected_bytes || rvq_size > kMaxRvqBytes) {
            throw std::runtime_error("prepared voice RVQ size is invalid");
        }
        const auto rvq_path = artifact_path(context.manifest_path, required_string(*rvq, "path"));
        if (sha256_file(rvq_path) != required_string(*rvq, "sha256")) {
            throw std::runtime_error("prepared voice RVQ SHA-256 mismatch");
        }
        result.codes = unpack_codes(read_bounded_file(rvq_path, rvq_size, kMaxRvqBytes), code_count);
        result.frames = frames;
    }
    result.cache_key = "prepared:" + required_string(speaker, "sha256") + ":" +
        (context.x_vector_only ? "xvector" : required_string(*rvq, "sha256")) + ":" +
        context.reference_text;
    return result;
}

PreparedVoiceReferenceData persist_prepared_voice_reference(
    const PreparedVoiceReferenceContext& context,
    const qt_voice_ref& extracted) {
    validate_context(context);
    if (extracted.ref_spk_emb == nullptr || extracted.ref_spk_dim <= 0 ||
        std::any_of(extracted.ref_spk_emb, extracted.ref_spk_emb + extracted.ref_spk_dim,
                    [](float value) { return !std::isfinite(value); })) {
        throw std::runtime_error("extracted speaker embedding is invalid");
    }
    if (!context.x_vector_only &&
        (extracted.ref_codes == nullptr || extracted.ref_T <= 0 ||
         extracted.num_codebooks != context.num_codebooks)) {
        throw std::runtime_error("extracted RVQ layout is invalid");
    }

    const auto directory = context.manifest_path.parent_path();
    reject_reparse_ancestors(directory.parent_path());
    std::filesystem::create_directories(directory);
    reject_reparse_ancestors(directory);
    const auto speaker_path = directory / "reference.spk";
    const auto rvq_path = directory / "reference.rvq";
    if (std::filesystem::exists(context.manifest_path) || std::filesystem::exists(speaker_path) ||
        std::filesystem::exists(rvq_path)) {
        throw std::runtime_error("refusing to overwrite an existing prepared voice publication");
    }

    const std::string suffix = ".qtb-tmp-" + std::to_string(GetCurrentProcessId());
    const auto speaker_temp = directory / ("reference.spk" + suffix);
    const auto rvq_temp = directory / ("reference.rvq" + suffix);
    const auto manifest_temp = directory / (context.manifest_path.filename().u8string() + suffix);
    bool speaker_published = false;
    bool rvq_published = false;
    try {
        const auto speaker_bytes = static_cast<std::size_t>(extracted.ref_spk_dim) * sizeof(float);
        write_bytes(speaker_temp, extracted.ref_spk_emb, speaker_bytes);

        std::vector<std::int32_t> codes;
        std::vector<unsigned char> packed_codes;
        if (!context.x_vector_only) {
            const auto count = static_cast<std::size_t>(extracted.num_codebooks) *
                static_cast<std::size_t>(extracted.ref_T);
            codes.assign(extracted.ref_codes, extracted.ref_codes + count);
            packed_codes = pack_codes(codes);
            write_bytes(rvq_temp, packed_codes.data(), packed_codes.size());
        }

        Json root = {
            {"schema_version", kSchemaVersion},
            {"format", "qwen3-tts-native-voice-reference"},
            {"source_wav_sha256", context.source_audio_sha256},
            {"reference_text", context.reference_text},
            {"x_vector_only", context.x_vector_only},
            {"engine", {
                {"name", "qwentts.cpp"},
                {"commit", context.engine_commit},
                {"abi_version", context.abi_version},
            }},
            {"models", {
                {"talker_sha256", context.talker_sha256},
                {"codec_sha256", context.codec_sha256},
            }},
            {"preprocessing", {
                {"version", kPreprocessingVersion},
                {"sample_rate", kSampleRate},
                {"channels", 1},
                {"sample_format", "float32"},
                {"icl_trailing_silence_samples", context.x_vector_only ? 0 : 12000},
            }},
            {"speaker", {
                {"path", "reference.spk"},
                {"dimension", extracted.ref_spk_dim},
                {"size_bytes", speaker_bytes},
                {"sha256", sha256_file(speaker_temp)},
                {"scalar", "float32-le"},
            }},
            {"rvq", nullptr},
        };
        if (!context.x_vector_only) {
            root["rvq"] = {
                {"path", "reference.rvq"},
                {"codebooks", extracted.num_codebooks},
                {"frames", extracted.ref_T},
                {"bits_per_code", kRvqCodeBits},
                {"layout", "codebook-major-frame-fastest"},
                {"size_bytes", packed_codes.size()},
                {"sha256", sha256_file(rvq_temp)},
            };
        }
        const std::string manifest_bytes = root.dump(2) + "\n";
        write_bytes(manifest_temp, manifest_bytes.data(), manifest_bytes.size());

        // Re-read every temporary artifact before any path becomes visible.
        (void)read_bounded_file(speaker_temp, speaker_bytes, kMaxSpeakerBytes);
        if (!context.x_vector_only) {
            const auto checked = unpack_codes(
                read_bounded_file(rvq_temp, packed_codes.size(), kMaxRvqBytes), codes.size());
            if (checked != codes) {
                throw std::runtime_error("prepared voice RVQ round-trip mismatch");
            }
        }
        Json checked_manifest;
        std::ifstream manifest_input(manifest_temp, std::ios::binary);
        manifest_input >> checked_manifest;
        manifest_input.close();
        if (checked_manifest != root) {
            throw std::runtime_error("prepared voice manifest round-trip mismatch");
        }

        std::filesystem::rename(speaker_temp, speaker_path);
        speaker_published = true;
        if (!context.x_vector_only) {
            std::filesystem::rename(rvq_temp, rvq_path);
            rvq_published = true;
        }
        std::filesystem::rename(manifest_temp, context.manifest_path);
    }
    catch (...) {
        remove_if_exists(speaker_temp);
        remove_if_exists(rvq_temp);
        remove_if_exists(manifest_temp);
        if (speaker_published) {
            remove_if_exists(speaker_path);
        }
        if (rvq_published) {
            remove_if_exists(rvq_path);
        }
        throw;
    }
    return load_prepared_voice_reference(context);
}

} // namespace qwen_tts_bridge::native_worker
