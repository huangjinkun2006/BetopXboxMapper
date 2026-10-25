cmake_minimum_required(VERSION 3.22)
project(betopd C)

set(CMAKE_C_STANDARD 99)
add_compile_options(-Wall -Wextra -Wno-unused-parameter)

# 产物伪装成 .so 放到 assets/<abi>/，App 安装后释放到 /data/local/tmp 再 su 起来
add_executable(betopd betopd.c)
set_target_properties(betopd PROPERTIES
    RUNTIME_OUTPUT_NAME "libbetopd.so"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_SOURCE_DIR}/../assets/${ANDROID_ABI}")
