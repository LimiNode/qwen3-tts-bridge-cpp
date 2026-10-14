#include "winmm_playback.hpp"

namespace qwen_tts_bridge::playback {

// Keep a real translation unit for the optional target.  The player remains
// header-defined so the example can compile its optional speech-animation
// cursor specialization without coupling the reusable module to that target.
void winmm_playback_link_anchor() {}

} // namespace qwen_tts_bridge::playback
