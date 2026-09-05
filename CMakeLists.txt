cmake_minimum_required(VERSION 3.16)

project(QwenTTSBridge
    VERSION 0.2.0
    DESCRIPTION "C++17 bridge for a persistent Qwen3-TTS worker"
    LANGUAGES CXX
)

option(QWEN_TTS_BRIDGE_BUILD_EXAMPLES "Build QwenTTSBridge examples" ON)
option(QWEN_TTS_BRIDGE_BUILD_TESTS "Build QwenTTSBridge tests" ON)
option(QWEN_TTS_BRIDGE_BUILD_NATIVE_BACKEND
    "Build the opt-in qwentts.cpp/GGML native backend adapter" OFF)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(QWEN_TTS_BRIDGE_SRC_DIR "${CMAKE_CURRENT_SOURCE_DIR}/src")
set(QWEN_TTS_BRIDGE_WORKER_DIR "${CMAKE_CURRENT_SOURCE_DIR}/worker/src")
set(QWEN_TTS_BRIDGE_EXTERNAL_CPP_DIR "${CMAKE_CURRENT_SOURCE_DIR}/external/cpp")
set(QWEN_TTS_BRIDGE_EXTERNAL_PYTHON_DIR "${CMAKE_CURRENT_SOURCE_DIR}/external/python")

