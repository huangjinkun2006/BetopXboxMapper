# -*- coding: utf-8 -*-
"""震动闹钟：到点让手柄一直震，按手柄上任意一个键就停。

闹钟线程只负责等时间 + 震 + 监听按键；要告诉界面的事全塞进 self.q，
由 Tk 侧 poll() 取走（子线程绝不直接碰 Tk 组件）。
"""
import datetime
import queue
import threading
import time

import betop

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:
    tk = None

DEFAULT_TIME = "07:00"
MAX_RING_SEC = 120          # 最多震两分钟，防止没人管一直震


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

    def set(self, hhmm, on=True, repeat=None, strength=None):
        """改配置。闹钟线程每 0.4 秒看一眼，改完立刻生效"""
        self.km["alarm_time"] = hhmm
        self.km["alarm_on"] = bool(on)
        if repeat is not None:
            self.km["alarm_repeat"] = bool(repeat)
        if strength is not None:
            self.km["alarm_strength"] = float(strength)
        if not on and self.ring_ev.is_set():
            self._finish("闹钟已关闭")

    def cancel_ring(self):
        if self.ring_ev.is_set():
            self._finish("手动停止")

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
                custom=self.km.get("rumble_custom")).open()
        except Exception as e:
            self.q.put(("error", "打不开震动通道：%s" % e))
            return
        self.ring_ev.set()
        self._buzz_stop.clear()
        threading.Thread(target=self._buzz, daemon=True).start()
        threading.Thread(target=self._watch, daemon=True).start()

    def _buzz(self):
        """断断续续地猛震（一直平震容易被人忽略）"""
        s = max(30, min(255, int(255 * float(self.km.get("alarm_strength", 1.0)))))
        t0 = time.time()
        try:
            while not self._buzz_stop.is_set() and time.time() - t0 < MAX_RING_SEC:
                try:
                    self._rm.set(s, s)
                except Exception:
                    pass
                time.sleep(0.45)
                try:
                    self._rm.set(0, 0)
                except Exception:
                    pass
                time.sleep(0.18)
        finally:
            if self.ring_ev.is_set():
                self._finish("响了 %d 秒自动停" % MAX_RING_SEC)

    def _watch(self):
        """监听手柄：任意键 / 扳机 / 摇杆大幅偏移都算“按到了”"""
        pad = None
        try:
            pad = betop.HidPad().open()
        except Exception:
            pad = None
        deadline = time.time() + MAX_RING_SEC + 1
        while not self._buzz_stop.is_set() and time.time() < deadline:
            if self._any_input(pad):
                self._finish("检测到按键，已停止")
                return
            time.sleep(0.04)

    def _any_input(self, pad):
        if pad is not None:
            try:
                r = pad.read()
                if r:
                    buttons, axes = betop.parse_report(pad, list(r), self.km)
                    if buttons:
                        return True
                    for k in ("LX", "LY", "RX", "RY"):
                        if abs(axes.get(k, 0.0)) > 0.6:
                            return True
                    for k in ("LT", "RT"):
                        if abs(axes.get(k, 0.0)) > 0.3:
                            return True
            except Exception:
                pass
            return False
        if self.state_getter is not None:          # 打不开第二路就蹭主界面的状态
            try:
                st = self.state_getter() or {}
                if st.get("buttons"):
                    return True
                a = st.get("axes") or {}
                for k in ("LX", "LY", "RX", "RY"):
                    if abs(a.get(k, 0.0)) > 0.6:
                        return True
                for k in ("LT", "RT"):
                    if abs(a.get(k, 0.0)) > 0.3:
                        return True
            except Exception:
                pass
        return False

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
        return ("还有 %d 小时 %d 分" % (h, m)) if h else ("还有 %d 分 %d 秒"
                                                          % (m, secs % 60))


