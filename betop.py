"""北通手柄 -> 虚拟 Xbox 360 手柄 映射引擎。

核心思路：
    1. 直接开物理手柄的 HID 接口，读原始输入报告（绕开厂商驱动）
    2. 用系统的 HidP API 解析报告（不是猜字节位）——轴和十字键是权威数据
    3. 通过 ViGEmBus(vgamepad) 输出成一个系统级真实的 Xbox 360 手柄
       —— 基岩版 Minecraft 这类只认 XInput 的（哪怕是 UWP）应用都能直接识别

实测这把手柄（VID 20BC / PID 503C）的报告描述符：
    report id = 3，输入报告 11 字节
    按钮: 使用页 0x09，usage 1..15（15 个）+ 消费页 0x0C usage 105
    轴  : 通用桌面页 X(0x30) Y(0x31) Z(0x32) Rz(0x35) Hat(0x39)
    扳机: 模拟页 Accelerator(0xC4) Brake(0xC5)
"""
import json
import os
import sys
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import hidraw

VID = 0x20BC

# 打包成 exe 后 __file__ 指向临时解压目录，键位必须存在 exe 旁边才留得住
if getattr(sys, "frozen", False):
    HERE = os.path.dirname(sys.executable)
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
KEYMAP_PATH = os.path.join(HERE, "keymap.json")

# Xbox 360 手柄的目标键位
BUTTON_TARGETS = ["A", "B", "X", "Y", "LB", "RB", "BACK", "START",
                  "LS", "RS", "GUIDE"]
DPAD_TARGETS = ["UP", "DOWN", "LEFT", "RIGHT"]
AXIS_TARGETS = ["LX", "LY", "RX", "RY", "LT", "RT"]

# 通用桌面页 usage
UP_GENERIC, UP_SIM, UP_CONSUMER = 0x01, 0x02, 0x0C
U_X, U_Y, U_Z, U_RZ, U_HAT = 0x30, 0x31, 0x32, 0x35, 0x39
U_ACCEL, U_BRAKE = 0xC4, 0xC5


# ---------------------------------------------------------------- 键位配置

def default_keymap():
    """BETOP BTP-V1T（先游定制版）实测布局。

    按钮来自该手柄的 SDL 官方映射串（"BETOP TCP BFM GAMEPAD"），
    已用原始 HID 报告字节逐一核对：A=bit0 B=bit1 X=bit3 Y=bit4
    LB=bit6 RB=bit7 BACK=bit10 START=bit11 LS=bit13 RS=bit14 GUIDE=bit15。
    （bit 编号 +1 = HID usage。bit2/bit5/bit8/bit9 是数字扳机，未使用。）
    """
    return {
        "_说明": "buttons 里的数字是 HID usage（按钮页 0x09），来自 SDL 官方映射串"
                 "并已实测核对。axes 由 usage 定位，别改 usage；invert=true 反向。",
        "report_len": 11,
        "deadzone": 0.12,
        "trigger_deadzone": 0.03,
        "rumble": True,          # 把游戏震动转发到物理手柄
        "rumble_fmt": 0,         # 震动命令格式（RUMBLE_FORMATS 下标）
        "rumble_gain": 1.0,      # 震动强度系数 0.05..3.0（>1 是把小震动放大）
        "rumble_custom": None,   # 实验室比出来的冠军命令，有它就优先用它
        # 震动闹钟：到点让手柄震，按任意键停
        "alarm_on": False,
        "alarm_time": "07:00",
        "alarm_repeat": True,    # True = 每天都响；False = 只响一次就自动关
        "alarm_strength": 1.0,   # 响铃时的震动强度 0.1..3.0
        "alarm_ring": 0,         # 铃声（alarm.RINGTONES 下标），0=连续猛震
        "buttons": {
            "A": 1, "B": 2, "X": 4, "Y": 5,
            "LB": 7, "RB": 8,
            "BACK": 11, "START": 12,
            "LS": 14, "RS": 15,
            "GUIDE": 16,
        },
        "axes": {
            "LX": {"up": UP_GENERIC, "usage": U_X, "lo": 0, "hi": 255, "center": 128,
                   "fallback_byte": 5, "invert": False},
            "LY": {"up": UP_GENERIC, "usage": U_Y, "lo": 0, "hi": 255, "center": 128,
                   "fallback_byte": 6, "invert": False},
            "RX": {"up": UP_GENERIC, "usage": U_Z, "lo": 0, "hi": 255, "center": 128,
                   "fallback_byte": 7, "invert": False},
            "RY": {"up": UP_GENERIC, "usage": U_RZ, "lo": 0, "hi": 255, "center": 128,
                   "fallback_byte": 8, "invert": False},
            # 实测：byte9 = Brake(0xC5) = LT，byte10 = Accelerator(0xC4) = RT
            "LT": {"up": UP_SIM, "usage": U_BRAKE, "lo": 0, "hi": 255, "unipolar": True,
                   "fallback_byte": 9, "invert": False},
            "RT": {"up": UP_SIM, "usage": U_ACCEL, "lo": 0, "hi": 255, "unipolar": True,
                   "fallback_byte": 10, "invert": False},
        },
        "hat": {"up": UP_GENERIC, "usage": U_HAT, "fallback_byte": 2},
    }


