#pragma once

#include <filesystem>
#include <vector>

namespace qwen_tts_bridge::native_worker {

std::vector<float> read_mono_24k_wav(const std::filesystem::path& path);

} // namespace qwen_tts_bridge::native_worker
