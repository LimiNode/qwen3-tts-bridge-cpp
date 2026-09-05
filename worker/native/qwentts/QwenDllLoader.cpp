#include "QwenDllLoader.hpp"

#include <sstream>
#include <stdexcept>

namespace qwen_tts_bridge::native_worker {
namespace {

std::string windows_error_message(DWORD code) {
    LPSTR message = nullptr;
    const DWORD size = FormatMessageA(
        FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM |
            FORMAT_MESSAGE_IGNORE_INSERTS,
        nullptr,
        code,
        0,
        reinterpret_cast<LPSTR>(&message),
        0,
        nullptr);
    std::string result = size != 0 && message != nullptr
        ? std::string(message, size)
        : std::string("Win32 error ") + std::to_string(code);
    if (message != nullptr) {
        LocalFree(message);
    }
    return result;
}

template <typename Function>
Function load_symbol(HMODULE module, const char* name) {
    const auto symbol = GetProcAddress(module, name);
    if (symbol == nullptr) {
        throw std::runtime_error(std::string("qwen.dll is missing required export: ") + name);
    }
    return reinterpret_cast<Function>(symbol);
}

} // namespace

QwenDllLoader::~QwenDllLoader() {
    unload();
}

void QwenDllLoader::load(
    const std::filesystem::path& dll_path,
    const std::filesystem::path& manifest_path) {
    if (module_ != nullptr) {
        throw std::runtime_error("qwen.dll is already loaded");
    }

    manifest_ = load_and_verify_runtime_manifest(manifest_path, dll_path);
    module_ = LoadLibraryExW(
        dll_path.c_str(),
        nullptr,
        LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    if (module_ == nullptr) {
        throw std::runtime_error(
            "unable to load qwen.dll: " + windows_error_message(GetLastError()));
    }

    try {
        api_.version = load_symbol<decltype(api_.version)>(module_, "qt_version");
        api_.last_error = load_symbol<decltype(api_.last_error)>(module_, "qt_last_error");
        api_.init_default_params = load_symbol<decltype(api_.init_default_params)>(module_, "qt_init_default_params");
        api_.init = load_symbol<decltype(api_.init)>(module_, "qt_init");
        api_.free = load_symbol<decltype(api_.free)>(module_, "qt_free");
        api_.tts_default_params = load_symbol<decltype(api_.tts_default_params)>(module_, "qt_tts_default_params");
        api_.synthesize = load_symbol<decltype(api_.synthesize)>(module_, "qt_synthesize");
        api_.audio_free = load_symbol<decltype(api_.audio_free)>(module_, "qt_audio_free");
        api_.num_codebooks = load_symbol<decltype(api_.num_codebooks)>(module_, "qt_num_codebooks");
        api_.n_speakers = load_symbol<decltype(api_.n_speakers)>(module_, "qt_n_speakers");
        api_.speaker_name = load_symbol<decltype(api_.speaker_name)>(module_, "qt_speaker_name");
        api_.duration_sec_to_tokens = load_symbol<decltype(api_.duration_sec_to_tokens)>(module_, "qt_duration_sec_to_tokens");
        api_.log_set = load_symbol<decltype(api_.log_set)>(module_, "qt_log_set");

        const char* version = api_.version();
        if (version == nullptr || *version == '\0') {
            throw std::runtime_error("qwen.dll returned an empty engine version");
        }
        engine_version_ = version;
    }
    catch (...) {
        unload();
        throw;
    }
}

void QwenDllLoader::unload() noexcept {
    api_ = {};
    engine_version_.clear();
    if (module_ != nullptr) {
        FreeLibrary(module_);
        module_ = nullptr;
    }
}

const QwenApi& QwenDllLoader::api() const {
    if (module_ == nullptr) {
        throw std::logic_error("qwen.dll is not loaded");
    }
    return api_;
}

const RuntimeManifest& QwenDllLoader::manifest() const {
    return manifest_;
}

const std::string& QwenDllLoader::engine_version() const {
    return engine_version_;
}

} // namespace qwen_tts_bridge::native_worker
