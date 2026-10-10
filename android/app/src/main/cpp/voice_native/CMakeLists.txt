# Isolated CMake project so whisper.cpp ggml does not clash with llama.cpp.
cmake_minimum_required(VERSION 3.22.1)
project(jarvis_voice_native CXX)
set(CMAKE_CXX_STANDARD 17)

# Static whisper/ggml so the APK does not ship a second libggml.so next to llama.cpp.
set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_SERVER OFF CACHE BOOL "" FORCE)
set(GGML_NATIVE OFF CACHE BOOL "" FORCE)
set(GGML_OPENMP OFF CACHE BOOL "" FORCE)

include(FetchContent)
FetchContent_Declare(
    whisper
    GIT_REPOSITORY https://github.com/ggerganov/whisper.cpp.git
    GIT_TAG v1.7.5
    GIT_SHALLOW TRUE
)
FetchContent_MakeAvailable(whisper)

add_library(jarvis_whisper SHARED ../jarvis_whisper.cpp)
target_include_directories(jarvis_whisper PRIVATE ${whisper_SOURCE_DIR}/include ${whisper_SOURCE_DIR})
target_link_libraries(jarvis_whisper whisper android log)
# Hide static ggml symbols so they cannot clash with llama.cpp at load time.
target_link_options(jarvis_whisper PRIVATE -Wl,--exclude-libs,ALL)

# ONNX Runtime Mobile — single source: Maven AAR with pinned SHA-256.
# Headers come from the AAR's headers/ directory (no raw.githubusercontent).
# Do not also add the Gradle Java binding; that would ship libonnxruntime4j_jni.so
# and a second libonnxruntime.so.
set(ORT_VERSION "1.20.0")
set(ORT_AAR_SHA256 "07a8f71ef890afed8c6087a56220e6d558a492804276ee2dd7cb7f6262242027")
set(ORT_AAR_DIR "${CMAKE_CURRENT_BINARY_DIR}/ort-aar")
set(ORT_AAR_FILE "${CMAKE_CURRENT_BINARY_DIR}/onnxruntime-android-${ORT_VERSION}.aar")
set(ORT_AAR_URL "https://repo1.maven.org/maven2/com/microsoft/onnxruntime/onnxruntime-android/${ORT_VERSION}/onnxruntime-android-${ORT_VERSION}.aar")

message(STATUS "Fetching ONNX Runtime Android ${ORT_VERSION} (hashed)")
file(DOWNLOAD "${ORT_AAR_URL}" "${ORT_AAR_FILE}"
     EXPECTED_HASH SHA256=${ORT_AAR_SHA256}
     SHOW_PROGRESS TLS_VERIFY ON
     STATUS ORT_DL_STATUS)
list(GET ORT_DL_STATUS 0 ORT_DL_CODE)
if(NOT ORT_DL_CODE EQUAL 0)
    message(FATAL_ERROR "Failed to download ONNX Runtime Android AAR: ${ORT_DL_STATUS}")
endif()

if(NOT EXISTS "${ORT_AAR_DIR}/jni" OR NOT EXISTS "${ORT_AAR_DIR}/headers/onnxruntime_cxx_api.h")
    file(MAKE_DIRECTORY "${ORT_AAR_DIR}")
    file(ARCHIVE_EXTRACT INPUT "${ORT_AAR_FILE}" DESTINATION "${ORT_AAR_DIR}")
endif()
set(ORT_INCLUDE_DIR "${ORT_AAR_DIR}/headers")
if(NOT EXISTS "${ORT_INCLUDE_DIR}/onnxruntime_cxx_api.h")
    message(FATAL_ERROR "ONNX Runtime AAR is missing headers/: ${ORT_INCLUDE_DIR}")
endif()

if(NOT ANDROID_ABI)
    set(ANDROID_ABI "arm64-v8a")
endif()
set(ORT_LIB "${ORT_AAR_DIR}/jni/${ANDROID_ABI}/libonnxruntime.so")
if(NOT EXISTS "${ORT_LIB}")
    message(FATAL_ERROR "ONNX Runtime native library missing for ABI ${ANDROID_ABI}: ${ORT_LIB}")
endif()

add_library(onnxruntime SHARED IMPORTED)
set_target_properties(onnxruntime PROPERTIES IMPORTED_LOCATION "${ORT_LIB}")

add_library(jarvis_voice_tts SHARED
    ../jarvis_voice_tts.cpp
    pocket_tts_engine.cpp
    pocket_tts_tokenizer.cpp
)
target_include_directories(jarvis_voice_tts PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${ORT_INCLUDE_DIR}
)
target_compile_definitions(jarvis_voice_tts PRIVATE JARVIS_VOICE_TTS_ORT=1)
target_link_libraries(jarvis_voice_tts onnxruntime android log)

# Package libonnxruntime.so next to our JNI libs so the APK loads it.
add_custom_command(TARGET jarvis_voice_tts POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${ORT_LIB}"
        "$<TARGET_FILE_DIR:jarvis_voice_tts>/libonnxruntime.so"
)
