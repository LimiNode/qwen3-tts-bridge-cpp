if(NOT DEFINED QWEN_TTS_BRIDGE_SOURCE_ROOT)
    message(FATAL_ERROR "QWEN_TTS_BRIDGE_SOURCE_ROOT is required")
endif()

set(source_files)
foreach(source_dir IN ITEMS src examples tests)
    foreach(extension IN ITEMS cpp cxx cc hpp hxx h)
        file(GLOB_RECURSE matches
            "${QWEN_TTS_BRIDGE_SOURCE_ROOT}/${source_dir}/*.${extension}")
        list(APPEND source_files ${matches})
    endforeach()
endforeach()

set(offenders)
foreach(source_file IN LISTS source_files)
    file(READ "${source_file}" source_text)
    if(source_text MATCHES "#[ \t]*include[ \t]*[<\"]\\.\\./")
        file(RELATIVE_PATH relative_file
            "${QWEN_TTS_BRIDGE_SOURCE_ROOT}" "${source_file}")
        list(APPEND offenders "${relative_file}")
    endif()
endforeach()

if(offenders)
    list(JOIN offenders "\n" offender_text)
    message(FATAL_ERROR
        "parent-relative C++ project include(s) are forbidden:\n${offender_text}")
endif()
