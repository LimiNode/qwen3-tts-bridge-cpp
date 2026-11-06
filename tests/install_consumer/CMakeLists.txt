cmake_minimum_required(VERSION 3.16)
project(QwenTTSBridgeInstallConsumer LANGUAGES CXX)
find_package(QwenTTSBridge CONFIG REQUIRED)
option(QWEN_TTS_BRIDGE_INSTALL_CONSUMER_USE_WINMM
    "Exercise the optional installed WinMM playback target" OFF)
option(QWEN_TTS_BRIDGE_INSTALL_CONSUMER_USE_TTS_FRONT
    "Exercise the optional installed tts-front-cpp adapter" OFF)
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
if(QWEN_TTS_BRIDGE_INSTALL_CONSUMER_USE_TTS_FRONT)
    if(NOT TARGET QwenTTSBridge::qwen_tts_bridge_tts_front)
        message(FATAL_ERROR
            "The installed package does not export the optional text frontend target")
    endif()
    target_compile_definitions(qwen_tts_bridge_install_consumer
        PRIVATE QWEN_TTS_BRIDGE_INSTALL_CONSUMER_USE_TTS_FRONT=1)
    target_link_libraries(qwen_tts_bridge_install_consumer
        PRIVATE QwenTTSBridge::qwen_tts_bridge_tts_front)
endif()

# Compile the new installed entry points separately, not after main.cpp's
# other umbrellas; missing installed dependencies must not be masked.
set(_entry_headers qwen_tts_bridge/transport/stdio.hpp)
if(QWEN_TTS_BRIDGE_INSTALL_CONSUMER_USE_WINMM)
    list(APPEND _entry_headers
        qwen_tts_bridge/playback/winmm.hpp
        qwen_tts_bridge/playback/winmm_playback.hpp)
endif()
foreach(_header IN LISTS _entry_headers)
    string(REPLACE "/" "_" _stem "${_header}")
    set(_source "${CMAKE_CURRENT_BINARY_DIR}/${_stem}.cpp")
    file(WRITE "${_source}" "#include <${_header}>\n")
    target_sources(qwen_tts_bridge_install_consumer PRIVATE "${_source}")
endforeach()
