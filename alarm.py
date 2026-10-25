# -*- coding: utf-8 -*-
"""震动闹钟：到点让手柄一直震，按手柄上任意一个键就停。

闹钟线程只负责等时间 + 震 + 监听按键；要告诉界面的事全塞进 self.q，
由 Tk 侧 poll() 取走（子线程绝不直接碰 Tk 组件）。
"""
import datetime
import math
import queue
import threading
import time

import betop
from padui import FT, S

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:
    tk = None

DEFAULT_TIME = "07:00"
MAX_RING_SEC = 120          # 最多震两分钟，防止没人管一直震
STEP = 0.05                 # 铃声采样间隔（秒）


# ---------------------------------------------------------------- 铃声库
# 每个铃声是一个函数 f(t, s) -> (大马达, 小马达)，
# t = 从开始响起的秒数，s = 基础强度（已乘过 alarm_strength）。
# 想加新铃声就往 RINGTONES 里塞一组 (名字, 说明, 函数)。
def _r_continuous(t, s):
    """一直猛震，最不容易被忽略"""
    return s, s


def _r_pulse(t, s):
    """急促脉冲：震 0.45 停 0.18"""
    return (s, s) if (t % 0.63) < 0.45 else (0, 0)


def _r_heart(t, s):
    """心跳：咚咚…咚咚…"""
    p = t % 1.6
    return (s, s) if (p < 0.13 or 0.26 <= p < 0.39) else (0, 0)


def _r_ram(t, s):
    """渐强：每 3 秒从 25% 爬到满，叫不醒就一直加码"""
    v = int(s * (0.25 + 0.75 * ((t % 3.0) / 3.0)))
    return v, v


def _r_beep(t, s):
    """三连滴：滴-滴-滴，停一下再来"""
    p = t % 2.0
    return (s, s) if (p < 0.1 or 0.2 <= p < 0.3 or 0.4 <= p < 0.5) else (0, 0)


def _r_wave(t, s):
    """波浪：2 秒一个来回，强弱平滑起伏"""
    v = int(s * (0.35 + 0.65 * (0.5 + 0.5 * math.sin(2 * math.pi * t / 2.0))))
    return v, v


def _r_siren(t, s):
    """警笛：短促连击，间隔由快到慢"""
    p = t % 2.2
    for i, (a, b) in enumerate(((0, .08), (.16, .24), (.36, .44),
                                (.60, .68), (.88, .96))):
        if a <= p < b:
            return s, s
    return 0, 0


def _morse(seq, dot=0.12, dash=0.36):
    """把 '.--' 之类的串变成 [(是否响, 时长), ...]"""
    out = []
    for i, ch in enumerate(seq):
        if ch == ".":
            out.append((1, dot))
        elif ch == "-":
            out.append((1, dash))
        elif ch == " ":
            out.append((0, dash))
        if i < len(seq) - 1:
            out.append((0, dot))
    return out


_SOS = _morse("... --- ...")
_SOS_GAP = 1.6
_SOS_TOTAL = sum(d for _o, d in _SOS) + _SOS_GAP


def _r_sos(t, s):
    """SOS 摩斯电码：... --- ..."""
    p = t % _SOS_TOTAL
    for on, dur in _SOS:
        if p < dur:
            return (s, s) if on else (0, 0)
        p -= dur
    return 0, 0


RINGTONES = [
    ("连续猛震", "一直震到停，最不容易睡过头", _r_continuous),
    ("急促脉冲", "震 0.45 秒停 0.18 秒，最有节奏感", _r_pulse),
    ("心跳", "咚咚…咚咚…，像有人在拍你", _r_heart),
    ("渐强", "每 3 秒从 25% 爬到满，越拖越猛", _r_ram),
    ("三连滴", "滴-滴-滴，停一下再来", _r_beep),
    ("波浪", "2 秒一个来回，强弱平滑起伏", _r_wave),
    ("警笛", "短促连击，间隔由快到慢", _r_siren),
    ("SOS 摩斯", "…---…，好玩但费马达", _r_sos),
]


def ringtone(idx):
    """按下标取铃声，越界就退回第 0 个"""
    try:
        i = int(idx)
    except Exception:
        i = 0
    if i < 0 or i >= len(RINGTONES):
        i = 0
    return RINGTONES[i]


def ring_names():
    return [r[0] for r in RINGTONES]


