cmake_minimum_required(VERSION 3.22.1)
project(bciwhisper_whisper LANGUAGES C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(WHISPER_ROOT "${CMAKE_SOURCE_DIR}/../../../../../vendor/whisper.cpp")

find_library(LOG_LIB log)
find_library(ANDROID_LIB android)

include(FetchContent)
FetchContent_Declare(ggml SOURCE_DIR "${WHISPER_ROOT}/ggml")
FetchContent_MakeAvailable(ggml)

add_library(
    bciwhisper_whisper
    SHARED
    "${WHISPER_ROOT}/src/whisper.cpp"
    "${CMAKE_SOURCE_DIR}/jni.c"
)

target_compile_definitions(bciwhisper_whisper PUBLIC GGML_USE_CPU)
target_compile_options(bciwhisper_whisper PRIVATE -O3 -fvisibility=hidden -fvisibility-inlines-hidden -ffunction-sections -fdata-sections)

target_include_directories(
    bciwhisper_whisper
    PRIVATE
    "${WHISPER_ROOT}"
    "${WHISPER_ROOT}/src"
    "${WHISPER_ROOT}/include"
    "${WHISPER_ROOT}/ggml/include"
    "${WHISPER_ROOT}/ggml/src"
    "${WHISPER_ROOT}/ggml/src/ggml-cpu"
)

target_link_libraries(
    bciwhisper_whisper
    PRIVATE
    ggml
    ${LOG_LIB}
    ${ANDROID_LIB}
)
