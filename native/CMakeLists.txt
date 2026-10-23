# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.3 | Engineering Build 2026.10.23-r6.35.3
# Developer Seal: CJB-DEV-2026

cmake_minimum_required(VERSION 3.20)
project(BCIWhisperNative LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(pybind11 CONFIG REQUIRED)

pybind11_add_module(_bci_native
    src/module.cpp
)

target_include_directories(_bci_native
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/include
)

target_compile_definitions(_bci_native
    PRIVATE
        BCIWHISPER_NATIVE_VERSION="58.3"
)

if (MSVC)
    target_compile_options(_bci_native PRIVATE /W4 /permissive-)
else()
    target_compile_options(_bci_native PRIVATE -Wall -Wextra -Wpedantic)
endif()

set_target_properties(_bci_native PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_SOURCE_DIR}/../bciwhisper/native"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_SOURCE_DIR}/../bciwhisper/native"
)
