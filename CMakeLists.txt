cmake_minimum_required(VERSION 3.18)
project(bams_core LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(bams_deadlock src/deadlock.cpp)
target_include_directories(bams_deadlock PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_compile_features(bams_deadlock PUBLIC cxx_std_14)

add_executable(deadlock_demo tools/deadlock_demo.cpp)
target_link_libraries(deadlock_demo PRIVATE bams_deadlock)

add_executable(deadlock_cli tools/deadlock_cli.cpp)
target_link_libraries(deadlock_cli PRIVATE bams_deadlock)

add_executable(deadlock_tests tests/deadlock_tests.cpp)
target_link_libraries(deadlock_tests PRIVATE bams_deadlock)

enable_testing()
add_test(NAME deadlock_tests COMMAND deadlock_tests)
