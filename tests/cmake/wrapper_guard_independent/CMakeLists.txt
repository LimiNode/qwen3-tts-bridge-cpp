cmake_minimum_required(VERSION 3.16)
project(QwenTTSBridgeWrapperGuardPositiveFixture LANGUAGES CXX)

set(QWEN_TTS_BRIDGE_SOURCE_ROOT "" CACHE PATH "Bridge source root")
if(NOT QWEN_TTS_BRIDGE_SOURCE_ROOT)
    message(FATAL_ERROR "QWEN_TTS_BRIDGE_SOURCE_ROOT is required")
endif()
include("${QWEN_TTS_BRIDGE_SOURCE_ROOT}/cmake/qwen_tts_bridge_wrapper_guard.cmake")

add_library(independent_wrapper_a STATIC
    src/qwen_tts_bridge/fixture_domain/fixture_wrapper.cpp)
add_library(independent_wrapper_b STATIC
    src/qwen_tts_bridge/fixture_domain/fixture_wrapper.cpp)
qwen_tts_bridge_validate_wrapper_sources(
    independent_wrapper_a
    "${CMAKE_CURRENT_SOURCE_DIR}")
qwen_tts_bridge_validate_wrapper_sources(
    independent_wrapper_b
    "${CMAKE_CURRENT_SOURCE_DIR}")