def play_ring(rm, idx, strength, seconds, stop_ev=None, on_done=None):
    """按选中的铃声震 seconds 秒；stop_ev 被置位就立刻停并归零"""
    _name, _desc, fn = ringtone(idx)
    base = max(30, min(255, int(255 * float(strength or 1.0))))
    t0 = time.time()
    try:
        while time.time() - t0 < seconds:
            if stop_ev is not None and stop_ev.is_set():
                break
            try:
                big, small = fn(time.time() - t0, base)
                rm.set(big, small)
            except Exception:
                pass
            time.sleep(STEP)
    finally:
        try:
            rm.set(0, 0)
            rm.stop()
            rm.stop_all()
        except Exception:
            pass
        if on_done is not None:
            try:
                on_done()
            except Exception:
                pass


class AlarmClock:
    """到点震、按任意键停"""

    def __init__(self, km, state_getter=None):
        self.km = km
        self.state_getter = state_getter     # 映射跑着的时候直接从主界面取按键状态
        self.q = queue.Queue()
        self.stop_ev = threading.Event()     # True = 整个线程退出（关程序时）
        self.ring_ev = threading.Event()     # True = 正在响
        self._buzz_stop = threading.Event()
        self._rm = None
        self._thread = None
        self.next_at = None

    # ------------------------------------------------------------ 配置
    @property
    def enabled(self):
        return bool(self.km.get("alarm_on"))

    @property
    def time_str(self):
        return str(self.km.get("alarm_time") or DEFAULT_TIME)

    def start(self):
        if self._thread is None or not self._thread.is_alive():
            self.stop_ev.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def shutdown(self):
        self.stop_ev.set()
        if self.ring_ev.is_set():
            self._finish("程序退出，闹钟已停")

    @property
    def ring_index(self):
        return int(self.km.get("alarm_ring", 0) or 0)

    def set(self, hhmm, on=True, repeat=None, strength=None, ring=None):
        """改配置。闹钟线程每 0.4 秒看一眼，改完立刻生效"""
        self.km["alarm_time"] = hhmm
        self.km["alarm_on"] = bool(on)
        if repeat is not None:
            self.km["alarm_repeat"] = bool(repeat)
        if strength is not None:
            self.km["alarm_strength"] = float(strength)
        if ring is not None:
            self.km["alarm_ring"] = int(ring)
        if not on and self.ring_ev.is_set():
            self._finish("闹钟已关闭")

    def cancel_ring(self):
        if self.ring_ev.is_set():
            self._finish("手动停止")

    def trigger_now(self):
        """不等设定时间，立刻按完整流程响一次：按任意键停，最多 MAX_RING_SEC"""
        if self.ring_ev.is_set():
            return False
        self._fire()
        return True

    # ------------------------------------------------------------ 主循环
    def _next_dt(self, hhmm=None):
        try:
            h, m = [int(x) for x in (hhmm or self.time_str).split(":")[:2]]
        except Exception:
            h, m = 7, 0
        h, m = max(0, min(23, h)), max(0, min(59, m))
        now = datetime.datetime.now()
        t = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if t <= now:                      # 今天这个点过了就等明天
            t += datetime.timedelta(days=1)
        return t

    def _loop(self):
        while not self.stop_ev.is_set():
            if not self.enabled:
                self.next_at = None
                if self.stop_ev.wait(1.0):
                    return
                continue
            hhmm = self.time_str
            target = self._next_dt(hhmm)
            self.next_at = target
            self.q.put(("armed", target.strftime("%H:%M")))
            now = datetime.datetime.now()
            while now < target:
                if self.stop_ev.wait(0.4):
                    return
                now = datetime.datetime.now()
                if str(self.km.get("alarm_time")) != hhmm or not self.enabled:
                    break            # 配置改了，重算
            else:
                self._fire()
                if not self.km.get("alarm_repeat", True):
                    self.km["alarm_on"] = False
                    self.q.put(("off", "响完了，一次性闹钟已自动关闭"))
                    return
                time.sleep(2.0)       # 别刚响完又立刻触发
                continue
            continue

    # ------------------------------------------------------------ 响铃
    def _fire(self):
        self.q.put(("fired", self.time_str))
        try:
            self._rm = betop.Rumble(
                fmt=int(self.km.get("rumble_fmt", 0) or 0),
                custom=self.km.get("rumble_custom"),
                custom_trig=self.km.get("rumble_custom_trig"),
                merge=bool(self.km.get("rumble_merge", True))).open()
        except Exception as e:
            self.q.put(("error", "打不开震动通道：%s" % e))
            return
        self.ring_ev.set()
        self._buzz_stop.clear()
        threading.Thread(target=self._buzz, daemon=True).start()
        threading.Thread(target=self._watch, daemon=True).start()

    def _buzz(self):
        """按选中的铃声震，直到被按键叫停或超时"""
        idx = self.ring_index
        try:
            play_ring(self._rm, idx, self.km.get("alarm_strength", 1.0),
                      MAX_RING_SEC, self._buzz_stop)
        finally:
            if self.ring_ev.is_set():
                self._finish("响了 %d 秒自动停" % MAX_RING_SEC)

    def _watch(self):
        """监听手柄：任意键 / 扳机 / 摇杆大幅偏移都算“按到了”

        响铃头 0.5 秒先不判断，免得刚震起来就被残留输入掐掉。
        """
        pad = None
        try:
            pad = betop.HidPad().open()
        except Exception:
            pad = None
        deadline = time.time() + MAX_RING_SEC + 1
        t0 = time.time()
        while not self._buzz_stop.is_set() and time.time() < deadline:
            if time.time() - t0 > 0.5 and self._any_input(pad):
                self._finish("检测到按键，已停止")
                return
            time.sleep(0.04)

    def _any_input(self, pad):
        """两条路都查：主界面的实时状态（映射跑着时最准）+ 自己开的第二路 HID。

        两个坑：
        1) buttons 是 {'A': False, ...} 这种全 False 的字典，
           `if buttons:` 对非空 dict 恒为真 —— 必须用 any(values())
        2) 扳机没扣时解出来是 -1.0（松开到底），abs(-1) > 0.3 也恒真，
           所以扳机只能判正方向：> 0.3 才算真的扣下去了
        """
        for st in (self._state_from_app(), self._state_from_pad(pad)):
            if st is None:
                continue
            buttons, axes = st
            if (any(buttons.values()) if isinstance(buttons, dict)
                    else bool(buttons)):
                return True
            for k in ("LX", "LY", "RX", "RY"):
                if abs(axes.get(k, 0.0)) > 0.6:
                    return True
            for k in ("LT", "RT"):
                if axes.get(k, -1.0) > 0.3:
                    return True
        return False

    def _state_from_app(self):
        """主界面正在跑映射时，直接蹭它的按键状态"""
        if self.state_getter is None:
            return None
        try:
            st = self.state_getter() or {}
            return (st.get("buttons") or {}, st.get("axes") or {})
        except Exception:
            return None

    def _state_from_pad(self, pad):
        """自己再开一路 HID 读（没启动映射时靠它）"""
        if pad is None:
            return None
        try:
            r = pad.read()
            if not r:
                return None
            return betop.parse_report(pad, list(r), self.km)
        except Exception:
            return None

    def _finish(self, why):
        if not self.ring_ev.is_set():
            return
        self.ring_ev.clear()
        self._buzz_stop.set()
        rm, self._rm = self._rm, None
        if rm is not None:
            try:
                rm.stop()
                rm.stop_all()
                rm.close()
            except Exception:
                pass
        self.q.put(("stopped", why))

    # ------------------------------------------------------------ 给界面
    def poll(self):
        out = []
        while True:
            try:
                out.append(self.q.get_nowait())
            except queue.Empty:
                break
        return out

    def countdown(self):
        """距离下次响铃还有多久，不启用就返回 None"""
        if self.ring_ev.is_set():
            return "正在响！按手柄任意键停止"
        if not self.enabled:
            return None
        if self.next_at is None:
            return "等待中…"
        d = self.next_at - datetime.datetime.now()
        secs = int(d.total_seconds())
        if secs <= 0:
            return "马上就要响了"
        h, m = secs // 3600, (secs % 3600) // 60
        when = "" if self.next_at.date() == datetime.date.today() else "明天 "
        return (("%s还有 %d 小时 %d 分" % (when, h, m)) if h else
                ("%s还有 %d 分 %d 秒" % (when, m, secs % 60)))


