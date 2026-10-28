#include "prepared_voice_reference.hpp"

#include "runtime_manifest.hpp"

#include <nlohmann/json.hpp>

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <algorithm>
#include <atomic>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <limits>
#include <random>
#include <sstream>
#include <stdexcept>

namespace qwen_tts_bridge::native_worker {
namespace {

using Json = nlohmann::json;

constexpr int kSchemaVersion = 1;
constexpr int kPreprocessingVersion = 1;
constexpr int kSampleRate = 24000;
constexpr int kRvqCodeBits = 11;
constexpr std::int32_t kMaxRvqCode = (1 << kRvqCodeBits) - 1;
constexpr int kMaxSpeakerDimension = 1 << 20;
constexpr int kMaxRvqCodebooks = 64;
constexpr int kMaxRvqFrames = 1 << 20;
constexpr std::uintmax_t kMaxManifestBytes = 1u * 1024u * 1024u;
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

std::string read_bounded_text_file(
    const std::filesystem::path& path,
    std::uintmax_t maximum_size) {
    reject_reparse_ancestors(path);
    if (!std::filesystem::is_regular_file(path)) {
        throw std::runtime_error("prepared voice manifest is missing: " + path.u8string());
    }
    const auto size = std::filesystem::file_size(path);
    if (size > maximum_size ||
        size > static_cast<std::uintmax_t>((std::numeric_limits<std::streamsize>::max)())) {
        throw std::runtime_error("prepared voice manifest is too large: " + path.u8string());
    }
    std::string bytes(static_cast<std::size_t>(size), '\0');
    std::ifstream input(path, std::ios::binary);
    if (!input || !input.read(bytes.data(), static_cast<std::streamsize>(bytes.size()))) {
        throw std::runtime_error("unable to read prepared voice manifest: " + path.u8string());
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

std::filesystem::path publication_marker_path(const std::filesystem::path& directory) {
    return directory / ".qtb-publication.incomplete";
}

std::string new_generation_id() {
    static std::atomic<std::uint64_t> sequence{0};
    LARGE_INTEGER counter{};
    QueryPerformanceCounter(&counter);
    std::random_device random;
    std::ostringstream output;
    output << std::hex << static_cast<unsigned long long>(GetCurrentProcessId()) << '-'
           << static_cast<unsigned long long>(GetTickCount64()) << '-'
           << static_cast<unsigned long long>(counter.QuadPart) << '-'
           << static_cast<unsigned long long>(random()) << '-'
           << sequence.fetch_add(1, std::memory_order_relaxed);
    return output.str();
}

bool is_safe_generation_id(const std::string& value) {
    return !value.empty() && value.size() <= 160 &&
        std::all_of(value.begin(), value.end(), [](unsigned char character) {
            return std::isalnum(character) || character == '-';
        });
}

class PublicationLock final {
public:
    explicit PublicationLock(const std::filesystem::path& directory)
        : path_(directory / ".qtb-publication.lock") {
        for (int attempt = 0; attempt != 3; ++attempt) {
            handle_ = CreateFileW(
                path_.c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr, CREATE_NEW,
                FILE_ATTRIBUTE_HIDDEN, nullptr);
            if (handle_ != INVALID_HANDLE_VALUE) {
                return;
            }
            const DWORD lock_error = GetLastError();
            if (lock_error != ERROR_FILE_EXISTS && lock_error != ERROR_ALREADY_EXISTS) {
                throw std::runtime_error("unable to acquire prepared voice publication lock");
            }
            const HANDLE probe = CreateFileW(
                path_.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
            if (probe == INVALID_HANDLE_VALUE) {
                throw std::runtime_error("prepared voice publication is active in another worker");
            }
            CloseHandle(probe);
            if (!DeleteFileW(path_.c_str())) {
                throw std::runtime_error("unable to remove stale prepared voice publication lock");
            }
        }
        throw std::runtime_error("prepared voice publication lock is contended");
    }

    PublicationLock(const PublicationLock&) = delete;
    PublicationLock& operator=(const PublicationLock&) = delete;

    ~PublicationLock() {
        if (handle_ != INVALID_HANDLE_VALUE) {
            CloseHandle(handle_);
            DeleteFileW(path_.c_str());
        }
    }

private:
    std::filesystem::path path_;
    HANDLE handle_ = INVALID_HANDLE_VALUE;
};

Json read_publication_marker(const std::filesystem::path& marker) {
    const auto bytes = read_bounded_text_file(marker, 16u * 1024u);
    Json value;
    try {
        value = Json::parse(bytes);
    }
    catch (const std::exception& error) {
        throw std::runtime_error(std::string("invalid prepared voice publication marker: ") + error.what());
    }
    if (!value.is_object() || value.value("schema_version", 0) != 1 ||
        value.value("format", std::string{}) != "qwen3-tts-native-publication" ||
        !is_safe_generation_id(value.value("generation_id", std::string{}))) {
        throw std::runtime_error("invalid prepared voice publication marker");
    }
    return value;
}

void recover_incomplete_publication_locked(
    const std::filesystem::path& directory,
    const std::filesystem::path& manifest_path) {
    const auto marker_path = publication_marker_path(directory);
    if (!std::filesystem::exists(marker_path)) {
        return;
    }
    const Json marker = read_publication_marker(marker_path);
    const std::string generation = marker.at("generation_id").get<std::string>();
    const auto speaker_name = marker.value("speaker_path", std::string{});
    const auto rvq_name = marker.value("rvq_path", std::string{});
    const auto marker_manifest = marker.value("manifest_path", std::string{});
    if (marker_manifest != manifest_path.filename().u8string() ||
        speaker_name != "reference-" + generation + ".spk" ||
        (!rvq_name.empty() && rvq_name != "reference-" + generation + ".rvq")) {
        throw std::runtime_error("prepared voice publication marker conflicts with target");
    }
    if (std::filesystem::exists(manifest_path)) {
        // The manifest is the commit boundary. The caller validates it before
        // removing this stale marker, so a crash cannot trigger regeneration.
        return;
    }

    std::error_code error;
    const auto quarantine = directory / (".qtb-recovery-" + generation);
    if (std::filesystem::exists(quarantine)) {
        throw std::runtime_error("prepared voice recovery directory already exists");
    }
    std::filesystem::create_directory(quarantine, error);
    if (error) {
        throw std::runtime_error("unable to create prepared voice recovery directory");
    }
    const auto move_owned = [&](const std::string& name) {
        if (name.empty()) {
            return;
        }
        const auto source = directory / name;
        if (!std::filesystem::exists(source)) {
            return;
        }
        const auto target = quarantine / name;
        if (std::filesystem::exists(target)) {
            throw std::runtime_error("prepared voice recovery target already exists");
        }
        std::filesystem::rename(source, target, error);
        if (error) {
            throw std::runtime_error("unable to quarantine incomplete prepared voice artifact");
        }
    };
    move_owned(speaker_name);
    move_owned(rvq_name);
    move_owned("reference-" + generation + ".spk.qtb-tmp");
    move_owned("reference-" + generation + ".rvq.qtb-tmp");
    move_owned(manifest_path.filename().u8string() + ".qtb-tmp-" + generation);
    std::filesystem::rename(marker_path, quarantine / marker_path.filename(), error);
    if (error) {
        throw std::runtime_error("unable to quarantine prepared voice publication marker");
    }
}

void maybe_inject_publication_failure(const char* phase) {
    const char* configured = std::getenv("QTB_TEST_PUBLICATION_FAILURE_PHASE");
    if (configured != nullptr && std::string(configured) == phase) {
        throw std::runtime_error(std::string("injected publication interruption at ") + phase);
    }
}

void maybe_delay_publication(const char* phase) {
    const char* configured_phase = std::getenv("QTB_TEST_PUBLICATION_DELAY_PHASE");
    const char* configured_ms = std::getenv("QTB_TEST_PUBLICATION_DELAY_MS");
    if (configured_phase == nullptr || configured_ms == nullptr ||
        std::string(configured_phase) != phase) {
        return;
    }
    const auto delay = std::strtoul(configured_ms, nullptr, 10);
    if (delay > 0 && delay <= 30000) {
        Sleep(static_cast<DWORD>(delay));
    }
}

void maybe_terminate_publication(const char* phase) {
    const char* configured = std::getenv("QTB_TEST_PUBLICATION_TERMINATE_PHASE");
    if (configured != nullptr && std::string(configured) == phase) {
        TerminateProcess(GetCurrentProcess(), 70);
    }
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

void reconcile_prepared_publication(const PreparedVoiceReferenceContext& context) {
    const auto directory = context.manifest_path.parent_path();
    if (!std::filesystem::exists(publication_marker_path(directory))) {
        return;
    }
    PublicationLock lock(directory);
    recover_incomplete_publication_locked(directory, context.manifest_path);
}

void finalize_prepared_publication(const PreparedVoiceReferenceContext& context) {
    const auto directory = context.manifest_path.parent_path();
    if (!std::filesystem::exists(publication_marker_path(directory))) {
        return;
    }
    PublicationLock lock(directory);
    if (!std::filesystem::exists(context.manifest_path)) {
        throw std::runtime_error("prepared voice publication manifest disappeared during reconciliation");
    }
    recover_incomplete_publication_locked(directory, context.manifest_path);
    remove_if_exists(publication_marker_path(directory));
}

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
    Json root;
    try {
        const auto manifest_bytes = read_bounded_text_file(context.manifest_path, kMaxManifestBytes);
        root = Json::parse(manifest_bytes);
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
        required_integer(preprocessing, "icl_trailing_silence_samples") != expected_silence ||
        required_string(preprocessing, "sample_format") != "float32") {
        throw std::runtime_error("prepared voice preprocessing identity mismatch");
    }

    const auto& speaker = root.at("speaker");
    const int speaker_dim = required_integer(speaker, "dimension");
    const auto speaker_size = required_size(speaker, "size_bytes");
    if (speaker_dim <= 0 || speaker_dim > kMaxSpeakerDimension ||
        static_cast<std::uintmax_t>(speaker_dim) >
            (std::numeric_limits<std::uintmax_t>::max)() / sizeof(float) ||
        speaker_size != static_cast<std::uintmax_t>(speaker_dim) * sizeof(float) ||
        speaker_size > kMaxSpeakerBytes) {
        throw std::runtime_error("prepared voice speaker dimensions are invalid");
    }
    if (required_string(speaker, "scalar") != "float32-le") {
        throw std::runtime_error("prepared voice speaker scalar is unsupported");
    }
    const auto speaker_path = artifact_path(context.manifest_path, required_string(speaker, "path"));
    const auto speaker_bytes = read_bounded_file(speaker_path, speaker_size, kMaxSpeakerBytes);
    if (sha256_bytes(speaker_bytes.data(), speaker_bytes.size()) != required_string(speaker, "sha256")) {
        throw std::runtime_error("prepared voice speaker SHA-256 mismatch");
    }

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
        if (codebooks != context.num_codebooks || codebooks <= 0 ||
            codebooks > kMaxRvqCodebooks || frames <= 0 || frames > kMaxRvqFrames ||
            bits != kRvqCodeBits ||
            required_string(*rvq, "layout") != "codebook-major-frame-fastest") {
            throw std::runtime_error("prepared voice RVQ layout is incompatible");
        }
        if (static_cast<std::size_t>(codebooks) >
            (std::numeric_limits<std::size_t>::max)() / static_cast<std::size_t>(frames)) {
            throw std::runtime_error("prepared voice RVQ dimensions are too large");
        }
        const std::size_t code_count = static_cast<std::size_t>(codebooks) *
            static_cast<std::size_t>(frames);
        if (code_count > (std::numeric_limits<std::size_t>::max)() / kRvqCodeBits) {
            throw std::runtime_error("prepared voice RVQ dimensions are too large");
        }
        const std::uintmax_t expected_bytes = (code_count * kRvqCodeBits + 7u) / 8u;
        const auto rvq_size = required_size(*rvq, "size_bytes");
        if (rvq_size != expected_bytes || rvq_size > kMaxRvqBytes) {
            throw std::runtime_error("prepared voice RVQ size is invalid");
        }
        const auto rvq_path = artifact_path(context.manifest_path, required_string(*rvq, "path"));
        const auto rvq_bytes = read_bounded_file(rvq_path, rvq_size, kMaxRvqBytes);
        if (sha256_bytes(rvq_bytes.data(), rvq_bytes.size()) != required_string(*rvq, "sha256")) {
            throw std::runtime_error("prepared voice RVQ SHA-256 mismatch");
        }
        result.codes = unpack_codes(rvq_bytes, code_count);
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
    // Deterministic fault injection keeps the DLL-owned extraction cleanup
    // path testable without changing the public ABI. This is intentionally
    // ignored unless a test explicitly opts in through the environment.
    if (std::getenv("QTB_TEST_PERSISTENCE_FAILURE") != nullptr) {
        throw std::runtime_error("injected prepared voice persistence failure");
    }
    if (extracted.ref_spk_emb == nullptr || extracted.ref_spk_dim <= 0 ||
        extracted.ref_spk_dim > kMaxSpeakerDimension ||
        static_cast<std::size_t>(extracted.ref_spk_dim) >
            (std::numeric_limits<std::size_t>::max)() / sizeof(float) ||
        static_cast<std::uintmax_t>(extracted.ref_spk_dim) * sizeof(float) > kMaxSpeakerBytes ||
        std::any_of(extracted.ref_spk_emb, extracted.ref_spk_emb + extracted.ref_spk_dim,
                    [](float value) { return !std::isfinite(value); })) {
        throw std::runtime_error("extracted speaker embedding is invalid");
    }
    if (!context.x_vector_only &&
        (extracted.ref_codes == nullptr || extracted.ref_T <= 0 ||
         extracted.ref_T > kMaxRvqFrames || extracted.num_codebooks <= 0 ||
         extracted.num_codebooks > kMaxRvqCodebooks ||
         extracted.num_codebooks != context.num_codebooks ||
         static_cast<std::size_t>(extracted.num_codebooks) >
             (std::numeric_limits<std::size_t>::max)() /
                 static_cast<std::size_t>(extracted.ref_T))) {
        throw std::runtime_error("extracted RVQ layout is invalid");
    }

    const auto directory = context.manifest_path.parent_path();
    reject_reparse_ancestors(directory.parent_path());
    std::filesystem::create_directories(directory);
    reject_reparse_ancestors(directory);
    PublicationLock publication_lock(directory);
    recover_incomplete_publication_locked(directory, context.manifest_path);
    if (std::filesystem::exists(context.manifest_path) ||
        std::filesystem::exists(directory / "reference.spk") ||
        std::filesystem::exists(directory / "reference.rvq")) {
        throw std::runtime_error("refusing to overwrite an existing prepared voice publication");
    }

    const auto generation = new_generation_id();
    const auto speaker_name = "reference-" + generation + ".spk";
    const auto rvq_name = "reference-" + generation + ".rvq";
    const auto speaker_path = directory / speaker_name;
    const auto rvq_path = directory / rvq_name;
    const auto speaker_temp = directory / (speaker_name + ".qtb-tmp");
    const auto rvq_temp = directory / (rvq_name + ".qtb-tmp");
    const auto manifest_temp = directory / (context.manifest_path.filename().u8string() + ".qtb-tmp-" + generation);
    const auto marker = publication_marker_path(directory);
    const auto marker_temp = directory / (".qtb-publication.incomplete.qtb-tmp-" + generation);
    bool speaker_published = false;
    bool rvq_published = false;
    try {
        const Json marker_json = {
            {"schema_version", 1},
            {"format", "qwen3-tts-native-publication"},
            {"generation_id", generation},
            {"manifest_path", context.manifest_path.filename().u8string()},
            {"speaker_path", speaker_name},
            {"rvq_path", context.x_vector_only ? std::string{} : rvq_name},
        };
        const std::string marker_text = marker_json.dump() + "\n";
        write_bytes(marker_temp, marker_text.data(), marker_text.size());
        std::filesystem::rename(marker_temp, marker);
        maybe_delay_publication("after-marker");
        maybe_terminate_publication("after-marker");
        maybe_inject_publication_failure("before-speaker");
        const auto speaker_bytes = static_cast<std::size_t>(extracted.ref_spk_dim) * sizeof(float);
        write_bytes(speaker_temp, extracted.ref_spk_emb, speaker_bytes);
        maybe_inject_publication_failure("after-temp-speaker");

        std::vector<std::int32_t> codes;
        std::vector<unsigned char> packed_codes;
        if (!context.x_vector_only) {
            const auto count = static_cast<std::size_t>(extracted.num_codebooks) *
                static_cast<std::size_t>(extracted.ref_T);
            codes.assign(extracted.ref_codes, extracted.ref_codes + count);
            packed_codes = pack_codes(codes);
            write_bytes(rvq_temp, packed_codes.data(), packed_codes.size());
            maybe_inject_publication_failure("after-temp-rvq");
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
                {"path", speaker_name},
                {"dimension", extracted.ref_spk_dim},
                {"size_bytes", speaker_bytes},
                {"sha256", sha256_file(speaker_temp)},
                {"scalar", "float32-le"},
            }},
            {"rvq", nullptr},
        };
        if (!context.x_vector_only) {
            root["rvq"] = {
                {"path", rvq_name},
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
        maybe_terminate_publication("after-publish-speaker");
        maybe_inject_publication_failure("after-publish-speaker");
        if (!context.x_vector_only) {
            std::filesystem::rename(rvq_temp, rvq_path);
            rvq_published = true;
            maybe_inject_publication_failure("after-publish-rvq");
        }
        maybe_inject_publication_failure("before-manifest");
        std::filesystem::rename(manifest_temp, context.manifest_path);
        maybe_terminate_publication("after-manifest");
        maybe_inject_publication_failure("after-manifest");
        remove_if_exists(marker);
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
        remove_if_exists(marker_temp);
        remove_if_exists(marker);
        throw;
    }
    return load_prepared_voice_reference(context);
}

} // namespace qwen_tts_bridge::native_worker
