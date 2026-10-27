"""HidHide 集成：「屏蔽物理手柄」的真正实现。

原理：独占打开（v1.0.11 那套）在这台机器上走不通 —— XboxService / dwm /
explorer 这些系统组件常年持有 HID 手柄的共享句柄，share=0 的 CreateFile
永远撞 ERROR_SHARING_VIOLATION。

HidHide（nefarius 出品，和 ViGEmBus 同生态）是内核过滤驱动：把设备实例
加进黑名单后，内核直接对不在白名单的进程返回"设备不存在"，游戏怎么枚举
都看不到物理手柄；映射器自己加进应用白名单，照常读。

2026-10-25 实测要点（都是踩过的坑）：
- CLI 装在 `C:\\Program Files\\Nefarius Software Solutions\\HidHide\\x64\\`，
  老版本的 `C:\\Program Files\\HidHideCLI\\` 早就没了
- 命令是 `--dev-hide / --dev-unhide / --dev-list / --app-reg / --app-unreg /
  --app-list / --cloak-on / --cloak-off / --cloak-state`，不是 /hide-add 那套
- **退出码永远是 0**，成功失败都得靠回读列表判断，不能信 exitcode
- 写操作在这台机器上**不需要管理员**（驱动自己判权），直接跑就行
- 一次调用可以串多条命令（--app-reg a --app-reg b --dev-hide x）
- 中文路径会被 CLI 输出截断（它自己 console 编码的 bug），但写入是成功的
"""
import os
import subprocess

CLI_CANDIDATES = [
    # v1.5.230+ 装在 Nefarius Software Solutions 目录下
    r"C:\Program Files\Nefarius Software Solutions\HidHide\x64\HidHideCLI.exe",
    # 老版本位置
    r"C:\Program Files\HidHideCLI\HidHideCLI.exe",
    r"C:\Program Files (x86)\HidHideCLI\HidHideCLI.exe",
]
SERVICE_NAME = "HidHide"


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


# CLI 单次调用超时。驱动被卡死时（官方 CLI 自己都要 40s+ 才应答），调用方
# 可以把这个值调小（比如 3 秒）快速失败，界面才不至于跟着一起挂。
DEFAULT_TIMEOUT = 20.0


def _run(args, timeout=None):
    """跑 CLI，返回 (stdout, stderr)。退出码不可信，看 stderr 有没有报错"""
    if timeout is None:
        timeout = DEFAULT_TIMEOUT
    exe = cli_path()
    if not exe:
        return "", "__err__找不到 HidHideCLI.exe"
    try:
        r = subprocess.run([exe] + args, capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8",
                           errors="replace",
                           creationflags=0x08000000)   # CREATE_NO_WINDOW
        return r.stdout or "", r.stderr or ""
    except Exception as e:
        return "", f"__err__{e}"


def _norm(s):
    return (s or "").lower().replace("\\", "").replace("/", "").strip()


# ------------------------------------------------------------------ 读
def hide_list():
    """当前被隐藏的设备（--dev-list 每行形如 --dev-hide "HID\\VID..."）"""
    out, err = _run(["--dev-list"])
    return None if err.startswith("__err__") else out


def app_list():
    out, err = _run(["--app-list"])
    return None if err.startswith("__err__") else out


def cloak_state():
    """True = 总开关打开（隐藏生效）"""
    out, err = _run(["--cloak-state"])
    return "--cloak-on" in out


def is_shielded(inst):
    lst = hide_list()
    if lst is None:
        return False
    key = _norm(inst)
    return any(key in _norm(line) for line in lst.splitlines())


def in_app_allowlist(exe):
    """白名单里有没有这个 exe（中文路径可能被 CLI 输出截断，做了宽松匹配）"""
    lst = app_list()
    if lst is None:
        return False
    name = os.path.basename(exe)
    return _norm(name) in _norm(lst) or _norm(exe) in _norm(lst)


