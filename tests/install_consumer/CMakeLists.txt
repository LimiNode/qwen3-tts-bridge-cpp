cmake_minimum_required(VERSION 3.16)
project(QwenTTSBridgeInstallConsumer LANGUAGES CXX)
find_package(QwenTTSBridge CONFIG REQUIRED)
option(QWEN_TTS_BRIDGE_INSTALL_CONSUMER_USE_WINMM
    "Exercise the optional installed WinMM playback target" OFF)
add_executable(qwen_tts_bridge_install_consumer main.cpp)
target_link_libraries(qwen_tts_bridge_install_consumer PRIVATE QwenTTSBridge::qwen_tts_bridge)
if(QWEN_TTS_BRIDGE_INSTALL_CONSUMER_USE_WINMM)
    if(NOT TARGET QwenTTSBridge::qwen_tts_bridge_winmm_playback)
        message(FATAL_ERROR
            "The installed package does not export the optional WinMM playback target")
    endif()
    target_compile_definitions(qwen_tts_bridge_install_consumer
        PRIVATE QWEN_TTS_BRIDGE_INSTALL_CONSUMER_USE_WINMM=1)
    target_link_libraries(qwen_tts_bridge_install_consumer
        PRIVATE QwenTTSBridge::qwen_tts_bridge_winmm_playback)
endif()
