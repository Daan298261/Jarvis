# Separate ggml namespace from llama — only included when JARVIS_BUILD_VOICE_NATIVE=ON.
cmake_minimum_required(VERSION 3.22.1)

set(WHISPER_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_SERVER OFF CACHE BOOL "" FORCE)

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

add_library(jarvis_voice_tts SHARED ../jarvis_voice_tts.cpp)
target_link_libraries(jarvis_voice_tts android log)
