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
        # 独占打开手柄接口：开了以后游戏 / DirectInput 就枚举不到物理手柄了，
        # 屏幕上只剩虚拟 Xbox 那一把（原神这类游戏不然会显示两个手柄）。
        # 必须在游戏之前开 —— 游戏先占上手柄的话这里会打不开。
        "exclusive": False,
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
            # 中央三键（2026-10-25 定案）：左上角返回键 = 11、右上角菜单键 = 12
            # （就是 SDL 映射串的 bit10 / bit11），蓝色箭头 LOGO 键 = 105
            # （消费页 0x0C，走 byte4 的 bit7）。
            # 之前把 105 当成 FN 是错的：FN 键固件压根不上报，按下去没有任何
            # 数据，它已经从键位表里删掉了（界面里那个 FN 方块只是装饰）。
            "BACK": 11, "START": 12,
            "LS": 14, "RS": 15,
            "GUIDE": 105,
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
    # 2026-10-25 更正：FN 键固件压根不上报，之前记的 usage 105 是 LOGO 键。
    # 老配置里的 FN 直接丢掉（不然按 LOGO 会误点亮一个不存在的键），
    # 顺手把记成 12 的 GUIDE 纠正成 105。
    km.get("buttons", {}).pop("FN", None)
    km.pop("fn_out", None)
    km.setdefault("exclusive", False)
    km.setdefault("buttons", {})
    # 老配置把中央三键记反过（BACK=16 / START=11 / GUIDE=12），这里纠正成
    # 现在的定案值；LOGO 写成 12 或 16 的也统一改成 105
    if km["buttons"].get("BACK") == 16 and km["buttons"].get("START") == 11:
        km["buttons"]["BACK"], km["buttons"]["START"] = 11, 12
    if km["buttons"].get("GUIDE") in (None, 12, 16):
        km["buttons"]["GUIDE"] = 105
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

    def open(self, exclusive=False):
        # 不锁死 PID：切模式或换连接方式 PID 可能变，只要是北通(20BC)就认
        path, in_len = hidraw.find_gamepad(VID, None)
        if path is None:
            raise RuntimeError("没找到北通手柄（VID 20BC），检查有线/蓝牙是否连上")
        self.dev = hidraw.RawHid().open_path(path, exclusive=exclusive)
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


def open_device(wait=False, timeout=180, exclusive=False):
    t0 = time.time()
    while True:
        try:
            return HidPad().open(exclusive=exclusive)
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
        if len(report) > 4 and report[4] & 0x80:
            pressed.add(105)          # LOGO 键（byte4 bit7）

    buttons = {}
    for tgt in BUTTON_TARGETS:
        usage = km["buttons"].get(tgt)
        buttons[tgt] = bool(usage) and usage in pressed

    # LOGO 键兜底：固件实测发 105，老配置里还有写成 12 / 16 的，都试一下；
    # 但已经被 BACK / START 占掉的 usage 不算，免得按 LOGO 串到别的键上
    if not buttons.get("GUIDE"):
        used = {km["buttons"].get("BACK"), km["buttons"].get("START")}
        for u in (105, 12, 16):
            if u not in used and u in pressed:
                buttons["GUIDE"] = True
                break

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


def _norm_motor(m):
    """马达槽位归一化。旧模板 motor 是 [左柄, 右柄] 两个偏移；
    新模板是 {"big":off, "small":off, "tl":off, "tr":off}，四个槽各自独立，
    没扫出来的马达就不在里面（发了也没字段可写）。"""
    if isinstance(m, dict):
        return {k: int(v) for k, v in m.items()
                if v and k in ("big", "small", "tl", "tr")}
    if isinstance(m, (list, tuple)):
        out = {}
        if len(m) >= 1 and m[0]:
            out["big"] = int(m[0])
        if len(m) >= 2 and m[1]:
            out["small"] = int(m[1])
        return out
    return {}


