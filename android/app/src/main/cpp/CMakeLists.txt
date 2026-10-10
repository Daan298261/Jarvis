cmake_minimum_required(VERSION 3.22.1)
project(jarvis_native)

set(CMAKE_CXX_STANDARD 17)

include(FetchContent)
set(LLAMA_BUILD_COMMON ON CACHE BOOL "" FORCE)
set(LLAMA_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_SERVER OFF CACHE BOOL "" FORCE)
set(GGML_OPENMP OFF CACHE BOOL "" FORCE)
set(GGML_LLAMAFILE OFF CACHE BOOL "" FORCE)

FetchContent_Declare(
    llama
    GIT_REPOSITORY https://github.com/ggerganov/llama.cpp.git
    GIT_TAG b4586
    GIT_SHALLOW TRUE
    GIT_CONFIG core.longpaths=true
)
FetchContent_MakeAvailable(llama)

add_library(jarvis_llama SHARED jarvis_llama.cpp)
target_include_directories(jarvis_llama PRIVATE ${llama_SOURCE_DIR}/include)
target_link_libraries(jarvis_llama llama android log)

# RFC-0140: whisper.cpp + TTS native are a separate CMake project (ggml clashes with llama).
# Enable with -DJARVIS_BUILD_VOICE_NATIVE=ON for device soak APKs.
option(JARVIS_BUILD_VOICE_NATIVE "Build jarvis_whisper + jarvis_voice_tts (RFC-0140)" OFF)
if(JARVIS_BUILD_VOICE_NATIVE)
    include(ExternalProject)
    # Isolated configure so whisper.cpp's ggml targets do not collide with llama.cpp.
    # Must be part of the default ninja graph or AGP never builds the voice .so files.
    # Keep imported inputs outside AGP's object output cleanup. Declared shared
    # dependencies are included in both fresh and incremental APKs.
    set(_voice_lib_dir "${CMAKE_CURRENT_BINARY_DIR}/voice_native_ext/exported")
    # Private JNI dir: do not dump whisper's ggml .so next to llama.cpp's ggml.
    set(_voice_jni "${CMAKE_CURRENT_BINARY_DIR}/voice_native_ext/jni")
    ExternalProject_Add(
        jarvis_voice_native_ext
        SOURCE_DIR ${CMAKE_CURRENT_SOURCE_DIR}/voice_native
        BINARY_DIR ${CMAKE_CURRENT_BINARY_DIR}/voice_native_ext
        CMAKE_GENERATOR "${CMAKE_GENERATOR}"
        CMAKE_ARGS
            -DCMAKE_TOOLCHAIN_FILE=${CMAKE_TOOLCHAIN_FILE}
            -DANDROID_ABI=${ANDROID_ABI}
            -DANDROID_PLATFORM=${ANDROID_PLATFORM}
            -DANDROID_NDK=${ANDROID_NDK}
            -DANDROID_STL=${ANDROID_STL}
            -DCMAKE_BUILD_TYPE=${CMAKE_BUILD_TYPE}
            -DCMAKE_CXX_STANDARD=17
            -DCMAKE_MAKE_PROGRAM=${CMAKE_MAKE_PROGRAM}
            -DCMAKE_LIBRARY_OUTPUT_DIRECTORY=${_voice_jni}
            -DBUILD_SHARED_LIBS=OFF
        BUILD_BYPRODUCTS
            ${_voice_lib_dir}/libjarvis_whisper.so
            ${_voice_lib_dir}/libjarvis_voice_tts.so
            ${_voice_lib_dir}/libonnxruntime.so
        BUILD_ALWAYS 1
        INSTALL_COMMAND ${CMAKE_COMMAND} -E make_directory ${_voice_lib_dir}
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            ${_voice_jni}/libjarvis_whisper.so ${_voice_lib_dir}/libjarvis_whisper.so
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            ${_voice_jni}/libjarvis_voice_tts.so ${_voice_lib_dir}/libjarvis_voice_tts.so
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            ${_voice_jni}/libonnxruntime.so ${_voice_lib_dir}/libonnxruntime.so
        USES_TERMINAL_CONFIGURE TRUE
        USES_TERMINAL_BUILD TRUE
    )
    add_custom_target(jarvis_voice_native ALL DEPENDS jarvis_voice_native_ext)
    add_dependencies(jarvis_llama jarvis_voice_native_ext)
    foreach(_voice_runtime jarvis_whisper jarvis_voice_tts onnxruntime)
        add_library(${_voice_runtime} SHARED IMPORTED)
        set_target_properties(${_voice_runtime} PROPERTIES
            IMPORTED_LOCATION "${_voice_lib_dir}/lib${_voice_runtime}.so")
        target_link_libraries(jarvis_llama ${_voice_runtime})
    endforeach()
endif()
