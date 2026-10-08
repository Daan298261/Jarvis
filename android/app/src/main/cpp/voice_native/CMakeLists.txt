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

# ONNX Runtime Mobile (Maven artifact onnxruntime-android) — MIT license.
# Headers from the matching GitHub tag; native .so from the official Android AAR.
set(ORT_VERSION "1.20.0")
set(ORT_AAR_DIR "${CMAKE_CURRENT_BINARY_DIR}/ort-aar")
set(ORT_INCLUDE_DIR "${CMAKE_CURRENT_BINARY_DIR}/ort-include")
set(ORT_AAR_FILE "${CMAKE_CURRENT_BINARY_DIR}/onnxruntime-android-${ORT_VERSION}.aar")
set(ORT_AAR_URL "https://repo1.maven.org/maven2/com/microsoft/onnxruntime/onnxruntime-android/${ORT_VERSION}/onnxruntime-android-${ORT_VERSION}.aar")

if(NOT EXISTS "${ORT_AAR_FILE}")
    message(STATUS "Downloading ONNX Runtime Android ${ORT_VERSION}")
    file(DOWNLOAD "${ORT_AAR_URL}" "${ORT_AAR_FILE}" SHOW_PROGRESS TLS_VERIFY ON
         STATUS ORT_DL_STATUS)
    list(GET ORT_DL_STATUS 0 ORT_DL_CODE)
    if(NOT ORT_DL_CODE EQUAL 0)
        message(FATAL_ERROR "Failed to download ONNX Runtime Android AAR: ${ORT_DL_STATUS}")
    endif()
endif()

if(NOT EXISTS "${ORT_AAR_DIR}/jni")
    file(MAKE_DIRECTORY "${ORT_AAR_DIR}")
    file(ARCHIVE_EXTRACT INPUT "${ORT_AAR_FILE}" DESTINATION "${ORT_AAR_DIR}")
endif()

set(ORT_HEADER_BASE "https://raw.githubusercontent.com/microsoft/onnxruntime/v${ORT_VERSION}/include/onnxruntime/core/session")
file(MAKE_DIRECTORY "${ORT_INCLUDE_DIR}")
foreach(ORT_HEADER
        onnxruntime_c_api.h
        onnxruntime_cxx_api.h
        onnxruntime_cxx_inline.h
        onnxruntime_float16.h)
    if(NOT EXISTS "${ORT_INCLUDE_DIR}/${ORT_HEADER}")
        file(DOWNLOAD "${ORT_HEADER_BASE}/${ORT_HEADER}" "${ORT_INCLUDE_DIR}/${ORT_HEADER}"
             TLS_VERIFY ON STATUS ORT_HDR_STATUS)
        list(GET ORT_HDR_STATUS 0 ORT_HDR_CODE)
        if(NOT ORT_HDR_CODE EQUAL 0)
            message(FATAL_ERROR "Failed to download ${ORT_HEADER}: ${ORT_HDR_STATUS}")
        endif()
    endif()
endforeach()

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
