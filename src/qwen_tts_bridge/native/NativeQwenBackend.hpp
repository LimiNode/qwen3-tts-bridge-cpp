#pragma once

/// \file NativeQwenBackend.hpp
/// \brief Optional adapter for the qwentts.cpp shared C ABI.

#include <cstddef>
#include <cstdint>
#include <functional>
#include <string>
#include <vector>

namespace qwen_tts_bridge::native {

/// \struct NativeQwenBackendOptions
/// \brief GGUF paths and initialization switches for the native backend.
struct NativeQwenBackendOptions {
    std::string talker_path; ///< Qwen Talker GGUF path.
    std::string codec_path; ///< Qwen 12 Hz tokenizer GGUF path.
    bool use_flash_attention = true; ///< Enable GGML fused attention when available.
    bool clamp_fp16 = false; ///< Guard FP16 residuals on older CUDA devices.
};

/// \struct NativeQwenSynthesisRequest
/// \brief Model-facing request accepted by the native adapter.
struct NativeQwenSynthesisRequest {
    std::string text; ///< Spoken UTF-8 text.
    std::string language = "auto"; ///< Qwen language hint.
    std::string instruction; ///< Voice-design/style instruction.
    std::string speaker; ///< CustomVoice speaker name.
    const float* reference_audio_24k = nullptr; ///< Optional Base reference PCM.
    int reference_audio_samples = 0; ///< Number of reference PCM samples.
    std::string reference_text; ///< Optional Base ICL transcript.
    std::int64_t seed = -1; ///< -1 lets the engine choose a random seed.
    int max_new_tokens = 2048; ///< Maximum Talker frames/tokens.
};

/// \struct NativeQwenAudio
/// \brief Buffered mono float PCM returned by the native engine.
struct NativeQwenAudio {
    std::vector<float> samples; ///< 24 kHz mono PCM samples.
    int sample_rate = 24000; ///< Output sample rate in Hz.
    int channels = 1; ///< Output channel count.
};

/// \class NativeQwenBackend
/// \brief Thin, opt-in C++17 wrapper over qwentts.cpp's C ABI.
///
/// This class is available only when CMake is configured with
/// `-DQWEN_TTS_BRIDGE_BUILD_NATIVE_BACKEND=ON`. It does not replace the
/// persistent Python worker or the public async bridge client. The native
/// engine owns a GGML context and `synthesize()` is blocking; applications
/// that need async behavior should call it from their own worker thread.
class NativeQwenBackend final {
public:
    using AudioChunkCallback = std::function<bool(const float*, std::size_t)>;
    using CancelCallback = std::function<bool()>;

    explicit NativeQwenBackend(const NativeQwenBackendOptions& options);
    ~NativeQwenBackend();

    NativeQwenBackend(const NativeQwenBackend&) = delete;
    NativeQwenBackend& operator=(const NativeQwenBackend&) = delete;

    /// \brief Returns whether GGUF initialization succeeded.
    [[nodiscard]] bool is_ready() const noexcept;

    /// \brief Returns the initialization or most recent synthesis error.
    [[nodiscard]] const std::string& last_error() const noexcept;

    /// \brief Returns the exact qwentts.cpp build identity.
    [[nodiscard]] std::string version() const;

    /// \brief Runs one buffered or streaming synthesis request.
    /// \param request Native model request.
    /// \param on_chunk Optional callback; returning false cancels generation.
    /// \param cancel Optional cooperative cancellation callback.
    /// \param output Buffered output when `on_chunk` is empty.
    /// \return True when the engine reports QT_STATUS_OK.
    bool synthesize(
        const NativeQwenSynthesisRequest& request,
        AudioChunkCallback on_chunk = {},
        CancelCallback cancel = {},
        NativeQwenAudio* output = nullptr);

private:
    struct Impl;
    Impl* impl_ = nullptr;
};

} // namespace qwen_tts_bridge::native
