cmake_minimum_required(VERSION 3.18)
project(bams_core LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(Python3 REQUIRED COMPONENTS Interpreter Development)
find_package(pybind11 CONFIG REQUIRED)
find_package(Threads REQUIRED)

set(BAMS_CORE_SOURCES
    src/storage.cpp
    src/buffer_pool.cpp
    src/lock_manager.cpp
    src/deadlock.cpp
    src/wal.cpp
    bindings/bindings.cpp
)

pybind11_add_module(bams_core ${BAMS_CORE_SOURCES})

target_include_directories(bams_core PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_link_libraries(bams_core PRIVATE Threads::Threads)

target_compile_features(bams_core PRIVATE cxx_std_17)

# Keep the Python extension in the layout expected by the Phase 1 tests.
set_target_properties(bams_core PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/../python/bams_core
    RUNTIME_OUTPUT_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/../python/bams_core
)

# Implementations and tests will be enabled after the design review.
# enable_testing()
# add_subdirectory(tests)
