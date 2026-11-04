cmake_minimum_required(VERSION 3.16)
project(QwenTTSBridgeWrapperGuardFixture LANGUAGES CXX)

set(QWEN_TTS_BRIDGE_SOURCE_ROOT "" CACHE PATH "Bridge source root")
if(NOT QWEN_TTS_BRIDGE_SOURCE_ROOT)
    message(FATAL_ERROR "QWEN_TTS_BRIDGE_SOURCE_ROOT is required")
endif()
include("${QWEN_TTS_BRIDGE_SOURCE_ROOT}/cmake/qwen_tts_bridge_wrapper_guard.cmake")

add_library(duplicate_wrapper STATIC
    src/qwen_tts_bridge/fixture_domain/fixture_wrapper.cpp
    src/qwen_tts_bridge/fixture_impl.cpp)
qwen_tts_bridge_validate_wrapper_sources(
    duplicate_wrapper
    "${CMAKE_CURRENT_SOURCE_DIR}")
