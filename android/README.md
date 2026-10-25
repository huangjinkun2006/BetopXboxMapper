# BetopPad · 安卓版

PC 版 [BetopXboxMapper](../) 的手机版。把 **北通 BTP-V1T**
（腾讯先游定制版，VID `20BC` / PID `503C`）在安卓上伪装成**标准安卓手柄**，
让只认标准手柄的游戏、云游戏客户端能正常用它。

## 前提：手机必须 root

安卓上没有 ViGEm 那种虚拟设备框架，唯一的办法是直接操作 `/dev/uinput`。
不 root 干不了，没有第二条路。

## 工作原理

```
物理手柄 /dev/input/eventN
   ↓ root 直读原始事件（走 framework 拿不到 FN 这种非标准键）
查询映射表 → 按键换码 / 轴线性缩放 + 反向 / 丢重复帧
   ↓
/dev/uinput → 系统里冒出一个标准安卓手柄（BUS_VIRTUAL）
```

- `app/src/main/cpp/betopd.c` —— C 写的守护进程，root 权限跑
- 用 NDK 编 4 个 ABI，**伪装成 `assets/<abi>/libbetopd.so`** 打进 APK
  （不走 jniLibs/CMake，省掉 externalNativeBuild 那一堆麻烦）
  运行时按 `Build.SUPPORTED_ABIS` 挑一个，释放到 `/data/local/tmp` 用 su 拉起
- 父进程与它之间用**文本流**通信（`K 304 1\n` / `A 0 32767\n`），
  不用结构体 —— `struct input_event` 在 32/64 位上大小不一样，二进制流迟早对不上
- 回传的是**物理原始码**，让 App 自己拿配置表折算。
  这样改键时才知道按的是物理上哪个键，FN 也抓得到

## 怎么编

1. 装 JDK17 / Android cmdline-tools / platforms;android-34 / build-tools;34.0.0 /
   platform-tools / ndk / Gradle —— 步骤见仓库根 README，或 skill `android-apk-build-win`
2. 改 `_build.sh` 顶部那 4 行路径，指向你自己的工具链
3. 编守护进程（4 个 ABI）：

   ```bash
   NDK=.../sdk/ndk/26.1.10909125
   CC="$NDK/toolchains/llvm/prebuilt/windows-x86_64/bin/clang.exe"
   for pair in "arm64-v8a:aarch64-linux-android24" \
               "armeabi-v7a:armv7a-linux-androideabi24" \
               "x86_64:x86_64-linux-android24" "x86:i686-linux-android24"; do
     abi="${pair%%:*}"; tgt="${pair##*:}"
     mkdir -p "app/src/main/assets/$abi"
     "$CC" --target=$tgt -Wall -o "app/src/main/assets/$abi/libbetopd.so" app/src/main/cpp/betopd.c
   done
   ```

4. 签名证书（`_android/keystore/betoppad.jks`，口令/别名都是 `betoppad`）在
   `app/build.gradle` 里配好；换机器编要自己生成一个新的
5. `bash _build.sh` → 产物在 `app/build/outputs/apk/release/`

## 更新检查

PC 版和安卓版发在**同一个仓库**，靠 tag 前缀区分：

| | tag |
|---|---|
| PC 版 | `vX.Y.Z` |
| 安卓版 | `android-vX.Y.Z` |

两边都遍历 `/releases?per_page=20` 再按前缀过滤 —— 直接读
`/releases/latest` 的话，谁后发谁就是 latest，会串台。

## 已知限制

- 必须 root
- 「独占接管」（EVIOCGRAB）开着时物理手柄的原始信号会被吃掉，
  守护进程崩了手柄会短暂失灵 —— 点「停止映射」恢复
- 震动命令格式是在 PC 上穷举出来的（`/dev/hidraw`，report id 2 / b1=0x08 /
  b3=大马达 / b4=小马达），别的固件版本不一定认
- **没在真机上跑过**（作者手头没 root 的安卓机）。卡住的话看主界面最底下
  那个日志框，它打 ABI、su 结果、守护进程释放结果和每个未绑定的原始键码
