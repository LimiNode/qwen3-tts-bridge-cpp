if(NOT DEFINED QWEN_DLL OR NOT DEFINED OUTPUT_DIR)
    message(FATAL_ERROR "QWEN_DLL and OUTPUT_DIR are required")
endif()
file(MAKE_DIRECTORY "${OUTPUT_DIR}")
file(COPY "${QWEN_DLL}" DESTINATION "${OUTPUT_DIR}")
file(SHA256 "${OUTPUT_DIR}/qwen.dll" QWEN_HASH)
file(WRITE "${OUTPUT_DIR}/manifest.json"
    "{\n"
    "  \"schema_version\": 1,\n"
    "  \"engine\": \"qwentts.cpp\",\n"
    "  \"engine_commit\": \"fake-qwentts-test\",\n"
    "  \"qt_abi_version\": 5,\n"
    "  \"architecture\": \"x64\",\n"
    "  \"backend\": \"fake\",\n"
    "  \"files\": [{\"path\": \"qwen.dll\", \"sha256\": \"${QWEN_HASH}\"}]\n"
    "}\n")
