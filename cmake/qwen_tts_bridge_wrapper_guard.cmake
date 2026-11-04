# Validate one target's domain-wrapper source list without using a compile database.
function(qwen_tts_bridge_validate_wrapper_sources target source_root)
    if(NOT TARGET "${target}")
        message(FATAL_ERROR "wrapper guard target does not exist: ${target}")
    endif()

    get_target_property(_wrapper_guard_sources "${target}" SOURCES)
    if(NOT _wrapper_guard_sources)
        return()
    endif()

    set(_wrapper_guard_absolute_sources)
    foreach(_source IN LISTS _wrapper_guard_sources)
        if(_source MATCHES "^\\$<")
            continue()
        endif()
        get_filename_component(_source_absolute "${_source}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
        file(TO_CMAKE_PATH "${_source_absolute}" _source_absolute)
        list(APPEND _wrapper_guard_absolute_sources "${_source_absolute}")
    endforeach()

    foreach(_source IN LISTS _wrapper_guard_absolute_sources)
        if(NOT _source MATCHES "/src/qwen_tts_bridge/.+_domain/[^/]+\\.cpp$")
            continue()
        endif()

        file(READ "${_source}" _wrapper_contents)
        string(REGEX MATCH
            "#include[ \\t]+<qwen_tts_bridge/([^>]+\\.cpp)>"
            _wrapper_include_match "${_wrapper_contents}")
        if(NOT _wrapper_include_match)
            message(FATAL_ERROR
                "wrapper source does not include exactly one library implementation: ${_source}")
        endif()
        set(_included_relative "${CMAKE_MATCH_1}")
        string(REGEX MATCHALL
            "#include[ \\t]+<qwen_tts_bridge/[^>]+\\.cpp>"
            _wrapper_includes "${_wrapper_contents}")
        list(LENGTH _wrapper_includes _wrapper_include_count)
        if(NOT _wrapper_include_count EQUAL 1)
            message(FATAL_ERROR
                "wrapper must include exactly one implementation: ${_source}")
        endif()

        file(TO_CMAKE_PATH
            "${source_root}/src/qwen_tts_bridge/${_included_relative}"
            _included_absolute)
        if(NOT EXISTS "${_included_absolute}")
            message(FATAL_ERROR
                "wrapper implementation does not exist: ${_included_absolute}")
        endif()
        list(FIND _wrapper_guard_absolute_sources
            "${_included_absolute}" _duplicate_index)
        if(NOT _duplicate_index EQUAL -1)
            message(FATAL_ERROR
                "target ${target} compiles wrapper and included implementation together: ${_source} -> ${_included_absolute}")
        endif()

        list(FIND _wrapper_guard_mapped_implementations
            "${_included_absolute}" _mapped_index)
        if(NOT _mapped_index EQUAL -1)
            message(FATAL_ERROR
                "target ${target} maps more than one wrapper to ${_included_absolute}")
        endif()
        list(APPEND _wrapper_guard_mapped_implementations "${_included_absolute}")
    endforeach()
endfunction()