# ---------------------------------------------------------------- 界面
if tk is not None:
    class AlarmDialog(tk.Toplevel):
        """震动闹钟设置窗"""

        W, H = S(420), S(486)

        def __init__(self, master, app):
            super().__init__(master)
            self.app = app
            self.km = app.km
            self.alarm = app.alarm
            self.title("震动闹钟")
            self.configure(bg="#f5f6f8")
            try:
                from padui import apply_icon
                apply_icon(self)
            except Exception:
                pass
            self.resizable(False, False)
            self.transient(master)
            try:
                self.grab_set()
            except Exception:
                pass
            self._place(master)
            self.protocol("WM_DELETE_WINDOW", self.destroy)
            self._build()
            self._tick()

        def _place(self, master):
            try:
                self.update_idletasks()
                x = master.winfo_rootx() + (master.winfo_width() - self.W) // 2
                y = master.winfo_rooty() + (master.winfo_height() - self.H) // 2
                self.geometry("%dx%d+%d+%d" % (self.W, self.H, max(0, x),
                                               max(0, y)))
            except Exception:
                self.geometry("%dx%d" % (self.W, self.H))

        def _build(self):
            from padui import FT, S
            FONT = "Microsoft YaHei UI"
            hd = tk.Frame(self, bg="#fff", height=64)
            hd.pack(fill="x")
            hd.pack_propagate(False)
            tk.Label(hd, text="⏰  震动闹钟", font=FT(15, "bold"),
                     fg="#22252b", bg="#fff").pack(side="left", padx=S(22))
            tk.Label(hd, text="到点震 · 按任意键停", font=FT(9),
                     fg="#8a8f99", bg="#fff").pack(side="right", padx=S(22))

            box = tk.Frame(self, bg="#fff", highlightthickness=1,
                           highlightbackground="#e5e7ec")
            box.pack(fill="both", expand=True, padx=S(20), pady=S(14))

            # 时间
            row = tk.Frame(box, bg="#fff")
            row.pack(fill="x", padx=S(18), pady=(S(16), S(6)))
            tk.Label(row, text="响铃时间", font=FT(10), fg="#3a3e46",
                     bg="#fff").pack(side="left")
            try:
                h, m = [int(x) for x in self.km.get(
                    "alarm_time", DEFAULT_TIME).split(":")[:2]]
            except Exception:
                h, m = 7, 0
            self.h_var = tk.StringVar(value="%02d" % h)
            self.m_var = tk.StringVar(value="%02d" % m)
            for var, hi, w in ((self.h_var, 23, 3), (self.m_var, 59, 3)):
                sp = tk.Spinbox(row, from_=0, to=hi, width=w, format="%02.0f",
                                font=FT(13, family="Consolas"), justify="center",
                                textvariable=var, relief="flat",
                                bg="#f4f5f8", buttonbackground="#f4f5f8")
                sp.pack(side="left", padx=(10, 0))
                var.trace_add("write", lambda *_a: self._apply())
            tk.Label(row, text="（24 小时制）", font=FT(8), fg="#8a8f99",
                     bg="#fff").pack(side="left", padx=S(8))

            # 选项
            self.rep_var = tk.BooleanVar(
                value=bool(self.km.get("alarm_repeat", True)))
            tk.Checkbutton(box, text="每天重复响（不勾就只响一次）",
                           variable=self.rep_var, font=FT(9),
                           fg="#3a3e46", bg="#fff", activebackground="#fff",
                           selectcolor="#fff",
                           command=self._apply).pack(anchor="w", padx=S(18),
                                                    pady=(S(8), S(2)))

            # 强度
            sr = tk.Frame(box, bg="#fff")
            sr.pack(fill="x", padx=S(18), pady=(S(8), S(2)))
            tk.Label(sr, text="震动强度", font=FT(9), fg="#3a3e46",
                     bg="#fff").pack(side="left")
            self.st_var = tk.DoubleVar(
                value=float(self.km.get("alarm_strength", 1.0)))
            self.st_lbl = tk.Label(sr, text="", font=FT(8), fg="#8a8f99",
                                   bg="#fff")
            self.st_lbl.pack(side="right")
            tk.Scale(sr, from_=0.1, to=3.0, resolution=0.05,
                     variable=self.st_var, orient="horizontal", length=190,
                     bg="#fff", highlightthickness=0, troughcolor="#f0f1f4",
                     command=lambda _v: self._apply()).pack(side="left", padx=S(8))
            self._upd_st_lbl()

            # 铃声
            rr = tk.Frame(box, bg="#fff")
            rr.pack(fill="x", padx=S(18), pady=(S(12), S(2)))
            tk.Label(rr, text="铃声", font=FT(9), fg="#3a3e46",
                     bg="#fff").pack(side="left")
            names = ring_names()
            self.ring_var = tk.StringVar(value=names[self.alarm.ring_index])
            om = tk.OptionMenu(rr, self.ring_var, *names)
            om.config(font=FT(9), bg="#fff", relief="flat", width=11,
                      highlightthickness=0, activebackground="#e0334a",
                      activeforeground="#fff", cursor="hand2")
            try:
                om["menu"].config(font=FT(9), bg="#fff")
            except Exception:
                pass
            om.pack(side="left", padx=S(8))
            self.ring_desc = tk.Label(box, text="", font=FT(8),
                                      fg="#8a8f99", bg="#fff", wraplength=S(350),
                                      justify="left")
            self.ring_desc.pack(anchor="w", padx=S(20), pady=(S(0), S(2)))
            self.ring_var.trace_add("write", lambda *_a: self._on_ring())
            self._upd_ring_desc()

            # 状态 + 倒计时
            self.state_lbl = tk.Label(box, text="", font=FT(11, "bold"),
                                      fg="#8a8f99", bg="#fff")
            self.state_lbl.pack(pady=(S(20), S(2)))
            self.cd_lbl = tk.Label(box, text="", font=FT(9), fg="#8a8f99",
                                   bg="#fff")
            self.cd_lbl.pack()

            # 按钮
            br = tk.Frame(self, bg="#f5f6f8")
            br.pack(fill="x", padx=S(20), pady=(S(0), S(16)))
            self.btn_on = tk.Button(br, text="启用闹钟", font=FT(10, "bold"),
                                    bg="#e0334a", fg="#fff", relief="flat",
                                    padx=S(12), pady=S(7), cursor="hand2",
                                    command=self.toggle)
            self.btn_on.pack(side="left")
            self.btn_test = tk.Button(br, text="试听铃声", font=FT(10),
                                      bg="#fff", fg="#4a4e57", relief="flat",
                                      padx=S(10), pady=S(7), cursor="hand2",
                                      command=self.test_ring)
            self.btn_test.pack(side="left", padx=S(6))
            tk.Button(br, text="立即响", font=FT(10), bg="#fff",
                      fg="#e0334a", relief="flat", padx=S(10), pady=S(7),
                      cursor="hand2", command=self.ring_now).pack(side="left")
            tk.Button(br, text="关闭", font=FT(10), bg="#fff",
                      fg="#4a4e57", relief="flat", padx=S(14), pady=S(7),
                      cursor="hand2", command=self.destroy).pack(side="right")
            self._upd_btn()

        # ------------------------------------------------------------
        def _upd_st_lbl(self):
            try:
                self.st_lbl.config(text="%d%%" % int(self.st_var.get() * 100))
            except Exception:
                pass

        def _apply(self):
            self._upd_st_lbl()
            hhmm = "%02d:%02d" % (self._int(self.h_var.get(), 7),
                                  self._int(self.m_var.get(), 0))
            self.alarm.set(hhmm, on=bool(self.km.get("alarm_on")),
                           repeat=bool(self.rep_var.get()),
                           strength=float(self.st_var.get()),
                           ring=self._ring_idx())
            try:
                betop.save_keymap(self.km)
            except Exception:
                pass

        # ------------------------------------------------------------ 铃声
        def _ring_idx(self):
            """下拉里选中的名字 -> RINGTONES 下标"""
            try:
                return ring_names().index(self.ring_var.get())
            except Exception:
                return 0

        def _upd_ring_desc(self):
            try:
                self.ring_desc.config(text=ringtone(self._ring_idx())[1])
            except Exception:
                pass

        def _on_ring(self):
            self._upd_ring_desc()
            idx = self._ring_idx()
            self.alarm.set(self.km.get("alarm_time", DEFAULT_TIME),
                           on=bool(self.km.get("alarm_on")),
                           repeat=bool(self.rep_var.get()),
                           strength=float(self.st_var.get()), ring=idx)
            try:
                betop.save_keymap(self.km)
            except Exception:
                pass
            self._test_stop()      # 换铃声就把正在试听的掐掉

        @staticmethod
        def _int(v, dft):
            try:
                return max(0, min(59, int(str(v).strip())))
            except Exception:
                return dft

        def toggle(self):
            on = not bool(self.km.get("alarm_on"))
            hhmm = "%02d:%02d" % (self._int(self.h_var.get(), 7),
                                  self._int(self.m_var.get(), 0))
            self.alarm.set(hhmm, on=on, repeat=bool(self.rep_var.get()),
                           strength=float(self.st_var.get()),
                           ring=self._ring_idx())
            self._upd_btn()
            try:
                betop.save_keymap(self.km)
            except Exception:
                pass
            if on:
                self.app.tray and self.app.tray.notify(
                    "闹钟已启用：%s" % hhmm, "震动闹钟")

        def _upd_btn(self):
            on = bool(self.km.get("alarm_on"))
            self.btn_on.config(text=("停用闹钟" if on else "启用闹钟"),
                               bg=("#5a5e66" if on else "#e0334a"))
            if on:
                txt = "已启用 · %s · %s" % (
                    self.km.get("alarm_time", DEFAULT_TIME),
                    ringtone(self.km.get("alarm_ring", 0))[0])
            else:
                txt = "未启用"
            self.state_lbl.config(text=txt,
                                  fg=("#3a8f5a" if on else "#8a8f99"))

        def ring_now(self):
            """立刻按闹钟完整流程响一次（按手柄任意键停，最多 2 分钟）"""
            self._apply()
            self._test_stop()
            if self.alarm.trigger_now():
                self.cd_lbl.config(text="正在响！按手柄任意键停止",
                                   fg="#e0334a")
            else:
                self.cd_lbl.config(text="已经在响了", fg="#c9a227")

        def _test_stop(self):
            """掐掉正在试听的铃声（换铃声 / 关窗时都调一次）"""
            ev = getattr(self, "_test_ev", None)
            if ev is not None:
                try:
                    ev.set()
                except Exception:
                    pass

        def test_ring(self):
            """用当前选中的铃声试听 5 秒，再点一次按钮立刻停"""
            if getattr(self, "_test_ev", None) is not None:
                self._test_stop()
                return
            idx = self._ring_idx()
            st = float(self.st_var.get())
            ev = threading.Event()
            self._test_ev = ev
            self.btn_test.config(text="停止试听", fg="#e0334a")
            self.cd_lbl.config(text="正在用「%s」试听…（再点按钮停止）"
                                    % ringtone(idx)[0], fg="#8a8f99")

            def done():
                self._test_ev = None
                try:
                    self.after(0, lambda: (
                        self.btn_test.config(text="试听铃声", fg="#4a4e57"),
                        self.cd_lbl.config(text="试听完毕", fg="#3a8f5a")))
                except Exception:
                    pass

            def go():
                try:
                    rm = betop.Rumble(
                        fmt=int(self.km.get("rumble_fmt", 0) or 0),
                        custom=self.km.get("rumble_custom"),
                custom_trig=self.km.get("rumble_custom_trig"),
                merge=bool(self.km.get("rumble_merge", True))).open()
                except Exception as e:
                    self.after(0, lambda: self.cd_lbl.config(
                        text="打不开震动通道：%s" % e, fg="#c0392b"))
                    done()
                    return
                try:
                    play_ring(rm, idx, st, 5.0, ev)
                finally:
                    try:
                        rm.close()
                    except Exception:
                        pass
                done()

            threading.Thread(target=go, daemon=True).start()

        def destroy(self):
            """关窗时别把铃声留在震着"""
            try:
                self._test_stop()
            except Exception:
                pass
            try:
                super().destroy()
            except Exception:
                pass

        def _tick(self):
            try:
                self.cd_lbl_cd = self.alarm.countdown()
                if self.cd_lbl.cget("text") != (self.cd_lbl_cd or ""):
                    self.cd_lbl.config(text=(self.cd_lbl_cd or "—"),
                                       fg=("#e0334a" if self.alarm.ring_ev.is_set()
                                           else "#8a8f99"))
                self._upd_btn()
                for ev in self.alarm.poll():
                    kind = ev[0]
                    if kind == "fired":
                        self.cd_lbl.config(text="正在响！按手柄任意键停止",
                                           fg="#e0334a")
                    elif kind == "stopped":
                        self.cd_lbl.config(text="已停：%s" % ev[1], fg="#3a8f5a")
                    elif kind == "error":
                        self.cd_lbl.config(text=ev[1], fg="#c0392b")
            except Exception:
                return
            self.after(400, self._tick)
else:
    AlarmDialog = None      # 无界面环境