if(QWEN_TTS_BRIDGE_BUILD_NATIVE_BACKEND)
    # qwentts.cpp is intentionally opt-in: its GGML graph and model format are
    # a separate runtime path and must not alter the accepted Python worker
    # build. The upstream project exposes the stable C ABI from its shared
    # `qwen` target when QWEN_SHARED is enabled.
    set(QWEN_SHARED ON CACHE BOOL
        "Build qwentts.cpp shared ABI library for the bridge" FORCE)
    add_subdirectory(
        "${QWEN_TTS_BRIDGE_EXTERNAL_CPP_DIR}/qwentts.cpp"
        "${CMAKE_CURRENT_BINARY_DIR}/qwentts.cpp"
        EXCLUDE_FROM_ALL
    )
    # qwentts.cpp's standalone CMake assumes its own binary directory is also
    # CMAKE_BINARY_DIR when locating the generated version.h. As a nested
    # subdirectory that assumption no longer holds, so restore the generated
    # include path for the ABI targets we consume.
    foreach(_qwentts_target qwen qwen-core)
        if(TARGET ${_qwentts_target})
            target_include_directories(${_qwentts_target}
                PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/qwentts.cpp")
        endif()
    endforeach()
endif()

add_subdirectory("${QWEN_TTS_BRIDGE_EXTERNAL_CPP_DIR}/tiny-process-library" EXCLUDE_FROM_ALL)
set(JSON_BuildTests OFF CACHE INTERNAL "")
add_subdirectory("${QWEN_TTS_BRIDGE_EXTERNAL_CPP_DIR}/nlohmann-json" EXCLUDE_FROM_ALL)

if(QWEN_TTS_BRIDGE_BUILD_EXAMPLES OR QWEN_TTS_BRIDGE_BUILD_TESTS)
    find_package(Python3 COMPONENTS Interpreter QUIET)
endif()

if(WIN32)
    target_compile_definitions(tiny-process-library
        PUBLIC
            UNICODE
            _UNICODE
    )
endif()

add_library(qwen_tts_bridge
    src/qwen_tts_bridge/audio/SaveWavCallbacks.cpp
    src/qwen_tts_bridge/audio/WavWriter.cpp
    src/qwen_tts_bridge/client/QwenTtsClient.cpp
    src/qwen_tts_bridge/protocol/control/ControlCodec.cpp
    src/qwen_tts_bridge/protocol/control/ControlDecode.cpp
    src/qwen_tts_bridge/protocol/control/ControlEncode.cpp
    src/qwen_tts_bridge/protocol/control/ControlJson.cpp
    src/qwen_tts_bridge/protocol/control/ControlValidation.cpp
    src/qwen_tts_bridge/protocol/control/ErrorCodec.cpp
    src/qwen_tts_bridge/protocol/framing/FrameCodec.cpp
    src/qwen_tts_bridge/protocol/framing/FrameParser.cpp
    src/qwen_tts_bridge/session/WorkerSession.cpp
    src/qwen_tts_bridge/transport/stdio/StdIoTransport.cpp
)
add_library(QwenTTSBridge::qwen_tts_bridge ALIAS qwen_tts_bridge)

target_compile_features(qwen_tts_bridge PUBLIC cxx_std_17)

target_include_directories(qwen_tts_bridge
    PUBLIC
        "${QWEN_TTS_BRIDGE_SRC_DIR}"
)

target_link_libraries(qwen_tts_bridge
    PRIVATE
        nlohmann_json::nlohmann_json
        tiny-process-library::tiny-process-library
)

if(QWEN_TTS_BRIDGE_BUILD_NATIVE_BACKEND)
    add_library(qwen_tts_bridge_native STATIC
        src/qwen_tts_bridge/native/NativeQwenBackend.cpp
    )
    add_library(QwenTTSBridge::qwen_tts_bridge_native ALIAS qwen_tts_bridge_native)
    target_compile_features(qwen_tts_bridge_native PUBLIC cxx_std_17)
    target_include_directories(qwen_tts_bridge_native
        PUBLIC
            "${QWEN_TTS_BRIDGE_SRC_DIR}"
        PRIVATE
            "${QWEN_TTS_BRIDGE_EXTERNAL_CPP_DIR}/qwentts.cpp/src"
    )
    target_link_libraries(qwen_tts_bridge_native
        PUBLIC
            qwen
    )
endif()

if(QWEN_TTS_BRIDGE_BUILD_EXAMPLES)
    set(QWEN_TTS_BRIDGE_EXAMPLE_PYTHON_EXECUTABLE "")
    if(Python3_Interpreter_FOUND)
        file(TO_CMAKE_PATH
            "${Python3_EXECUTABLE}"
            QWEN_TTS_BRIDGE_EXAMPLE_PYTHON_EXECUTABLE
        )
    endif()
    file(TO_CMAKE_PATH
        "${QWEN_TTS_BRIDGE_WORKER_DIR}"
        QWEN_TTS_BRIDGE_EXAMPLE_WORKER_DIR
    )

    add_executable(qwen_tts_save_wav
        examples/qwen_tts_save_wav.cpp
    )

    add_executable(qwen_tts_latency_benchmark
        examples/qwen_tts_latency_benchmark.cpp
    )

    if(WIN32)
        add_executable(qwen_tts_play
            examples/qwen_tts_play.cpp
        )
    endif()

    target_link_libraries(qwen_tts_save_wav
        PRIVATE
            QwenTTSBridge::qwen_tts_bridge
    )

    target_link_libraries(qwen_tts_latency_benchmark
        PRIVATE
            QwenTTSBridge::qwen_tts_bridge
            nlohmann_json::nlohmann_json
    )

    if(WIN32)
        target_link_libraries(qwen_tts_play
            PRIVATE
                QwenTTSBridge::qwen_tts_bridge
                winmm
        )
        if(MINGW)
            target_link_options(qwen_tts_play PRIVATE -municode)
        endif()
    endif()

    target_compile_definitions(qwen_tts_save_wav
        PRIVATE
            QWEN_TTS_BRIDGE_EXAMPLE_PYTHON_EXECUTABLE="${QWEN_TTS_BRIDGE_EXAMPLE_PYTHON_EXECUTABLE}"
            QWEN_TTS_BRIDGE_EXAMPLE_WORKER_DIR="${QWEN_TTS_BRIDGE_EXAMPLE_WORKER_DIR}"
    )

    target_compile_definitions(qwen_tts_latency_benchmark
        PRIVATE
            QWEN_TTS_BRIDGE_EXAMPLE_PYTHON_EXECUTABLE="${QWEN_TTS_BRIDGE_EXAMPLE_PYTHON_EXECUTABLE}"
            QWEN_TTS_BRIDGE_EXAMPLE_WORKER_DIR="${QWEN_TTS_BRIDGE_EXAMPLE_WORKER_DIR}"
    )

    if(WIN32)
        target_compile_definitions(qwen_tts_play
            PRIVATE
                QWEN_TTS_BRIDGE_EXAMPLE_PYTHON_EXECUTABLE="${QWEN_TTS_BRIDGE_EXAMPLE_PYTHON_EXECUTABLE}"
                QWEN_TTS_BRIDGE_EXAMPLE_WORKER_DIR="${QWEN_TTS_BRIDGE_EXAMPLE_WORKER_DIR}"
        )
    endif()
endif()

if(QWEN_TTS_BRIDGE_BUILD_TESTS)
    enable_testing()

    if(QWEN_TTS_BRIDGE_BUILD_NATIVE_BACKEND)
        add_executable(native_qwen_backend_abi_test
            tests/native_qwen_backend_abi_test.cpp
        )
        target_link_libraries(native_qwen_backend_abi_test
            PRIVATE
                QwenTTSBridge::qwen_tts_bridge_native
        )
        add_test(NAME native_qwen_backend_abi_test COMMAND native_qwen_backend_abi_test)
    endif()

    add_executable(protocol_frame_test
        tests/protocol_frame_test.cpp
    )

    target_link_libraries(protocol_frame_test
        PRIVATE
            QwenTTSBridge::qwen_tts_bridge
    )

    add_test(NAME protocol_frame_test COMMAND protocol_frame_test)

    add_executable(control_codec_test
        tests/control_codec_test.cpp
    )

    target_link_libraries(control_codec_test
        PRIVATE
            QwenTTSBridge::qwen_tts_bridge
    )

    add_test(NAME control_codec_test COMMAND control_codec_test)

    add_executable(qwen_tts_save_wav_callbacks_test
        tests/qwen_tts_save_wav_callbacks_test.cpp
    )

    target_link_libraries(qwen_tts_save_wav_callbacks_test
        PRIVATE
            QwenTTSBridge::qwen_tts_bridge
    )

    target_compile_definitions(qwen_tts_save_wav_callbacks_test
        PRIVATE
            QWEN_TTS_BRIDGE_TEST_OUTPUT_DIR="${CMAKE_CURRENT_BINARY_DIR}"
    )

    add_test(
        NAME qwen_tts_save_wav_callbacks_test
        COMMAND qwen_tts_save_wav_callbacks_test
    )

    if(Python3_Interpreter_FOUND)
        file(TO_CMAKE_PATH
            "${Python3_EXECUTABLE}"
            QWEN_TTS_BRIDGE_TEST_PYTHON_EXECUTABLE
        )
        file(TO_CMAKE_PATH
            "${QWEN_TTS_BRIDGE_WORKER_DIR}"
            QWEN_TTS_BRIDGE_TEST_WORKER_DIR
        )
        add_executable(stdio_transport_test
            tests/stdio_transport_test.cpp
        )

        target_link_libraries(stdio_transport_test
            PRIVATE
                QwenTTSBridge::qwen_tts_bridge
        )

        target_compile_definitions(stdio_transport_test
            PRIVATE
                QWEN_TTS_BRIDGE_TEST_PYTHON_EXECUTABLE="${QWEN_TTS_BRIDGE_TEST_PYTHON_EXECUTABLE}"
                QWEN_TTS_BRIDGE_TEST_WORKER_DIR="${QWEN_TTS_BRIDGE_TEST_WORKER_DIR}"
        )

        add_test(NAME stdio_transport_test COMMAND stdio_transport_test)
        set_tests_properties(stdio_transport_test PROPERTIES TIMEOUT 60)

        add_executable(worker_session_test
            tests/worker_session_test.cpp
        )

        target_link_libraries(worker_session_test
            PRIVATE
                QwenTTSBridge::qwen_tts_bridge
        )

        target_compile_definitions(worker_session_test
            PRIVATE
                QWEN_TTS_BRIDGE_TEST_PYTHON_EXECUTABLE="${QWEN_TTS_BRIDGE_TEST_PYTHON_EXECUTABLE}"
                QWEN_TTS_BRIDGE_TEST_WORKER_DIR="${QWEN_TTS_BRIDGE_TEST_WORKER_DIR}"
        )

        add_test(NAME worker_session_test COMMAND worker_session_test)

        add_executable(qwen_tts_client_test
            tests/qwen_tts_client_test.cpp
        )

        target_link_libraries(qwen_tts_client_test
            PRIVATE
                QwenTTSBridge::qwen_tts_bridge
        )

        target_compile_definitions(qwen_tts_client_test
            PRIVATE
                QWEN_TTS_BRIDGE_TEST_PYTHON_EXECUTABLE="${QWEN_TTS_BRIDGE_TEST_PYTHON_EXECUTABLE}"
                QWEN_TTS_BRIDGE_TEST_WORKER_DIR="${QWEN_TTS_BRIDGE_TEST_WORKER_DIR}"
        )

        add_test(NAME qwen_tts_client_test COMMAND qwen_tts_client_test)

        if(QWEN_TTS_BRIDGE_BUILD_EXAMPLES)
            add_test(
                NAME qwen_tts_save_wav_mock_example
                COMMAND qwen_tts_save_wav
                    --mock
                    --output "${CMAKE_CURRENT_BINARY_DIR}/qwen_tts_save_wav_mock.wav"
                    --text "Example synthesis request"
                    --mock-chunks 2
                    --request-timeout-ms 10000
            )
            add_test(
                NAME qwen_tts_save_wav_mock_verify
                COMMAND "${Python3_EXECUTABLE}"
                    "${CMAKE_CURRENT_SOURCE_DIR}/tests/python/verify_wav.py"
                    "${CMAKE_CURRENT_BINARY_DIR}/qwen_tts_save_wav_mock.wav"
                    --sample-rate 24000
                    --channels 1
                    --bits-per-sample 16
                    --min-data-bytes 1
            )
            set_tests_properties(qwen_tts_save_wav_mock_verify
                PROPERTIES
                    DEPENDS qwen_tts_save_wav_mock_example
            )
            add_test(
                NAME qwen_tts_latency_benchmark_mock_example
                COMMAND qwen_tts_latency_benchmark
                    --mock
                    --text "Benchmark synthesis request"
                    --mock-chunks 2
                    --warmups 1
                    --requests 2
                    --request-timeout-ms 10000
            )
            if(WIN32)
                add_test(
                    NAME qwen_tts_play_mock_utf8_example
                    COMMAND qwen_tts_play
                        --mock
                        --no-playback
                        --text "Я твой робот, я твой работник."
                        --speaker serena
                )
                add_test(
                    NAME qwen_tts_play_mock_playback_metrics
                    COMMAND "${Python3_EXECUTABLE}"
                        "${CMAKE_CURRENT_SOURCE_DIR}/tests/python/verify_playback_metrics.py"
                        --player "$<TARGET_FILE:qwen_tts_play>"
                        --output "${CMAKE_CURRENT_BINARY_DIR}/qwen_tts_play_mock_metrics.json"
                )
                add_test(
                    NAME qwen_tts_play_mock_pcm_capture
                    COMMAND "${Python3_EXECUTABLE}"
                        "${CMAKE_CURRENT_SOURCE_DIR}/tests/python/verify_pcm_capture.py"
                        --player "$<TARGET_FILE:qwen_tts_play>"
                        --output "${CMAKE_CURRENT_BINARY_DIR}/qwen_tts_play_mock_capture.pcm"
                )
                set_tests_properties(
                    qwen_tts_play_mock_utf8_example
                    qwen_tts_play_mock_playback_metrics
                    qwen_tts_play_mock_pcm_capture
                    PROPERTIES RESOURCE_LOCK default_audio_playback
                )
            endif()
        endif()
    else()
        message(WARNING "Python3 interpreter not found; stdio/worker session tests will not be built")
    endif()
endif()
