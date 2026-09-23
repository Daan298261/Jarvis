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
)
FetchContent_MakeAvailable(llama)

add_library(jarvis_llama SHARED jarvis_llama.cpp)
target_include_directories(jarvis_llama PRIVATE ${llama_SOURCE_DIR}/include)
target_link_libraries(jarvis_llama llama android log)

# RFC-0140: whisper.cpp + TTS native are a separate CMake project (ggml clashes with llama).
# Enable with -DJARVIS_BUILD_VOICE_NATIVE=ON for device soak APKs.
option(JARVIS_BUILD_VOICE_NATIVE "Build jarvis_whisper + jarvis_voice_tts (RFC-0140)" OFF)
if(JARVIS_BUILD_VOICE_NATIVE)
    add_subdirectory(voice_native)
endif()