# ------------------------------------------------------------------ 写
def _write(args):
    """非提权跑一条写命令。返回值不可信，一律靠回读列表判断。

    注意：CLI 偶尔会往 stderr 吐 'volume is case sensitive' 之类的噪音但
    其实写成功了，所以**不能**拿 stderr 当失败依据去弹 UAC —— 否则每次
    点屏蔽都莫名其妙弹一次授权。要不要提权，交给 shield_* 里回读决定。"""
    _run(args)
    return True


def _as_list(x):
    if not x:
        return []
    return list(x) if isinstance(x, (list, tuple, set)) else [x]


def _write_elevated(args, timeout=60):
    exe = cli_path()
    if not exe:
        return False
    quoted = " ".join(f'"{a}"' for a in args)
    ps = (f"$p = Start-Process -FilePath '{exe}' -ArgumentList '{quoted}' "
          f"-Verb RunAs -Wait -PassThru -WindowStyle Hidden; $p.ExitCode")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, timeout=timeout)
    except Exception:
        return False
    out, err = _run(args)          # 提权跑完再回读一次，靠列表判断
    return not err.strip()


def app_add(exe):
    return _write(["--app-reg", exe])


def app_rem(exe):
    return _write(["--app-unreg", exe])


def hide_add(inst):
    return _write(["--dev-hide", inst])


def hide_rem(inst):
    return _write(["--dev-unhide", inst])


def cloak_on():
    return _write(["--cloak-on"])


def cloak_off():
    return _write(["--cloak-off"])


def _all_shielded(insts):
    insts = _as_list(insts)
    return bool(insts) and all(is_shielded(i) for i in insts)


def _all_visible(insts):
    insts = _as_list(insts)
    return bool(insts) and not any(is_shielded(i) for i in insts)


def _do_shield(insts, apps, hide):
    """一轮实际操作：白名单 + 藏/放设备 + 总开关"""
    insts = _as_list(insts)
    args = []
    for exe in apps or ():
        args += ["--app-reg", exe]
    for i in insts:
        args += (["--dev-hide"] if hide else ["--dev-unhide"]) + [i]
    args += ["--cloak-on"] if hide else []
    _write(args)


def shield_on(insts, apps=()):
    """开屏蔽。返回 True = 回读确认全部进了黑名单且总开关已开。

    先非提权跑一轮（这台机器有权限，不会弹 UAC）；回读没生效才提权重试。
    """
    insts = _as_list(insts)
    if not insts:
        return False
    _do_shield(insts, apps, True)
    if _all_shielded(insts) and cloak_state():
        return True
    # 真没权限，弹一次 UAC 再试
    _write_elevated(_shield_args(insts, apps, True))
    return _all_shielded(insts) and cloak_state()


def shield_off(insts):
    """解除屏蔽（总开关保持不动，免得影响别的设备）"""
    insts = _as_list(insts)
    if not insts:
        return False
    _do_shield(insts, (), False)
    if _all_visible(insts):
        return True
    _write_elevated(_shield_args(insts, (), False))
    return _all_visible(insts)


def _shield_args(insts, apps, hide):
    args = []
    for exe in apps or ():
        args += ["--app-reg", exe]
    for i in insts:
        args += (["--dev-hide"] if hide else ["--dev-unhide"]) + [i]
    if hide:
        args += ["--cloak-on"]
    return args


def betop_instances(vid=0x20BC):
    """枚举这把北通当下的所有 HID 接口实例路径（col01/02/03 全要）。

    全藏才保险：只藏 col02 的话，有的游戏可能从别的接口也认出一个设备。
    映射器自己走白名单，藏哪个都不影响它读。
    """
    try:
        import hidraw
        rows = hidraw.list_devices(vid, None)
    except Exception:
        return []
    out = []
    for row in rows:
        path = row[-1]
        inst = instance_path(path)
        if inst not in out:
            out.append(inst)
    return out


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
