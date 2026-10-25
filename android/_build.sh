#!/bin/bash
# 安卓版构建脚本。
# 环境变量都是绝对路径 —— 改到别的机器上编，把下面 4 行改成你自己的位置就行。
# JDK / Android SDK / NDK / Gradle 的安装步骤见仓库根 README，
# 或者看 skill: android-apk-build-win
TOOLS_WIN="F:\\Workbuddy\\2026-10-24-08-32-45\\_android"
TOOLS="/f/Workbuddy/2026-10-24-08-32-45/_android"
JDK_WIN="$TOOLS_WIN\\jdk\\jdk-17.0.20.1+1"
JDK="$TOOLS/jdk/jdk-17.0.20.1+1"

# Java/AGP 只认 Windows 路径，这两类必须写成 F:\... 而不是 Git Bash 的 /f/...
export JAVA_HOME="$JDK_WIN"
export ANDROID_HOME="$TOOLS_WIN\\sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export GRADLE_USER_HOME="$TOOLS_WIN\\gradle-home"
# 只有 PATH 可以用 Git Bash 风格
export PATH="$JDK/bin:$PATH"

HERE="$(cd "$(dirname "$0")" && pwd)"
"$JDK/bin/java" -version 2>&1 | head -1
cd "$HERE"
"$TOOLS/gradle/gradle-8.2/bin/gradle" assembleRelease --stacktrace "$@" 2>&1
echo "GRADLE_EXIT=$?"
echo "产物: $HERE/app/build/outputs/apk/release/"
