cmake_minimum_required(VERSION 3.16)
project(uinputd LANGUAGES C)

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS ON)

add_executable(uinputd uinputd.c)

if(CMAKE_C_COMPILER_ID MATCHES "Clang|GNU")
    target_compile_options(uinputd PRIVATE -Wall -Wextra -Werror)
endif()