class Rumble:
    """把虚拟手柄收到的震动指令转发给物理手柄。

    这把定制版有四套马达：左柄（大）、右柄（小）、左扳机、右扳机
    （官方 GO柄 app 里就有「手柄马达 / 扳机马达」两个测试页）。
    - 手柄马达：命令模板 rumble_custom（ motor 槽位 big/small ）
    - 扳机马达：私有协议另一条命令，模板 custom_trig（槽位 tl/tr），
      游戏走 XInput 只有两大马达信号，扳机只能本地测试或开「跟随」
    """

    # 固件收到命令只会震很短一下（不像 XInput 会自己持续），
    # 所以要不停重发，游戏里的持续震动才不会变成"抖一下"。
    HB_INTERVAL = 0.20

    _LIVE = []      # 所有存活的 Rumble 实例（含临时测试用的），给界面抖动联动

    @classmethod
    def max_level(cls):
        """当前全部实例的最大马达强度 0.0~1.0；没在震就是 0"""
        act = [r for r in cls._LIVE
               if getattr(r, "_target", None) not in (None, (0, 0, 0, 0))]
        if not act:
            return 0.0
        return min(1.0, max(max(r._target) for r in act) / 255.0)

    def __init__(self, fmt=0, enabled=True, custom=None, custom_trig=None,
                 merge=True):
        Rumble._LIVE.append(self)
        self.dev = None
        self.fmt = fmt
        self.enabled = enabled
        self._last = None
        self._target = (0, 0, 0, 0)      # big small tl tr
        self._hb_stop = threading.Event()
        self._hb = None
        # merge：不分左右/扳机，四个马达共用同一条命令、同一个强度
        # （反正都是震动，能震就行；只找到一条可用命令时也靠它让全部马达都响）
        self.merge = merge
        # custom = 实验室比出来的冠军命令，形如
        #   {"chan": "write"/"set", "fixed": [(偏移, 值)...],
        #    "motor": {"big": off, "small": off, ...}}
        # motor 槽位对应的字节会被马达强度覆盖；有它就不用猜格式了
        self.custom = custom
        # 扳机马达的独立命令（没有就代表还没扫出来，扳机发不出东西）
        self.custom_trig = custom_trig

    # ------------------------------------------------------ 造帧
    @staticmethod
    def _build(tpl, vals):
        b = [2] + [0] * 63
        for off, val in tpl.get("fixed") or []:
            if 0 <= off < 64:
                b[off] = val
        for key, off in _norm_motor(tpl.get("motor")).items():
            if 0 <= off < 64:
                b[off] = vals.get(key, 0) & 0xFF
        return b

    def _vals(self, l, r, tl, tr):
        """合并模式下四个槽位都写同一个值（取最大），不然各写各的"""
        if self.merge:
            m = max(l, r, tl, tr)
            return {"big": m, "small": m, "tl": m, "tr": m}
        return {"big": l, "small": r, "tl": tl, "tr": tr}

    def frame(self, l, r, tl=0, tr=0):
        """主帧：手柄马达（没配自定义模板就退回下拉里的候选格式）"""
        c = self.custom
        v = self._vals(l, r, tl, tr)
        if not c:
            return RUMBLE_FORMATS[self.fmt][2](v["big"], v["small"])
        return self._build(c, v)

    def trig_frames(self, tl, tr):
        """扳机马达的帧；没配独立模板返回 []"""
        if not self.custom_trig:
            return []
        return [self._build(self.custom_trig, self._vals(0, 0, tl, tr))]

    def frames(self, l, r, tl=0, tr=0):
        out = [self.frame(l, r, tl, tr)]
        out += self.trig_frames(tl, tr)
        return out

    def has_motor(self, which):
        """这个马达有没有可用的命令模板（发了有没有效果）"""
        if self.merge:
            # 合并模式下四个马达共用一条命令，只要能震就都算能震
            return True
        if which in ("tl", "tr"):
            t = self.custom_trig
            return bool(t and _norm_motor(t.get("motor")).get(which))
        if self.custom is None:
            return True          # 下拉候选格式左右槽都在
        return bool(_norm_motor(self.custom.get("motor")).get(which))

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
            big, small, tl, tr = self._target
            if (big or small or tl or tr) and self.dev is not None \
                    and self.enabled:
                try:
                    for f in self.frames(big, small, tl, tr):
                        self._send(f)
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

    def set(self, big, small, tl=0, tr=0):
        """四个马达 0..255。游戏信号只来 big/small，扳机要跟随或测试才有"""
        if self.dev is None or not self.enabled:
            return
        v = tuple(max(0, min(255, int(x))) for x in (big, small, tl, tr))
        self._target = v
        key = v + (self.fmt, id(self.custom_trig))
        if key == self._last:      # 值没变就不用立刻重写，心跳会续着
            if any(v):
                self._ensure_hb()
            return
        self._last = key
        try:
            for f in self.frames(*v):
                self._send(f)
        except Exception:
            pass
        if any(v):
            self._ensure_hb()      # 只要还在震就一直续发

    def play_once(self, idx, strength=255, secs=0.9):
        """试震 / 自动扫描用：按指定格式发一段固定强度的震动"""
        self.fmt = max(0, min(idx, len(RUMBLE_FORMATS) - 1))
        self._last = None
        self._send(self.frame(strength, strength))

    def play_motor(self, which, strength=255, secs=0.9):
        """单马达试震。which: big=左柄 / small=右柄 / tl=左扳机 / tr=右扳机"""
        s = max(0, min(255, int(strength)))
        if self.merge:                  # 合并模式下点哪个都是四个一起震
            fs = self.frames(s, s, s, s)
            t0 = time.time()
            while time.time() - t0 < secs:
                for f in fs:
                    self._send(f)
                time.sleep(0.05)
            for z in self.frames(0, 0, 0, 0):
                try:
                    self._send(z)
                except Exception:
                    pass
            return
        vals = {"big": 0, "small": 0, "tl": 0, "tr": 0}
        vals[which] = s
        if which in ("tl", "tr"):
            fs = self.trig_frames(vals["tl"], vals["tr"])
            if not fs:
                raise RuntimeError("还没给扳机马达扫出命令，先点「扫描马达命令」")
        else:
            fs = [self.frame(vals["big"], vals["small"])]
        t0 = time.time()
        while time.time() - t0 < secs:
            for f in fs:
                self._send(f)
            time.sleep(0.05)
        for z in self.frames(0, 0, 0, 0):
            try:
                self._send(z)
            except Exception:
                pass

    def stop(self):
        """用当前格式回写 0，让马达停转"""
        self._last = None
        self._target = (0, 0, 0, 0)     # 四个马达全停，别写成两元组
        if self.dev is None:
            return
        try:
            for f in self.frames(0, 0, 0, 0):
                self._send(f)
        except Exception:
            pass

    def stop_all(self):
        """保险起见，把所有已知载荷都清一遍（有手柄收到某条命令后会一直震）"""
        self._last = None
        self._target = (0, 0, 0, 0)
        if self.dev is None:
            return
        if self.custom:               # 自定义冠军命令也要回写 0
            try:
                z = self.frame(0, 0)
                self.dev.write(z)
                self.dev.set_report(z)
            except Exception:
                pass
        if self.custom_trig:          # 扳机模板同样要归零，不然会一直震
            try:
                z = self._build(self.custom_trig, {})
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
        try:
            Rumble._LIVE.remove(self)
        except ValueError:
            pass


