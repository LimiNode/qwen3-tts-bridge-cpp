#include "NativeEngine.hpp"
#include "StdioServer.hpp"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <fcntl.h>
#include <io.h>

#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {

using qwen_tts_bridge::native_worker::NativeEngineOptions;

std::string wide_to_utf8(const std::wstring& value) {
    if (value.empty()) {
        return {};
    }
    const int size = WideCharToMultiByte(
        CP_UTF8,
        WC_ERR_INVALID_CHARS,
        value.data(),
        static_cast<int>(value.size()),
        nullptr,
        0,
        nullptr,
        nullptr);
    if (size <= 0) {
        throw std::runtime_error("unable to convert a command-line argument to UTF-8");
    }
    std::string result(static_cast<std::size_t>(size), '\0');
    if (WideCharToMultiByte(
            CP_UTF8,
            WC_ERR_INVALID_CHARS,
            value.data(),
            static_cast<int>(value.size()),
            result.data(),
            size,
            nullptr,
            nullptr) != size) {
        throw std::runtime_error("unable to convert a command-line argument to UTF-8");
    }
    return result;
}

std::filesystem::path require_value(int& index, int argc, wchar_t** argv, const wchar_t* option) {
    if (++index >= argc) {
        throw std::invalid_argument(wide_to_utf8(option) + " requires a value");
    }
    return std::filesystem::path(argv[index]);
}

NativeEngineOptions parse_arguments(int argc, wchar_t** argv) {
    NativeEngineOptions options;
    std::filesystem::path runtime_dir;

    for (int index = 1; index < argc; ++index) {
        const std::wstring argument = argv[index];
        if (argument == L"--runtime-dir") {
            runtime_dir = require_value(index, argc, argv, L"--runtime-dir");
        }
        else if (argument == L"--dll-path") {
            options.dll_path = require_value(index, argc, argv, L"--dll-path");
        }
        else if (argument == L"--manifest-path") {
            options.manifest_path = require_value(index, argc, argv, L"--manifest-path");
        }
        else if (argument == L"--talker-model") {
            options.talker_model = require_value(index, argc, argv, L"--talker-model");
        }
        else if (argument == L"--codec-model") {
            options.codec_model = require_value(index, argc, argv, L"--codec-model");
        }
        else if (argument == L"--no-flash-attention") {
            options.use_flash_attention = false;
        }
        else if (argument == L"--clamp-fp16") {
            options.clamp_fp16 = true;
        }
        else if (argument == L"--max-batch") {
            const auto value = require_value(index, argc, argv, L"--max-batch");
            options.max_batch = std::stoi(value.wstring());
        }
        else if (argument == L"--codec-chunk-sec") {
            const auto value = require_value(index, argc, argv, L"--codec-chunk-sec");
            options.codec_chunk_seconds = std::stof(value.wstring());
        }
        else if (argument == L"--stream-max-chunk-frames") {
            const auto value = require_value(index, argc, argv, L"--stream-max-chunk-frames");
            options.stream_max_chunk_frames = std::stoi(value.wstring());
        }
        else if (argument == L"--max-new-tokens") {
            const auto value = require_value(index, argc, argv, L"--max-new-tokens");
            options.max_new_tokens = std::stoi(value.wstring());
        }
        else if (argument == L"--help" || argument == L"-h") {
            std::cerr
                << "qwen_tts_native_worker --runtime-dir DIR --talker-model FILE --codec-model FILE\n"
                << "  [--dll-path FILE] [--manifest-path FILE] [--no-flash-attention]\n"
                << "  [--clamp-fp16] [--max-batch N] [--codec-chunk-sec N]\n"
                << "  [--stream-max-chunk-frames N] [--max-new-tokens N]\n";
            std::exit(EXIT_SUCCESS);
        }
        else {
            throw std::invalid_argument("unknown argument: " + wide_to_utf8(argument));
        }
    }

    if (!runtime_dir.empty()) {
        if (options.dll_path.empty()) {
            options.dll_path = runtime_dir / L"qwen.dll";
        }
        if (options.manifest_path.empty()) {
            options.manifest_path = runtime_dir / L"manifest.json";
        }
    }
    if (options.dll_path.empty()) {
        throw std::invalid_argument("--runtime-dir or --dll-path is required");
    }
    if (options.manifest_path.empty()) {
        options.manifest_path = options.dll_path.parent_path() / L"manifest.json";
    }
    if (options.talker_model.empty() || options.codec_model.empty()) {
        throw std::invalid_argument("--talker-model and --codec-model are required");
    }
    if (options.max_batch < 1 || options.max_batch > 64) {
        throw std::invalid_argument("--max-batch must be in [1, 64]");
    }
    if (!(options.codec_chunk_seconds > 0.0F) || options.codec_chunk_seconds > 3600.0F) {
        throw std::invalid_argument("--codec-chunk-sec must be in (0, 3600]");
    }
    if (options.stream_max_chunk_frames != 1 && options.stream_max_chunk_frames != 2 &&
        options.stream_max_chunk_frames != 4 && options.stream_max_chunk_frames != 8) {
        throw std::invalid_argument("--stream-max-chunk-frames must be one of 1, 2, 4 or 8");
    }
    if (options.max_new_tokens < 1 || options.max_new_tokens > 65536) {
        throw std::invalid_argument("--max-new-tokens must be in [1, 65536]");
    }
    return options;
}

} // namespace

int wmain(int argc, wchar_t** argv) {
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
    std::ios::sync_with_stdio(false);

    try {
        NativeEngineOptions options = parse_arguments(argc, argv);
        qwen_tts_bridge::native_worker::NativeEngine engine(std::move(options));
        engine.load();
        const auto& manifest = engine.manifest();
        std::cerr
            << "[native-worker:info] qwentts runtime ready"
            << " commit=" << manifest.engine_commit
            << " abi=" << manifest.qt_abi_version
            << " backend=" << manifest.backend
            << " version=\"" << engine.engine_version() << "\"\n";
        qwen_tts_bridge::native_worker::StdioServer server(engine);
        const int status = server.run();
        engine.close();
        return status;
    }
    catch (const std::exception& error) {
        std::cerr << "[native-worker:fatal] " << error.what() << '\n';
        return EXIT_FAILURE;
    }
}
