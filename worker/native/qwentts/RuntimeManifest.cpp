#include "RuntimeManifest.hpp"

#include <nlohmann/json.hpp>

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>

#include <array>
#include <cctype>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <stdexcept>

namespace qwen_tts_bridge::native_worker {
namespace {

using Json = nlohmann::json;

std::string sha256_file(const std::filesystem::path& path) {
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    BCRYPT_HASH_HANDLE hash = nullptr;
    DWORD object_size = 0;
    DWORD hash_size = 0;
    DWORD written = 0;
    std::vector<unsigned char> object;
    std::vector<unsigned char> digest;

    const auto cleanup = [&]() {
        if (hash != nullptr) {
            BCryptDestroyHash(hash);
        }
        if (algorithm != nullptr) {
            BCryptCloseAlgorithmProvider(algorithm, 0);
        }
    };

    if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) < 0 ||
        BCryptGetProperty(
            algorithm,
            BCRYPT_OBJECT_LENGTH,
            reinterpret_cast<PUCHAR>(&object_size),
            sizeof(object_size),
            &written,
            0) < 0 ||
        BCryptGetProperty(
            algorithm,
            BCRYPT_HASH_LENGTH,
            reinterpret_cast<PUCHAR>(&hash_size),
            sizeof(hash_size),
            &written,
            0) < 0) {
        cleanup();
        throw std::runtime_error("unable to initialize SHA-256 verification");
    }

    object.resize(object_size);
    digest.resize(hash_size);
    if (BCryptCreateHash(
            algorithm,
            &hash,
            object.data(),
            static_cast<ULONG>(object.size()),
            nullptr,
            0,
            0) < 0) {
        cleanup();
        throw std::runtime_error("unable to create SHA-256 verifier");
    }

    std::ifstream input(path, std::ios::binary);
    if (!input) {
        cleanup();
        throw std::runtime_error("runtime file is missing: " + path.string());
    }

    std::array<char, 64 * 1024> buffer{};
    while (input) {
        input.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
        const auto count = input.gcount();
        if (count > 0 && BCryptHashData(
                hash,
                reinterpret_cast<PUCHAR>(buffer.data()),
                static_cast<ULONG>(count),
                0) < 0) {
            cleanup();
            throw std::runtime_error("unable to hash runtime file: " + path.string());
        }
    }
    if (!input.eof()) {
        cleanup();
        throw std::runtime_error("unable to read runtime file: " + path.string());
    }
    if (BCryptFinishHash(hash, digest.data(), static_cast<ULONG>(digest.size()), 0) < 0) {
        cleanup();
        throw std::runtime_error("unable to finish SHA-256 verification");
    }
    cleanup();

    std::ostringstream out;
    out << std::hex << std::setfill('0');
    for (const unsigned char byte : digest) {
        out << std::setw(2) << static_cast<unsigned int>(byte);
    }
    return out.str();
}

std::string lower_ascii(std::string value) {
    for (char& ch : value) {
        ch = static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
    }
    return value;
}

std::string required_string(const Json& object, const char* name) {
    const auto it = object.find(name);
    if (it == object.end() || !it->is_string() || it->get_ref<const std::string&>().empty()) {
        throw std::runtime_error(std::string("runtime manifest requires non-empty ") + name);
    }
    return it->get<std::string>();
}

int required_integer(const Json& object, const char* name) {
    const auto it = object.find(name);
    if (it == object.end() || !it->is_number_integer()) {
        throw std::runtime_error(std::string("runtime manifest requires integer ") + name);
    }
    return it->get<int>();
}

bool is_safe_relative_path(const std::filesystem::path& path) {
    if (path.empty() || path.is_absolute()) {
        return false;
    }
    for (const auto& part : path) {
        if (part == "..") {
            return false;
        }
    }
    return true;
}

} // namespace

RuntimeManifest load_and_verify_runtime_manifest(
    const std::filesystem::path& manifest_path,
    const std::filesystem::path& dll_path) {
    std::ifstream input(manifest_path, std::ios::binary);
    if (!input) {
        throw std::runtime_error("qwentts runtime manifest is missing: " + manifest_path.string());
    }

    Json root;
    try {
        input >> root;
    }
    catch (const std::exception& error) {
        throw std::runtime_error(std::string("invalid qwentts runtime manifest: ") + error.what());
    }
    if (!root.is_object()) {
        throw std::runtime_error("qwentts runtime manifest must be a JSON object");
    }

    RuntimeManifest manifest;
    manifest.schema_version = required_integer(root, "schema_version");
    manifest.engine = required_string(root, "engine");
    manifest.engine_commit = required_string(root, "engine_commit");
    manifest.qt_abi_version = required_integer(root, "qt_abi_version");
    manifest.architecture = required_string(root, "architecture");
    manifest.backend = required_string(root, "backend");

    if (manifest.schema_version != 1) {
        throw std::runtime_error("unsupported qwentts runtime manifest schema_version");
    }
    if (manifest.engine != "qwentts.cpp") {
        throw std::runtime_error("runtime manifest engine must be qwentts.cpp");
    }
    if (manifest.qt_abi_version != QT_ABI_VERSION) {
        throw std::runtime_error(
            "qwentts ABI mismatch: worker expects " + std::to_string(QT_ABI_VERSION) +
            ", runtime declares " + std::to_string(manifest.qt_abi_version));
    }
    if (lower_ascii(manifest.architecture) != "x64" || sizeof(void*) != 8) {
        throw std::runtime_error("qwentts runtime architecture must be x64");
    }

    const auto files_it = root.find("files");
    if (files_it == root.end() || !files_it->is_array() || files_it->empty()) {
        throw std::runtime_error("runtime manifest requires a non-empty files array");
    }

    const auto root_dir = std::filesystem::weakly_canonical(manifest_path.parent_path());
    const auto expected_dll = std::filesystem::weakly_canonical(dll_path);
    bool dll_declared = false;
    for (const Json& item : *files_it) {
        if (!item.is_object()) {
            throw std::runtime_error("runtime manifest files entries must be objects");
        }
        RuntimeFile file;
        file.path = std::filesystem::u8path(required_string(item, "path"));
        file.sha256 = lower_ascii(required_string(item, "sha256"));
        if (!is_safe_relative_path(file.path) || file.sha256.size() != 64) {
            throw std::runtime_error("runtime manifest contains an invalid file entry");
        }

        const auto absolute_path = std::filesystem::weakly_canonical(root_dir / file.path);
        const auto relative = absolute_path.lexically_relative(root_dir);
        if (!is_safe_relative_path(relative)) {
            throw std::runtime_error("runtime manifest file escapes the runtime directory");
        }
        const std::string actual_hash = sha256_file(absolute_path);
        if (actual_hash != file.sha256) {
            throw std::runtime_error("runtime file SHA-256 mismatch: " + file.path.string());
        }
        if (absolute_path == expected_dll) {
            dll_declared = true;
        }
        manifest.files.push_back(std::move(file));
    }
    if (!dll_declared) {
        throw std::runtime_error("runtime manifest does not declare the selected qwen.dll");
    }
    return manifest;
}

} // namespace qwen_tts_bridge::native_worker