# ---------------------------------------------------------------- 界面
if tk is not None:
    class AlarmDialog(tk.Toplevel):
        """震动闹钟设置窗"""

        W, H = 420, 400

        def __init__(self, master, app):
            super().__init__(master)
            self.app = app
            self.km = app.km
            self.alarm = app.alarm
            self.title("震动闹钟")
            self.configure(bg="#f5f6f8")
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
            FONT = "Microsoft YaHei UI"
            hd = tk.Frame(self, bg="#fff", height=64)
            hd.pack(fill="x")
            hd.pack_propagate(False)
            tk.Label(hd, text="⏰  震动闹钟", font=(FONT, 15, "bold"),
                     fg="#22252b", bg="#fff").pack(side="left", padx=22)
            tk.Label(hd, text="到点震 · 按任意键停", font=(FONT, 9),
                     fg="#8a8f99", bg="#fff").pack(side="right", padx=22)

            box = tk.Frame(self, bg="#fff", highlightthickness=1,
                           highlightbackground="#e5e7ec")
            box.pack(fill="both", expand=True, padx=20, pady=14)

            # 时间
            row = tk.Frame(box, bg="#fff")
            row.pack(fill="x", padx=18, pady=(16, 6))
            tk.Label(row, text="响铃时间", font=(FONT, 10), fg="#3a3e46",
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
                                font=("Consolas", 13), justify="center",
                                textvariable=var, relief="flat",
                                bg="#f4f5f8", buttonbackground="#f4f5f8")
                sp.pack(side="left", padx=(10, 0))
                var.trace_add("write", lambda *_a: self._apply())
            tk.Label(row, text="（24 小时制）", font=(FONT, 8), fg="#8a8f99",
                     bg="#fff").pack(side="left", padx=8)

            # 选项
            self.rep_var = tk.BooleanVar(
                value=bool(self.km.get("alarm_repeat", True)))
            tk.Checkbutton(box, text="每天重复响（不勾就只响一次）",
                           variable=self.rep_var, font=(FONT, 9),
                           fg="#3a3e46", bg="#fff", activebackground="#fff",
                           selectcolor="#fff",
                           command=self._apply).pack(anchor="w", padx=18,
                                                    pady=(8, 2))

            # 强度
            sr = tk.Frame(box, bg="#fff")
            sr.pack(fill="x", padx=18, pady=(8, 2))
            tk.Label(sr, text="震动强度", font=(FONT, 9), fg="#3a3e46",
                     bg="#fff").pack(side="left")
            self.st_var = tk.DoubleVar(
                value=float(self.km.get("alarm_strength", 1.0)))
            self.st_lbl = tk.Label(sr, text="", font=(FONT, 8), fg="#8a8f99",
                                   bg="#fff")
            self.st_lbl.pack(side="right")
            tk.Scale(sr, from_=0.1, to=3.0, resolution=0.05,
                     variable=self.st_var, orient="horizontal", length=190,
                     bg="#fff", highlightthickness=0, troughcolor="#f0f1f4",
                     command=lambda _v: self._apply()).pack(side="left", padx=8)
            self._upd_st_lbl()

            # 状态 + 倒计时
            self.state_lbl = tk.Label(box, text="", font=(FONT, 11, "bold"),
                                      fg="#8a8f99", bg="#fff")
            self.state_lbl.pack(pady=(20, 2))
            self.cd_lbl = tk.Label(box, text="", font=(FONT, 9), fg="#8a8f99",
                                   bg="#fff")
            self.cd_lbl.pack()

            # 按钮
            br = tk.Frame(self, bg="#f5f6f8")
            br.pack(fill="x", padx=20, pady=(0, 16))
            self.btn_on = tk.Button(br, text="启用闹钟", font=(FONT, 10, "bold"),
                                    bg="#e0334a", fg="#fff", relief="flat",
                                    padx=16, pady=7, cursor="hand2",
                                    command=self.toggle)
            self.btn_on.pack(side="left")
            tk.Button(br, text="现在试响 3 秒", font=(FONT, 10), bg="#fff",
                      fg="#4a4e57", relief="flat", padx=12, pady=7,
                      cursor="hand2", command=self.test_ring).pack(side="left",
                                                                   padx=8)
            tk.Button(br, text="关闭", font=(FONT, 10), bg="#fff",
                      fg="#4a4e57", relief="flat", padx=14, pady=7,
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
                           strength=float(self.st_var.get()))
            try:
                betop.save_keymap(self.km)
            except Exception:
                pass

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
                           strength=float(self.st_var.get()))
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
            self.state_lbl.config(text=("已启用 · %s"
                                        % self.km.get("alarm_time", DEFAULT_TIME)
                                        if on else "未启用"),
                                  fg=("#3a8f5a" if on else "#8a8f99"))

        def test_ring(self):
            """立刻震 3 秒，验证命令格式对不对"""
            def go():
                try:
                    rm = betop.Rumble(
                        fmt=int(self.km.get("rumble_fmt", 0) or 0),
                        custom=self.km.get("rumble_custom")).open()
                except Exception as e:
                    self.after(0, lambda: self.cd_lbl.config(
                        text="打不开震动通道：%s" % e, fg="#c0392b"))
                    return
                s = max(30, min(255, int(255 * float(self.st_var.get()))))
                try:
                    for _i in range(4):
                        rm.set(s, s)
                        time.sleep(0.45)
                        rm.set(0, 0)
                        time.sleep(0.18)
                finally:
                    try:
                        rm.stop()
                        rm.stop_all()
                        rm.close()
                    except Exception:
                        pass
                self.after(0, lambda: self.cd_lbl.config(text="试响完毕"))
            threading.Thread(target=go, daemon=True).start()
            self.cd_lbl.config(text="正在试响…（按手柄任意键不会停，3 秒自动结束）")

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
