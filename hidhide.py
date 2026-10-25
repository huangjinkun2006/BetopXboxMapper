"""HidHide 集成：「屏蔽物理手柄」的真正实现。

原理：独占打开（v1.0.11 那套）在这台机器上走不通 —— XboxService / dwm /
explorer 这些系统组件常年持有 HID 手柄的共享句柄，share=0 的 CreateFile
永远撞 ERROR_SHARING_VIOLATION。

HidHide（nefarius 出品，和 ViGEmBus 同生态）是内核过滤驱动：把设备实例
加进黑名单后，内核直接对不在白名单的进程返回"设备不存在"，游戏怎么枚举
都看不到物理手柄；映射器自己加进应用白名单，照常读。
"""
import ctypes
import os
import subprocess

CLI_CANDIDATES = [
    r"C:\Program Files\HidHideCLI\HidHideCLI.exe",
    r"C:\Program Files (x86)\HidHideCLI\HidHideCLI.exe",
]
SERVICE_NAME = "HidHide"
SW_HIDE = 0


def cli_path():
    for p in CLI_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def installed():
    """驱动装没装：看 CLI 或服务"""
    if cli_path():
        return True
    try:
        out = subprocess.run(["sc", "query", SERVICE_NAME],
                             capture_output=True, text=True, timeout=10,
                             encoding="utf-8", errors="replace").stdout
        return "RUNNING" in out or "STOPPED" in out
    except Exception:
        return False


def instance_path(interface_path):
    r"""\\?\hid#vid_20bc&pid_503c&col02#7&2529385&0&0001#{guid}
    -> HID\VID_20BC&PID_503C&COL02\7&2529385&0&0001"""
    p = interface_path
    if p.startswith("\\\\?\\"):
        p = p[4:]
    p = p.split("#{")[0]          # 去掉接口 GUID 尾巴
    p = p.upper().replace("HID#", "HID\\", 1).replace("#", "\\")
    return p


def _run(args, timeout=15):
    """直接跑 CLI（读操作不需要管理员）"""
    try:
        return subprocess.run([cli_path()] + args, capture_output=True,
                              text=True, timeout=timeout,
                              encoding="utf-8", errors="replace",
                              creationflags=0x08000000).stdout  # CREATE_NO_WINDOW
    except Exception as e:
        return f"__err__{e}"


def _run_elevated(args, timeout=30):
    """要管理员权限的写操作：PowerShell Start-Process -Verb RunAs，拿退出码"""
    exe = cli_path()
    if not exe:
        return -1
    quoted = " ".join(f'"{a}"' for a in args)
    ps = (f"$p = Start-Process -FilePath '{exe}' -ArgumentList '{quoted}' "
          f"-Verb RunAs -Wait -PassThru -WindowStyle Hidden; $p.ExitCode")
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=timeout)
        return int(r.stdout.strip() or -1)
    except Exception:
        return -1


def hide_list():
    out = _run(["/hide-list"])
    if out.startswith("__err__"):
        return None
    return out


def is_shielded(inst):
    lst = hide_list()
    if lst is None:
        return False
    key = inst.lower().replace("\\", "")
    for line in lst.splitlines():
        if key in line.lower().replace("\\", ""):
            return True
    return False


def app_list():
    out = _run(["/app-list"])
    return None if out.startswith("__err__") else out


def _elevated_ok(code):
    return code == 0


def hide_add(inst):
    return _elevated_ok(_run_elevated(["/hide-add", inst]))


def hide_rem(inst):
    return _elevated_ok(_run_elevated(["/hide-rem", inst]))


def app_add(exe):
    return _elevated_ok(_run_elevated(["/app-add", exe]))


def app_rem(exe):
    return _elevated_ok(_run_elevated(["/app-rem", exe]))


def in_app_allowlist(exe):
    lst = app_list()
    if lst is None:
        return False
    return exe.lower() in lst.lower()


def install_silent(installer_path):
    """静默安装 HidHide（WiX burn：/passive /norestart），要 UAC"""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"$p = Start-Process -FilePath '{installer_path}' "
             f"-ArgumentList '/passive','/norestart' -Verb RunAs -Wait "
             f"-PassThru; $p.ExitCode"],
            capture_output=True, text=True, timeout=300)
        code = int(r.stdout.strip() or -1)
        return code == 0 or code == 3010        # 3010 = 装完要重启
    except Exception:
        return False