def load_keymap():
    km = default_keymap()
    if os.path.exists(KEYMAP_PATH):
        try:
            with open(KEYMAP_PATH, "r", encoding="utf-8") as f:
                km.update(json.load(f))
        except Exception:
            pass
    return km


def save_keymap(km):
    with open(KEYMAP_PATH, "w", encoding="utf-8") as f:
        json.dump(km, f, ensure_ascii=False, indent=2)
    print(f"已保存键位到 {KEYMAP_PATH}")


# ---------------------------------------------------------------- 设备

class HidPad:
    def __init__(self):
        self.dev = None
        self.in_len = 11
        self.use_hidp = False

    def open(self):
        # 不锁死 PID：切模式或换连接方式 PID 可能变，只要是北通(20BC)就认
        path, in_len = hidraw.find_gamepad(VID, None)
        if path is None:
            raise RuntimeError("没找到北通手柄（VID 20BC），检查有线/蓝牙是否连上")
        self.dev = hidraw.RawHid().open_path(path)
        self.in_len = in_len or 11
        self.use_hidp = bool(self.dev.preparsed)
        return self

    def read(self):
        return self.dev.read(self.in_len)

    def decode(self, report):
        """返回 (按下的 usage 集合, 是否用了 HidP)"""
        if self.use_hidp:
            btns, _ = self.dev.decode(report)
            return set(btns.keys()), True
        return set(), False

    def usage_value(self, report, up, usage):
        if not self.use_hidp:
            return None
        return self.dev.usage_value(report, up, usage)

    def close(self):
        if self.dev:
            self.dev.close()


def open_device(wait=False, timeout=180):
    t0 = time.time()
    while True:
        try:
            return HidPad().open()
        except Exception as e:
            if not wait or (time.time() - t0) > timeout:
                raise
            print(f"\r  等手柄连上...（{e}）      ", end="", flush=True)
            time.sleep(1.0)


def read_report(dev, timeout=2.0, tries=40):
    """读一帧有效报告"""
    for _ in range(tries):
        r = dev.read()
        if r:
            return list(r)
        time.sleep(0.02)
    return None


# ---------------------------------------------------------------- 报告解析

def hat_to_dpad(v):
    """HID hat: 0=上，顺时针到 7=左上；8/15=中位"""
    if v is None or v in (8, 15, 0xFF):
        return {"UP": False, "DOWN": False, "LEFT": False, "RIGHT": False}
    return {
        "UP": v in (0, 1, 7),
        "RIGHT": v in (1, 2, 3),
        "DOWN": v in (3, 4, 5),
        "LEFT": v in (5, 6, 7),
    }


