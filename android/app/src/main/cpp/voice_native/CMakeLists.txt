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
    GIT_CONFIG core.longpaths=true
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
set(ORT_VERSION "1.31.0")
set(ORT_AAR_SHA256 "72683787a80d0608a3121b967d8e1239aef48286826661c953211626690540a7")
set(ORT_AAR_DIR "${CMAKE_CURRENT_BINARY_DIR}/ort-aar-${ORT_VERSION}-${ORT_AAR_SHA256}")
set(ORT_AAR_URL "https://repo1.maven.org/maven2/com/microsoft/onnxruntime/onnxruntime-android/${ORT_VERSION}/onnxruntime-android-${ORT_VERSION}.aar")
# One verified copy of the AAR is shared by every ABI and reused across builds
# (it used to be re-downloaded per ABI per build, so a single dropped
# connection failed the whole APK). Override with JARVIS_ORT_CACHE_DIR.
if(DEFINED ENV{JARVIS_ORT_CACHE_DIR} AND NOT "$ENV{JARVIS_ORT_CACHE_DIR}" STREQUAL "")
    file(TO_CMAKE_PATH "$ENV{JARVIS_ORT_CACHE_DIR}" ORT_CACHE_DIR)
else()
    get_filename_component(ORT_CACHE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../../../build/ort-cache" ABSOLUTE)
endif()
set(ORT_AAR_FILE "${ORT_CACHE_DIR}/onnxruntime-android-${ORT_VERSION}.aar")
set(ORT_DL_ATTEMPTS 4)

file(MAKE_DIRECTORY "${ORT_CACHE_DIR}")
# ABIs configure in parallel; serialize check + download on the shared cache.
file(LOCK "${ORT_CACHE_DIR}/onnxruntime-android-${ORT_VERSION}.lock"
     GUARD PROCESS TIMEOUT 1800 RESULT_VARIABLE ORT_LOCK_RESULT)
if(NOT ORT_LOCK_RESULT EQUAL 0)
    message(FATAL_ERROR "Could not lock ONNX Runtime cache ${ORT_CACHE_DIR}: ${ORT_LOCK_RESULT}")
endif()

set(ORT_AAR_VALID FALSE)
if(EXISTS "${ORT_AAR_FILE}")
    file(SHA256 "${ORT_AAR_FILE}" ORT_CACHED_SHA256)
    if(ORT_CACHED_SHA256 STREQUAL ORT_AAR_SHA256)
        set(ORT_AAR_VALID TRUE)
        message(STATUS "ONNX Runtime Android ${ORT_VERSION}: using verified cache ${ORT_AAR_FILE}")
    else()
        message(WARNING "Discarding cached ONNX Runtime AAR with wrong SHA-256 ${ORT_CACHED_SHA256}")
        file(REMOVE "${ORT_AAR_FILE}")
    endif()
endif()

if(NOT ORT_AAR_VALID)
    # Hash is verified by hand rather than with EXPECTED_HASH: a mismatch there
    # is a non-fatal CMake error that still fails configure after a good retry.
    set(ORT_AAR_PART "${ORT_AAR_FILE}.part")
    foreach(ORT_DL_ATTEMPT RANGE 1 ${ORT_DL_ATTEMPTS})
        message(STATUS "Fetching ONNX Runtime Android ${ORT_VERSION} (hashed), attempt ${ORT_DL_ATTEMPT}/${ORT_DL_ATTEMPTS}")
        file(REMOVE "${ORT_AAR_PART}")
        file(DOWNLOAD "${ORT_AAR_URL}" "${ORT_AAR_PART}"
             TLS_VERIFY ON
             INACTIVITY_TIMEOUT 60
             TIMEOUT 900
             STATUS ORT_DL_STATUS)
        list(GET ORT_DL_STATUS 0 ORT_DL_CODE)
        if(ORT_DL_CODE EQUAL 0)
            file(SHA256 "${ORT_AAR_PART}" ORT_DL_SHA256)
            if(ORT_DL_SHA256 STREQUAL ORT_AAR_SHA256)
                file(RENAME "${ORT_AAR_PART}" "${ORT_AAR_FILE}")
                set(ORT_AAR_VALID TRUE)
                break()
            endif()
            set(ORT_DL_STATUS "SHA-256 mismatch: got ${ORT_DL_SHA256}, expected ${ORT_AAR_SHA256}")
        endif()
        message(WARNING "ONNX Runtime AAR download attempt ${ORT_DL_ATTEMPT}/${ORT_DL_ATTEMPTS} failed: ${ORT_DL_STATUS}")
        if(ORT_DL_ATTEMPT LESS ORT_DL_ATTEMPTS)
            math(EXPR ORT_DL_BACKOFF "${ORT_DL_ATTEMPT} * 10")
            execute_process(COMMAND "${CMAKE_COMMAND}" -E sleep ${ORT_DL_BACKOFF})
        endif()
    endforeach()
    file(REMOVE "${ORT_AAR_PART}")
    if(NOT ORT_AAR_VALID)
        file(LOCK "${ORT_CACHE_DIR}/onnxruntime-android-${ORT_VERSION}.lock" RELEASE)
        message(FATAL_ERROR "Failed to download ONNX Runtime Android AAR after ${ORT_DL_ATTEMPTS} attempts: ${ORT_DL_STATUS}")
    endif()
endif()
file(LOCK "${ORT_CACHE_DIR}/onnxruntime-android-${ORT_VERSION}.lock" RELEASE)

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