def battery_info(vid=VID, tries=6):
    """尽力读手柄电量（电量是 HID 标准_usage，能不能读全看固件报不报）。

    返回：
      None               手柄不在线
      ("usb", None)      在线，但读不到电量（插 USB 线供电时常见）
      (percent, None)    读到了 0~100 的电量
    注意：要开第二个 HID 句柄读报告，可能花 1~2 秒，放线程里调。
    """
    import hidraw
    rows = hidraw.list_devices(vid)
    if not rows:
        return None
    devs = []
    try:
        for _v, _p, _up, _us, _inlen, path in rows:
            try:
                d = hidraw.RawHid()
                d.open_path(path)
                devs.append(d)
            except Exception:
                pass
        for _ in range(tries):
            for d in devs:
                r = d.read()
                if not r:
                    continue
                # 电池系统页(0x85)的强度 / 通用桌面页的 Battery Strength
                for page, usage in ((0x85, 0x85), (0x01, 0x85), (0x85, 0x20)):
                    v = d.usage_value(r, page, usage)
                    if v is not None and 0 <= v <= 100:
                        return (int(v), None)
        return ("usb", None)
    finally:
        for d in devs:
            try:
                d.close()
            except Exception:
                pass


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

    def __init__(self, rumble_callback=None, fn_out=None):
        import vgamepad as vg
        self.vg = vg
        # 实例级副本：改键时只改自己，别污染类上的那份
        self.BUTTON_MAP = dict(self.BUTTON_MAP)
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