def normalize(spec, raw):
    """把原始值归一化到 -1..1（摇杆）或 -1..1（扳机松开=-1 扣底=+1）"""
    lo = spec.get("lo", 0)
    hi = spec.get("hi", 255)
    if hi == lo:
        return 0.0
    if spec.get("unipolar"):
        v = (raw - lo) / (hi - lo) * 2.0 - 1.0
    else:
        center = spec.get("center", (lo + hi) // 2)
        half = (hi - lo) / 2.0
        v = 0.0 if half == 0 else (raw - center) / half
    if spec.get("invert"):
        v = -v
    return max(-1.0, min(1.0, v))


def apply_deadzone(v, dz):
    if dz <= 0:
        return v
    if abs(v) < dz:
        return 0.0
    return (v - dz) / (1 - dz) if v > 0 else (v + dz) / (1 - dz)


def parse_report(dev, report, km):
    """把一帧报告翻译成 (buttons dict, axes dict)"""
    pressed, _ = dev.decode(report)

    # 字节兜底：HidP 不可用时，按 "usage 1..16 顺序排在 byte3/bit0 起" 解析。
    # 这把手柄实测就是这个排布（bit 编号 +1 = usage）。
    if not pressed and len(report) >= 5:
        pressed = {i + 1 for i in range(16)
                   if (report[3 + i // 8] >> (i % 8)) & 1}

    buttons = {}
    for tgt in BUTTON_TARGETS:
        usage = km["buttons"].get(tgt)
        buttons[tgt] = bool(usage) and usage in pressed

    hat_spec = km.get("hat", {})
    hv = dev.usage_value(report, hat_spec.get("up", 1), hat_spec.get("usage", U_HAT))
    if hv is None and hat_spec.get("fallback_byte") is not None:
        hv = report[hat_spec["fallback_byte"]]
    dpad = hat_to_dpad(hv)
    buttons.update(dpad)

    axes = {}
    for tgt in AXIS_TARGETS:
        spec = km["axes"].get(tgt)
        if not spec:
            axes[tgt] = 0.0
            continue
        raw = dev.usage_value(report, spec.get("up", 1), spec.get("usage"))
        fb = spec.get("fallback_byte")
        if raw is None and fb is not None:
            raw = report[fb]
        if raw is None:
            axes[tgt] = 0.0
            continue
        axes[tgt] = normalize(spec, raw)
    return buttons, axes


# ---------------------------------------------------------------- 震动

# 这把手柄的游戏接口（0x01/0x05）实测 out_len=0，发不出东西；
# 64 字节双向的厂商私有接口（0xFF00）才有输出报告，震动只能走那儿。
# 协议没公开，下面是按同类北通手柄（2171s BFM）逆向出来的格式做的一批候选，
# 界面上可以逐个试，哪个能震就选哪个，选中后写进 keymap.json。
# Linux 内核的 hid-betopff.c 是这么干的（同类北通 BFM 手柄）：
#   用 HID_REQ_SET_REPORT（控制通道，不是 WriteFile）+ 4 字节 "00 00 左 右"
# 所以候选 = 两种发送通道 × 字节位置若干组合。界面上有自动扫描，挨个发，
# 感觉到震就点一下，选中后写进 keymap.json。
CH_SET_REPORT = 0     # HidD_SetOutputReport（控制通道）
CH_WRITE      = 1     # WriteFile（中断 OUT）
CHANNEL_NAME  = {CH_SET_REPORT: "SET_REPORT", CH_WRITE: "WriteFile"}


def _pl(off_big, off_small, magic=None):
    """造一帧：第 0 字节是 report id 2，其余按位置填两个马达强度"""
    def build(l, r):
        b = [2] + [0] * 63
        if magic is not None:
            b[1] = magic
        b[off_big] = l
        b[off_small] = r
        return b
    return build


def _build_formats():
    out = []
    for ch in (CH_SET_REPORT, CH_WRITE):
        cn = CHANNEL_NAME[ch]
        # 最可疑的排前面：id 之后 00 00 大 小（就是内核驱动那个布局）
        out.append((f"① {cn} · 00 00 大 小", ch, _pl(3, 4)))
        out.append((f"② {cn} · 00 00 小 大", ch, _pl(4, 3)))
        # 相邻位置扫一遍（第 n、n+1 字节）
        for n in range(1, 9):
            out.append((f"{'·'} {cn} · 第{n}字节=大 第{n+1}=小", ch, _pl(n, n + 1)))
        # 带命令头的几种
        for magic in (1, 2, 8, 0x0b, 0x40, 0x55):
            out.append((f"{'·'} {cn} · 头字节 0x{magic:02X} 后接 大 小", ch,
                        _pl(3, 4, magic=magic)))
    return out


RUMBLE_FORMATS = _build_formats()


class Rumble:
    """把虚拟手柄收到的震动指令转发给物理手柄。"""

    # 固件收到命令只会震很短一下（不像 XInput 会自己持续），
    # 所以要不停重发，游戏里的持续震动才不会变成"抖一下"。
    HB_INTERVAL = 0.20

    def __init__(self, fmt=0, enabled=True, custom=None):
        self.dev = None
        self.fmt = fmt
        self.enabled = enabled
        self._last = None
        self._target = (0, 0)
        self._hb_stop = threading.Event()
        self._hb = None
        # custom = 实验室比出来的冠军命令，形如
        #   {"chan": "write"/"set", "fixed": [(偏移, 值)...], "motor": [偏移...]}
        # motor 里的字节会被马达强度覆盖；有它就不用猜格式了
        self.custom = custom

    # ------------------------------------------------------ 造帧
    def frame(self, l, r):
        c = self.custom
        if not c:
            return RUMBLE_FORMATS[self.fmt][2](l, r)
        b = [2] + [0] * 63
        for off, val in c.get("fixed", []):
            b[off] = val
        m = [o for o in c.get("motor", []) if o != 1] or [3]
        b[m[0]] = max(l, r) if len(m) == 1 else l
        if len(m) >= 2:
            b[m[1]] = r
        return b

    # ------------------------------------------------------ 心跳续发
    def _ensure_hb(self):
        if self._hb is not None and self._hb.is_alive():
            return
        self._hb_stop.clear()
        self._hb = threading.Thread(target=self._hb_loop, daemon=True)
        self._hb.start()

    def _hb_loop(self):
        while not self._hb_stop.is_set():
            time.sleep(self.HB_INTERVAL)
            l, r = self._target
            if (l or r) and self.dev is not None and self.enabled:
                try:
                    self._send(self.frame(l, r))
                except Exception:
                    pass

    def open(self):
        path = hidraw.find_output_iface(VID)
        if path is None:
            raise RuntimeError("没找到手柄的私有输出接口（0xFF00），震动用不了")
        self.dev = hidraw.RawHid().open_path(path)
        return self

    def _send(self, data):
        """按当前格式（或自定义冠军命令）指定的通道发一帧；不支持就退回另一种"""
        if self.custom:
            ch = CH_SET_REPORT if self.custom.get("chan") == "set" else CH_WRITE
        else:
            ch = RUMBLE_FORMATS[self.fmt][1]
        if ch == CH_SET_REPORT:
            if self.dev.set_report(data):
                return True
            return self.dev.write(data)
        if self.dev.write(data):
            return True
        return self.dev.set_report(data)

    def set(self, big, small):
        """big/small 都是 0..255"""
        if self.dev is None or not self.enabled:
            return
        l = max(0, min(255, int(big)))
        r = max(0, min(255, int(small)))
        self._target = (l, r)
        key = (l, r, self.fmt)
        if key == self._last:      # 值没变就不用立刻重写，心跳会续着
            if l or r:
                self._ensure_hb()
            return
        self._last = key
        try:
            self._send(self.frame(l, r))
        except Exception:
            pass
        if l or r:
            self._ensure_hb()      # 只要还在震就一直续发

    def play_once(self, idx, strength=255, secs=0.9):
        """试震 / 自动扫描用：按指定格式发一段固定强度的震动"""
        self.fmt = max(0, min(idx, len(RUMBLE_FORMATS) - 1))
        self._last = None
        self._send(self.frame(strength, strength))

    def stop(self):
        """用当前格式回写 0，让马达停转"""
        self._last = None
        self._target = (0, 0)
        if self.dev is None:
            return
        try:
            self._send(self.frame(0, 0))
        except Exception:
            pass

    def stop_all(self):
        """保险起见，把所有已知载荷都清一遍（有手柄收到某条命令后会一直震）"""
        self._last = None
        self._target = (0, 0)
        if self.dev is None:
            return
        if self.custom:               # 自定义冠军命令也要回写 0
            try:
                z = self.frame(0, 0)
                self.dev.write(z)
                self.dev.set_report(z)
            except Exception:
                pass
        for _n, _c, fn in RUMBLE_FORMATS:
            try:
                zero = fn(0, 0)
            except Exception:
                continue
            for f in (self.dev.set_report, self.dev.write):
                try:
                    f(zero)
                except Exception:
                    pass
        for rid in (0, 1, 2, 3, 4, 8):
            for ln in (5, 6, 9, 64, 65):
                buf = [rid] + [0] * (ln - 1)
                for f in (self.dev.set_report, self.dev.write):
                    try:
                        f(buf)
                    except Exception:
                        pass

    def close(self):
        self._hb_stop.set()        # 心跳线程停掉，不然关了还在发
        try:
            self.stop()
            self.stop_all()
        except Exception:
            pass
        if self.dev:
            try:
                self.dev.close()
            except Exception:
                pass
        self.dev = None


# ---------------------------------------------------------------- 输出

class VirtualPad:
    BUTTON_MAP = {
        "A": "XUSB_GAMEPAD_A", "B": "XUSB_GAMEPAD_B", "X": "XUSB_GAMEPAD_X",
        "Y": "XUSB_GAMEPAD_Y", "LB": "XUSB_GAMEPAD_LEFT_SHOULDER",
        "RB": "XUSB_GAMEPAD_RIGHT_SHOULDER", "BACK": "XUSB_GAMEPAD_BACK",
        "START": "XUSB_GAMEPAD_START", "LS": "XUSB_GAMEPAD_LEFT_THUMB",
        "RS": "XUSB_GAMEPAD_RIGHT_THUMB", "GUIDE": "XUSB_GAMEPAD_GUIDE",
        "UP": "XUSB_GAMEPAD_DPAD_UP", "DOWN": "XUSB_GAMEPAD_DPAD_DOWN",
        "LEFT": "XUSB_GAMEPAD_DPAD_LEFT", "RIGHT": "XUSB_GAMEPAD_DPAD_RIGHT",
    }

    def __init__(self, rumble_callback=None):
        import vgamepad as vg
        self.vg = vg
        self.pad = vg.VX360Gamepad()
        self._rumble_cb = rumble_callback
        if rumble_callback:
            # 新版 vgamepad 改名了，老版还叫旧名，两个都试
            reg = getattr(self.pad, "register_notification", None) or \
                getattr(self.pad, "register_notification_callback")
            reg(self._on_rumble)

    def _on_rumble(self, client, target, large_motor, small_motor, led_number, user_data):
        if self._rumble_cb:
            try:
                self._rumble_cb(large_motor, small_motor)
            except Exception:
                pass

    def update(self, buttons, axes):
        vg = self.vg
        for name, pressed in buttons.items():
            const = self.BUTTON_MAP.get(name)
            if not const or not hasattr(vg.XUSB_BUTTON, const):
                continue
            btn = getattr(vg.XUSB_BUTTON, const)
            if pressed:
                self.pad.press_button(btn)
            else:
                self.pad.release_button(btn)
        self.pad.left_joystick(int(axes.get("LX", 0) * 32767),
                               int(axes.get("LY", 0) * 32767))
        self.pad.right_joystick(int(axes.get("RX", 0) * 32767),
                                int(axes.get("RY", 0) * 32767))
        lt = int((axes.get("LT", -1) + 1) / 2 * 255)
        rt = int((axes.get("RT", -1) + 1) / 2 * 255)
        self.pad.left_trigger(max(0, min(255, lt)))
        self.pad.right_trigger(max(0, min(255, rt)))
        self.pad.update()

    def reset(self):
        self.pad.reset()
        self.pad.update()


# ---------------------------------------------------------------- 主循环

def run(keymap=None, verbose=False, rumble_callback=None, stop_event=None):
    km = keymap or load_keymap()
    dev = open_device(wait=True)
    pad = VirtualPad(rumble_callback=rumble_callback)
    dz = km.get("deadzone", 0.12)
    tdz = km.get("trigger_deadzone", 0.03)
    print("\n北通手柄已连接，虚拟 Xbox 360 手柄已创建。Ctrl+C 退出。")

    prev_sig = None
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            report = dev.read()
            if not report:
                time.sleep(0.002)
                continue
            report = list(report)

            buttons, axes = parse_report(dev, report, km)
            for k in ("LT", "RT"):
                axes[k] = apply_deadzone(axes[k], tdz)
            for k in ("LX", "LY", "RX", "RY"):
                axes[k] = apply_deadzone(axes[k], dz)

            pad.update(buttons, axes)

            if verbose:
                sig = (tuple(sorted(buttons.items())),
                       tuple(round(axes[k], 2) for k in AXIS_TARGETS))
                if sig != prev_sig:
                    prev_sig = sig
                    on = ",".join(k for k, v in buttons.items() if v)
                    print(f"\r 按键:{on or '-':<26} "
                          f"L({axes['LX']:+.2f},{axes['LY']:+.2f}) "
                          f"R({axes['RX']:+.2f},{axes['RY']:+.2f}) "
                          f"LT{axes['LT']:+.2f} RT{axes['RT']:+.2f}   ",
                          end="", flush=True)
    except KeyboardInterrupt:
        print("\n退出，虚拟手柄已释放")
    finally:
        pad.reset()
        dev.close()


if __name__ == "__main__":
    run(verbose="-v" in sys.argv)
