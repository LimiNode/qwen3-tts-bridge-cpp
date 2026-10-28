#pragma once

#include <filesystem>
#include <string>
#include <vector>

#include <qwen.h>

namespace qwen_tts_bridge::native_worker {

struct RuntimeFile {
    std::filesystem::path path;
    std::string sha256;
};

struct RuntimeManifest {
    int schema_version = 0;
    std::string engine;
    std::string engine_commit;
    int qt_abi_version = 0;
    std::string architecture;
    std::string backend;
    std::vector<RuntimeFile> files;
};

/// Return the lowercase SHA-256 digest of a regular file.
std::string sha256_file(const std::filesystem::path& path);

RuntimeManifest load_and_verify_runtime_manifest(
    const std::filesystem::path& manifest_path,
    const std::filesystem::path& dll_path);

} // namespace qwen_tts_bridge::native_worker
