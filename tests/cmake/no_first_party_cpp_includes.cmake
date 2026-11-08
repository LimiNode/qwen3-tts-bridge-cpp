if(NOT DEFINED QWEN_TTS_BRIDGE_SOURCE_ROOT)
    message(FATAL_ERROR "QWEN_TTS_BRIDGE_SOURCE_ROOT is required")
endif()

file(GLOB_RECURSE source_files
    "${QWEN_TTS_BRIDGE_SOURCE_ROOT}/src/qwen_tts_bridge/*.cpp")

set(offenders)
foreach(source_file IN LISTS source_files)
    file(READ "${source_file}" source_text)
    if(source_text MATCHES "#[ \\t]*include[ \\t]*[<\"]([^>\"]+\\.cpp)[>\"]")
        file(RELATIVE_PATH relative_file
            "${QWEN_TTS_BRIDGE_SOURCE_ROOT}" "${source_file}")
        list(APPEND offenders "${relative_file}")
    endif()
endforeach()

if(offenders)
    list(JOIN offenders "\\n" offender_text)
    message(FATAL_ERROR
        "first-party .cpp includes are forbidden under src/qwen_tts_bridge/:\\n${offender_text}")
endif()
