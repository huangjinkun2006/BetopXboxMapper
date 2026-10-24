"""北通 -> Xbox 360 映射器 图形界面（北通游戏厅风格 + 中央实时手柄图）。
双击 start_gui.py 打开这个。
"""
import os
import sys

# ---- 依赖自举：当前解释器缺 vgamepad 就自动切到装好的那个 Python ----
# 打包成 exe 后依赖已经打进去了，不能再切回 venv
VENV_PY = r"C:\Users\黄锦坤\.workbuddy\binaries\python\envs\py312\Scripts\python.exe"
if not getattr(sys, "frozen", False):
    try:
        import vgamepad  # noqa: F401
    except ImportError:
        if os.path.exists(VENV_PY) and os.path.abspath(sys.executable).lower() != VENV_PY.lower():
            os.execv(VENV_PY, [VENV_PY, os.path.abspath(__file__)] + sys.argv[1:])

import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import betop
import guide
import lab
import alarm
import tray
import updater

HERE = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.abspath(__file__)))

BTN_ORDER = ["Y", "X", "B", "A", "LB", "RB", "BACK", "START", "LS", "RS", "GUIDE"]
BTN_CN = {"Y": "Y", "X": "X", "B": "B", "A": "A", "LB": "LB", "RB": "RB",
          "BACK": "BACK", "START": "START", "LS": "L3", "RS": "R3", "GUIDE": "LOGO"}

# 托盘右键菜单 id
T_SHOW, T_TOGGLE, T_ALARM, T_TEST, T_UPDATE, T_EXIT = 1, 2, 3, 4, 5, 6

# 配色 / 手柄图统一放在 padui.py（识别向导 wizard.py 用的是同一套）
from padui import (C_BG, C_CARD, C_ACC, C_ACC_DK, C_ACC_LT, C_TEXT, C_SUB,
                   C_LINE, C_OK, C_PRESS, P_IDLE, FONT, round_rect, PadView)

C_RED = C_ACC          # 旧变量名兼容
C_RED_DK = C_ACC_DK


class App:
    def __init__(self, root):
        self.root = root
        root.title("北通游戏厅 · 手柄映射器")
        root.geometry("1080x730")
        root.resizable(False, False)
        root.configure(bg=C_BG)

        self.km = betop.load_keymap()
        self.dev = None
        self.pad = None
        self.running = False
        self.stop = threading.Event()
        self.state = {"buttons": {}, "axes": {k: 0.0 for k in betop.AXIS_TARGETS}}
        self.rebind_target = None
        self.rumble = None        # 物理手柄震动通道（可能为 None）

        self.status = tk.StringVar(value="设备就绪，点右上角「启动映射」")
        self.pad_items = {}      # 名字 -> [canvas item ids]
        self.pad_text = {}       # 名字 -> text item id
        self._build()
        # 第一次打开自动弹一次教程，之后不再打扰
        if not self.km.get("guide_seen"):
            self.km["guide_seen"] = True
            try:
                betop.save_keymap(self.km)
            except Exception:
                pass
            root.after(700, self.open_guide)
        # 启动时后台静默查一次更新，结果只显示在左下角，不弹窗
        root.after(1200, self.auto_check_update)
        # 托盘 + 震动闹钟（闹钟即使不开映射也能到点震）
        self.tray = None
        self._tray_hid = False
        self.alarm = alarm.AlarmClock(self.km,
                                      state_getter=lambda: self.state)
        self.alarm.start()
        root.after(600, self._init_tray)
        root.protocol("WM_DELETE_WINDOW", self.on_close_request)

    # ------------------------------------------------------------ 托盘
    def _init_tray(self):
        """起托盘图标；失败（比如远程桌面没外壳）也不影响主程序"""
        try:
            t = tray.TrayIcon(tip="北通手柄映射器")
            if t.start(self._tray_items()):
                self.tray = t
                t.set_tip("北通手柄映射器 — 双击打开，右键看菜单")
            else:
                t.stop()
        except Exception:
            self.tray = None

    def _tray_items(self):
        """菜单项：(id, 文字, 打勾, 可用)"""
        run = bool(self.running)
        return [
            (T_SHOW, "显示主界面"),
            (T_TOGGLE, "停止映射") if run else (T_TOGGLE, "启动映射"),
            None,
            (T_ALARM, "⏰ 震动闹钟",
             bool(self.km.get("alarm_on")), True),
            (T_TEST, "试震一下", False, True),
            (T_UPDATE, "🔄 检查更新"),
            None,
            (T_EXIT, "退出程序"),
        ]

    def _refresh_tray(self):
        if self.tray:
            try:
                self.tray.set_items(self._tray_items())
            except Exception:
                pass

    def _drain_tray(self):
        """托盘动作在子线程产生的，这里（主线程）统一处理"""
        if not self.tray:
            return
        for cmd in self.tray.poll():
            try:
                if cmd in ("show", T_SHOW):
                    self.show_window()
                elif cmd == T_TOGGLE:
                    self.toggle()
                elif cmd == T_ALARM:
                    self.open_alarm()
                elif cmd == T_TEST:
                    self.test_rumble()
                elif cmd == T_UPDATE:
                    self.open_update()
                elif cmd == T_EXIT:
                    self.quit_app()
            except Exception:
                pass
        self._refresh_tray()

    def show_window(self):
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass

    def hide_to_tray(self):
        """关窗口只藏起来，程序继续在托盘里跑"""
        try:
            self.root.withdraw()
            self._tray_hid = True
            if self.tray:
                self.tray.notify("还在后台跑着，双击图标打开；"
                                 "想彻底退出就右键 → 退出程序",
                                 "北通手柄映射器")
        except Exception:
            pass

    def on_close_request(self):
        """点 X：有托盘就藏起来，没托盘就直接退"""
        if self.tray:
            self.hide_to_tray()
        else:
            self.quit_app()

    def quit_app(self):
        """真正退出：停映射、停震动、撤托盘"""
        try:
            self.fun_stop.set()          # 娱乐模式先停
            th = getattr(self, "_fun_thread", None)
            if th is not None and th.is_alive():
                th.join(timeout=2.0)
            if self.running:
                self.stop.set()
                self.running = False
        except Exception:
            pass
        try:
            self.alarm.cancel_ring()
            self.alarm.shutdown()
        except Exception:
            pass
        time.sleep(0.25)
        try:
            if self.rumble is not None:
                self.rumble.stop()
                self.rumble.stop_all()
                self.rumble.close()
                self.rumble = None
        except Exception:
            pass
        try:
            if self.tray:
                self.tray.stop()
                self.tray = None
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    # ------------------------------------------------------------ 闹钟
    def open_alarm(self):
        try:
            alarm.AlarmDialog(self.root, self)
        except Exception as e:
            messagebox.showerror("震动闹钟", str(e), parent=self.root)

    def _drain_alarm(self):
        for ev in self.alarm.poll():
            kind = ev[0]
            try:
                if kind == "fired":
                    if self.tray:
                        self.tray.notify("时间到了！按手柄任意键停止震动",
                                         "⏰ 震动闹钟")
                    self.status.set("⏰ 闹钟响了，按手柄任意键停")
                    self._refresh_status()
                elif kind == "stopped":
                    if self.tray:
                        self.tray.notify("闹钟已停（%s）" % ev[1], "⏰ 震动闹钟")
                    self.status.set("闹钟已停")
                    self._refresh_status()
                elif kind == "error":
                    if self.tray:
                        self.tray.notify(ev[1], "⏰ 震动闹钟",
                                         tray.NIIF_WARNING)
                    self.rumble_lbl.config(text=ev[1])
                elif kind == "off":
                    self.status.set(ev[1])
                    self._refresh_status()
            except Exception:
                pass

    # ------------------------------------------------------------ 更新
    def open_update(self):
        """弹出检查更新窗口"""
        try:
            updater.UpdateDialog(self.root)
        except Exception as e:
            messagebox.showerror("检查更新", str(e), parent=self.root)

    def auto_check_update(self):
        """后台查一次，只更新左下角那行字"""
        try:
            updater.check_async_tk(self.root, self.on_update_result)
        except Exception:
            pass

    def on_update_result(self, info, err, cmp_):
        """主线程回调（check_async_tk 保证），直接改左下角"""
        try:
            if err:
                txt, clr = "检查更新失败", "#c9a227"
            elif cmp_ > 0:
                txt, clr = "🎉 有新版本 v" + info["version"], C_ACC
            elif cmp_ < 0:
                txt, clr = "🛠 开发版 v" + updater.APP_VERSION, "#c2c6cd"
            else:
                txt, clr = "✅ 已是最新版", C_OK
            self.foot_upd.config(text=txt, fg=clr)
        except Exception:
            pass

    # ------------------------------------------------------------ 界面
    def _build(self):
        # ================= 左侧导航 =================
        sb = tk.Frame(self.root, bg=C_CARD, width=180)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)
        tk.Frame(sb, bg=C_LINE, height=0).pack()

        logo = tk.Frame(sb, bg=C_CARD)
        logo.pack(fill="x", padx=18, pady=(20, 4))
        ic = tk.Canvas(logo, width=32, height=32, bg=C_CARD, highlightthickness=0)
        ic.pack(side="left")
        round_rect(ic, 1, 6, 31, 28, 9, fill=C_RED, outline="")
        ic.create_text(16, 17, text="🎮", font=("Segoe UI Emoji", 12))
        tk.Label(logo, text="北通游戏厅", font=(FONT, 12, "bold"),
                 fg=C_TEXT, bg=C_CARD).pack(side="left", padx=6)
        tk.Label(sb, text="手柄映射工具版", font=(FONT, 8),
                 fg=C_SUB, bg=C_CARD).pack(padx=20, anchor="w")

        def nav_header(t):
            tk.Label(sb, text=t, font=(FONT, 8), fg=C_SUB, bg=C_CARD
                     ).pack(fill="x", padx=20, pady=(16, 3))

        def nav_item(t, cmd=None, active=False):
            f = tk.Label(sb, text="  " + t, font=(FONT, 10, "bold" if active else "normal"),
                         fg=(C_RED if active else "#4a4e57"),
                         bg=(C_ACC_LT if active else C_CARD),
                         anchor="w", padx=6, pady=7, cursor="hand2")
            f.pack(fill="x", padx=12, pady=1)
            if cmd:
                f.bind("<Button-1>", lambda e: cmd())
            return f

        nav_header("我的手柄")
        nav_item("📖 新手教程", self.open_guide)
        nav_item("🖥 设备检测", self.show_device)
        nav_header("工具箱")
        nav_item("🕹 键位映射", None, active=True)
        nav_item("🔑 键位识别向导", self.open_wizard)
        nav_item("🧪 震动实验室", self.open_lab)
        nav_item("⏰ 震动闹钟", self.open_alarm)
        nav_item("📖 使用说明", self.show_help)
        nav_item("💾 保存键位", self.save)
        nav_header("关于")
        nav_item("🔄 检查更新", self.open_update)

        ft = tk.Frame(sb, bg=C_CARD)
        ft.pack(side="bottom", pady=12)
        tk.Label(ft, text="BTP-V1T 先游定制版\nv" + updater.APP_VERSION,
                 font=(FONT, 8), fg="#c2c6cd", bg=C_CARD,
                 justify="center").pack()
        self.foot_upd = tk.Label(ft, text="检查更新…", font=(FONT, 8),
                                 fg="#c2c6cd", bg=C_CARD, cursor="hand2")
        self.foot_upd.pack(pady=(5, 0))
        self.foot_upd.bind("<Button-1>", lambda e: self.open_update())

        # ================= 主区 =================
        main = tk.Frame(self.root, bg=C_BG)
        main.pack(side="left", fill="both", expand=True)

        top = tk.Frame(main, bg=C_CARD)
        top.pack(fill="x")
        inner = tk.Frame(top, bg=C_CARD)
        inner.pack(fill="x", padx=22, pady=11)
        tk.Label(inner, text="键位映射", font=(FONT, 15, "bold"),
                 fg=C_TEXT, bg=C_CARD).pack(side="left")
        self.chip = tk.Label(inner, text="● " + self.status.get(), font=(FONT, 9),
                             fg=C_SUB, bg="#f4f5f8", padx=10, pady=4)
        self.chip.pack(side="left", padx=14)
        self.btn_run = tk.Button(inner, text="启动映射", font=(FONT, 10, "bold"),
                                 fg="white", bg=C_RED, activebackground=C_RED_DK,
                                 activeforeground="white", relief="flat",
                                 padx=22, pady=6, cursor="hand2",
                                 command=self.toggle)
        self.btn_run.pack(side="right")

        # ---------- 中央：手柄图 + 右侧状态 ----------
        row = tk.Frame(main, bg=C_BG)
        row.pack(fill="x", padx=18, pady=14)

        lc = tk.Frame(row, bg=C_CARD, highlightthickness=1, highlightbackground=C_LINE)
        lc.pack(side="left")
        hdr = tk.Frame(lc, bg=C_CARD)
        hdr.pack(fill="x", padx=16, pady=(10, 2))
        tk.Label(hdr, text="实时手柄状态", font=(FONT, 11, "bold"), fg=C_TEXT,
                 bg=C_CARD).pack(side="left")
        tk.Label(hdr, text="按下会亮绿 · 点任意键可重新绑定", font=(FONT, 8),
                 fg=C_SUB, bg=C_CARD).pack(side="left", padx=8)
        self.canvas = tk.Canvas(lc, width=560, height=370, bg=C_CARD,
                                highlightthickness=0)
        self.canvas.pack(padx=8, pady=(2, 10))
        self.pad_view = PadView(self.canvas)
        self.pad_view.bind_click(self.rebind)

        rc = tk.Frame(row, bg=C_CARD, highlightthickness=1, highlightbackground=C_LINE)
        rc.pack(side="left", fill="both", padx=12, ipadx=8)
        tk.Label(rc, text="设备", font=(FONT, 11, "bold"), fg=C_TEXT,
                 bg=C_CARD).pack(anchor="w", padx=14, pady=(10, 4))
        self.dev_lbl = tk.Label(rc, text="北通 BTP-V1T\n先游定制版", font=(FONT, 9),
                                fg=C_TEXT, bg=C_CARD, justify="left")
        self.dev_lbl.pack(anchor="w", padx=14)
        self.mode_lbl = tk.Label(rc, text="解码：未连接", font=(FONT, 8), fg=C_SUB,
                                 bg=C_CARD)
        self.mode_lbl.pack(anchor="w", padx=14, pady=(2, 8))
        tk.Frame(rc, bg=C_LINE, height=1).pack(fill="x", padx=12)
        tk.Label(rc, text="改键（先启动映射）", font=(FONT, 9, "bold"), fg=C_TEXT,
                 bg=C_CARD).pack(anchor="w", padx=14, pady=(8, 4))
        chips = tk.Frame(rc, bg=C_CARD)
        chips.pack(padx=12, fill="x")
        for i, name in enumerate(BTN_ORDER):
            cell = tk.Frame(chips, bg="#f4f5f8", highlightthickness=1,
                            highlightbackground=C_LINE)
            cell.grid(row=i // 2, column=i % 2, padx=3, pady=3, sticky="ew")
            tk.Label(cell, text=BTN_CN[name], font=("Consolas", 9, "bold"),
                     fg="#5a5e66", bg="#f4f5f8", width=5).pack(side="left")
            lb = tk.Label(cell, text="改", font=(FONT, 8), fg=C_RED, bg="#f4f5f8",
                          cursor="hand2", padx=4)
            lb.pack(side="left")
            lb.bind("<Button-1>", lambda e, n=name: self.rebind(n))
        chips.columnconfigure(0, weight=1)
        chips.columnconfigure(1, weight=1)

        # ---------- 右侧：震动 ----------
        tk.Frame(rc, bg=C_LINE, height=1).pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(rc, text="震动", font=(FONT, 9, "bold"), fg=C_TEXT,
                 bg=C_CARD).pack(anchor="w", padx=14, pady=(8, 2))
        self.rumble_on = tk.BooleanVar(value=bool(self.km.get("rumble", True)))
        tk.Checkbutton(rc, text="把游戏的震动转到手柄上", variable=self.rumble_on,
                       font=(FONT, 9), fg=C_TEXT, bg=C_CARD,
                       activebackground=C_CARD, selectcolor="#eaf5ea",
                       command=self.on_rumble_cfg).pack(anchor="w", padx=12)
        fr = tk.Frame(rc, bg=C_CARD)
        fr.pack(fill="x", padx=14, pady=(4, 0))
        tk.Label(fr, text="命令格式", font=(FONT, 8), fg=C_SUB,
                 bg=C_CARD).pack(side="left")
        names = [f[0] for f in betop.RUMBLE_FORMATS]
        self.rumble_fmt = tk.StringVar(value=names[self.km.get("rumble_fmt", 0)])
        om = tk.OptionMenu(fr, self.rumble_fmt, *names)
        om.config(font=(FONT, 8), bg="#f4f5f8", relief="flat",
                  highlightthickness=0, width=16)
        om["menu"].config(font=(FONT, 8))
        om.pack(side="left", padx=4)
        self.rumble_fmt.trace_add("write", lambda *_: self.on_rumble_cfg())
        # 震动强度滑块（转发和娱乐模式都吃这个系数）
        gr = tk.Frame(rc, bg=C_CARD)
        gr.pack(fill="x", padx=14, pady=(2, 0))
        tk.Label(gr, text="强度", font=(FONT, 8), fg=C_SUB,
                 bg=C_CARD).pack(side="left")
        tk.Label(gr, text="(>100%放大)", font=(FONT, 7), fg="#a0a4ad",
                 bg=C_CARD).pack(side="left")
        self.rumble_gain = tk.DoubleVar(
            value=float(self.km.get("rumble_gain", 1.0)))
        ttk.Scale(gr, from_=0.05, to=3.0, variable=self.rumble_gain,
                  length=118, command=lambda _v: self.on_gain()).pack(
            side="left", padx=4)
        self.gain_lbl = tk.Label(gr, text=f"{int(self.rumble_gain.get() * 100)}%",
                                 font=("Consolas", 8), fg=C_TEXT, bg=C_CARD, width=4)
        self.gain_lbl.pack(side="left")
        tb = tk.Frame(rc, bg=C_CARD)
        tb.pack(fill="x", padx=14, pady=(6, 12))
        tk.Button(tb, text="试震一下", font=(FONT, 9), fg="white", bg=C_ACC,
                  activebackground=C_ACC_DK, activeforeground="white",
                  relief="flat", padx=10, pady=4, cursor="hand2",
                  command=self.test_rumble).pack(side="left")
        tk.Button(tb, text="停止震动", font=(FONT, 9), fg="#c0392b", bg="#fdecea",
                  relief="flat", padx=10, pady=4, cursor="hand2",
                  command=self.stop_rumble).pack(side="left", padx=6)
        tk.Button(tb, text="自动识别", font=(FONT, 9), fg=C_TEXT, bg="#f0f1f4",
                  relief="flat", padx=10, pady=4, cursor="hand2",
                  command=self.auto_scan).pack(side="left", padx=6)
        self.rumble_lbl = tk.Label(tb, text="", font=(FONT, 8), fg=C_SUB,
                                   bg=C_CARD, wraplength=150, justify="left")
        self.rumble_lbl.pack(side="left", padx=8)
        # 诊断：游戏到底有没有把震动发过来
        self.dbg_lbl = tk.Label(rc, text="还没收到游戏的震动指令",
                                font=("Consolas", 8), fg="#a0a4ad",
                                bg=C_CARD, justify="left")
        self.dbg_lbl.pack(anchor="w", padx=14, pady=(0, 4))
        # 娱乐模式：手柄无限震动，再点一次停
        self.fun_stop = threading.Event()
        self._fun_thread = None
        self._fun_rm = None
        self._fun_own = False
        tb2 = tk.Frame(rc, bg=C_CARD)
        tb2.pack(fill="x", padx=14, pady=(6, 12))
        self.btn_fun = tk.Button(tb2, text="娱乐模式 · 无限震动",
                                 font=(FONT, 9, "bold"), fg="white", bg="#8e44ad",
                                 activebackground="#6c3483",
                                 activeforeground="white", relief="flat",
                                 padx=12, pady=4, cursor="hand2",
                                 command=self.toggle_fun)
        self.btn_fun.pack(side="left")
        tk.Label(tb2, text="再点一次按钮停止", font=(FONT, 8), fg=C_SUB,
                 bg=C_CARD).pack(side="left", padx=6)
        cl = tk.Frame(rc, bg=C_CARD)
        cl.pack(fill="x", padx=14, pady=(0, 10))
        self.custom_lbl = tk.Label(cl, text=self._custom_text(),
                                   font=(FONT, 8), fg=C_SUB, bg=C_CARD,
                                   justify="left", wraplength=210)
        self.custom_lbl.pack(side="left")
        self.btn_clr_custom = tk.Button(
            cl, text="🗑", font=(FONT, 8), relief="flat", bg="#fdecea",
            fg="#c0392b", padx=5, pady=0, cursor="hand2",
            command=lambda: self.clear_custom(True))
        self.btn_clr_custom.pack(side="right")

        # ---------- 底部：摇杆 / 扳机 ----------
        bc = tk.Frame(main, bg=C_CARD, highlightthickness=1, highlightbackground=C_LINE)
        bc.pack(fill="x", padx=18, pady=(0, 14))
        head = tk.Frame(bc, bg=C_CARD)
        head.pack(fill="x", padx=16, pady=(10, 4))
        tk.Label(head, text="摇杆 / 扳机", font=(FONT, 11, "bold"), fg=C_TEXT,
                 bg=C_CARD).pack(side="left")
        tk.Label(head, text="摇杆死区", font=(FONT, 9), fg=C_TEXT,
                 bg=C_CARD).pack(side="right")
        self.dz = tk.DoubleVar(value=self.km.get("deadzone", 0.12))
        ttk.Scale(head, from_=0, to=0.5, variable=self.dz, length=110,
                  command=lambda v: self.on_dz()).pack(side="right")
        self.dz_lbl = tk.Label(head, text=f"{self.dz.get():.2f}",
                               font=("Consolas", 9), fg=C_TEXT, bg=C_CARD, width=4)
        self.dz_lbl.pack(side="right")
        bars = tk.Frame(bc, bg=C_CARD)
        bars.pack(fill="x", padx=16, pady=(0, 12))
        self.bars = {}
        for i, k in enumerate(betop.AXIS_TARGETS):
            col = tk.Frame(bars, bg=C_CARD)
            col.grid(row=0, column=i, padx=6)
            tk.Label(col, text=k, font=("Consolas", 9, "bold"), fg=C_SUB,
                     bg=C_CARD).pack()
            cv = tk.Canvas(col, width=104, height=12, bg="#f4f5f8", highlightthickness=0)
            cv.pack(pady=2)
            self.bars[k] = cv
            fz = tk.Label(col, text="反向", font=(FONT, 8), fg=C_RED, bg=C_CARD,
                          cursor="hand2")
            fz.pack()
            fz.bind("<Button-1>", lambda e, kk=k: self.flip(kk))
            if k in ("LX", "LY", "RX", "RY"):
                cz = tk.Label(col, text="中位", font=(FONT, 8), fg=C_RED, bg=C_CARD,
                              cursor="hand2")
                cz.pack()
                cz.bind("<Button-1>", lambda e, kk=k: self.calib(kk))

        self.root.after(70, self.pump)

    # ------------------------------------------------------------ 控制
    def toggle(self):
        if self.running:
            self.stop.set()
            self.running = False
            self.fun_stop.set()          # 娱乐模式一起停
            self._close_rumble()
            self.btn_run.config(text="启动映射", bg=C_RED)
            self.status.set("已停止")
            self._refresh_status()
            return
        try:
            self.dev = betop.open_device()
            self.pad = betop.VirtualPad(rumble_callback=self.on_rumble)
        except Exception as e:
            messagebox.showerror("启动失败", f"{e}\n\n确认 ViGEmBus 驱动装好了没")
            return
        # 震动通道单独开（游戏接口没有输出报告），开不了也只是没震，不影响映射
        try:
            self.rumble = betop.Rumble(fmt=self._fmt_index(),
                                       enabled=bool(self.rumble_on.get()),
                                       custom=self.km.get("rumble_custom")).open()
            self.rumble_lbl.config(text="震动通道已开")
        except Exception as e:
            self.rumble = None
            self.rumble_lbl.config(text=f"震动通道开不了：{e}")
            self.dbg_lbl.config(text="震动通道开不了，游戏震动转不出去",
                                fg="#c0392b")
        self.stop.clear()
        self.running = True
        self.btn_run.config(text="停止映射", bg="#5a5e66")
        be = "HidP 精确解码" if self.dev.use_hidp else "字节兜底"
        self.status.set(f"运行中（{be}）— 去开基岩版 MC")
        self.mode_lbl.config(text="解码：" + be)
        self._refresh_status()
        threading.Thread(target=self.loop, daemon=True).start()

    # ------------------------------------------------------------ 震动
    def _fmt_index(self):
        cur = self.rumble_fmt.get()
        for i, (name, _ch, _fn) in enumerate(betop.RUMBLE_FORMATS):
            if name == cur:
                return i
        return 0

    def on_rumble_cfg(self):
        self.km["rumble"] = bool(self.rumble_on.get())
        self.km["rumble_fmt"] = self._fmt_index()
        if self.rumble is not None:
            self.rumble.enabled = self.km["rumble"]
            self.rumble.fmt = self.km["rumble_fmt"]

    def on_gain(self):
        g = max(0.05, min(3.0, self.rumble_gain.get()))
        self.km["rumble_gain"] = round(g, 2)
        self.gain_lbl.config(text=f"{int(g * 100)}%")

    def _gain(self):
        return max(0.05, min(3.0, float(self.km.get("rumble_gain", 1.0))))

    def on_rumble(self, big, small):
        """ViGEm 告诉我们游戏想让手柄震多大 -> 乘上强度滑块 -> 转发"""
        if self.rumble is not None:
            g = self._gain()
            self.rumble.set(min(255, int(big * g)), min(255, int(small * g)))
        self._dbg = (int(big), int(small), self.rumble is not None)
        now = time.time()
        if now - getattr(self, "_dbg_t", 0) > 0.12:   # 别把 UI 队列刷爆
            self._dbg_t = now
            self.root.after(0, self._flush_dbg)

    def _flush_dbg(self):
        b, s, ok = getattr(self, "_dbg", (0, 0, False))
        tail = "" if ok else "  （震动通道没开，转不出去）"
        self.dbg_lbl.config(text=f"游戏震动 → 大马达 {b:3d} · 小马达 {s:3d}{tail}",
                            fg=("#0f9d58" if ok else "#c0392b"))

    def _custom_text(self):
        """现在到底在用哪条震动命令"""
        c = self.km.get("rumble_custom")
        if not c:
            return "当前用「命令格式」下拉里选的那条"
        fixed = " ".join(f"b[{o}]=0x{v:02X}" for o, v in c.get("fixed", []))
        motor = "、".join(f"b[{o}]" for o in c.get("motor", []))
        return f"已用实验室冠军命令：{fixed}；马达字节 {motor}"

    def open_guide(self):
        """图形化新手教程：六步走一遍"""
        try:
            guide.Guide(self)
        except Exception as e:
            messagebox.showerror("教程打不开", str(e), parent=self.root)

    def open_lab(self):
        """震动实验室：扫命令 + 两两对决选出最猛的那条"""
        try:
            lab.Lab(self.root, self.km, on_apply=self.apply_custom,
                    on_clear=lambda: self.clear_custom(False))
        except Exception as e:
            self.rumble_lbl.config(text=f"实验室开不了：{e}")

    def clear_custom(self, confirm=True):
        """丢掉实验室选出来的冠军命令，回到「命令格式」下拉里选的那条"""
        if confirm and not self.km.get("rumble_custom"):
            messagebox.showinfo("清除", "现在没有冠军命令，用的就是下拉里那条",
                                parent=self.root)
            return
        if confirm and not messagebox.askyesno(
                "清除冠军命令",
                "丢掉实验室选出来的冠军命令，改用「命令格式」下拉里选的那条？",
                parent=self.root):
            return
        self.km["rumble_custom"] = None
        if self.rumble is not None:
            self.rumble.custom = None
            self.rumble._last = None
        self.custom_lbl.config(text=self._custom_text())
        self.rumble_lbl.config(text="已回到下拉里的命令格式")

    def apply_custom(self, spec, title):
        self.km["rumble_custom"] = spec
        if self.rumble is not None:
            self.rumble.custom = spec
            self.rumble._last = None
        self.custom_lbl.config(text=self._custom_text())
        self.rumble_lbl.config(text=f"已换成冠军 {title}")

    def _close_rumble(self):
        if self.rumble is not None:
            try:
                self.rumble.stop()
                self.rumble.stop_all()
                self.rumble.close()
            except Exception:
                pass
            self.rumble = None

    def stop_rumble(self):
        """急停：不管当前在震什么都立刻清零"""
        self.fun_stop.set()          # 娱乐模式也一起停
        rm = self.rumble
        own = False
        if rm is None or rm.dev is None:
            try:
                rm = betop.Rumble(custom=self.km.get("rumble_custom")).open()
                own = True
            except Exception as e:
                self.rumble_lbl.config(text=f"打不开：{e}")
                return
        try:
            rm.stop()
            rm.stop_all()
            if own:
                rm.close()
        except Exception:
            pass
        self.rumble_lbl.config(text="已停止震动")

    def test_rumble(self):
        """不启动映射也能量：单独开私有通道震三下"""
        try:
            r = betop.Rumble(fmt=self._fmt_index(),
                          custom=self.km.get("rumble_custom")).open()
        except Exception as e:
            self.rumble_lbl.config(text=f"打不开：{e}")
            return
        self.rumble_lbl.config(text="连震三下…")

        def go():
            try:
                g = self._gain()
                # 先单独大马达、再单独小马达、最后两个一起，好分辨哪个在响
                seq = [(255, 0), (0, 0), (0, 255), (0, 0), (255, 255), (0, 0)]
                for a, b in seq:
                    r.set(min(255, int(a * g)), min(255, int(b * g)))
                    time.sleep(0.7)
            finally:
                r.close()
        threading.Thread(target=go, daemon=True).start()

    def toggle_fun(self):
        """娱乐模式：手柄无限震动，再点一次（或点停止震动）停"""
        if self._fun_thread is not None and self._fun_thread.is_alive():
            self.fun_stop.set()
            return
        rm, own = self.rumble, False
        if rm is None or rm.dev is None:
            try:
                rm = betop.Rumble(fmt=self._fmt_index(),
                           custom=self.km.get("rumble_custom")).open()
                own = True
            except Exception as e:
                self.rumble_lbl.config(text=f"打不开：{e}")
                return
        self._fun_rm, self._fun_own = rm, own
        self.fun_stop.clear()
        self.btn_fun.config(text="停止无限震动", bg=C_RED_DK)
        self.rumble_lbl.config(text="娱乐模式震着呢…")
        self._fun_thread = threading.Thread(target=self._fun_loop, daemon=True)
        self._fun_thread.start()

    def _fun_loop(self):
        rm = self._fun_rm
        own = self._fun_own
        try:
            strength = max(1, min(255, int(255 * self._gain())))
            while not self.fun_stop.is_set():
                try:
                    # 固件收到命令不会自动停，但持续续发最稳；强度跟滑块走
                    rm.play_once(rm.fmt, strength)
                except Exception:
                    pass
                time.sleep(0.5)
        finally:
            try:
                rm.stop()
                rm.stop_all()
            except Exception:
                pass
            if own:
                try:
                    rm.close()
                except Exception:
                    pass
            self._fun_rm = None
            self._fun_own = False
            try:
                self.root.after(0, lambda: self.btn_fun.config(
                    text="娱乐模式 · 无限震动", bg="#8e44ad"))
                self.rumble_lbl.config(text="已停止娱乐模式")
            except Exception:
                pass

    def auto_scan(self):
        """挨个发候选命令把手感试出来：感觉到震就点「这次震了」"""
        if getattr(self, "_scanning", False):
            return
        rm, own = self.rumble, False
        if rm is None or rm.dev is None:
            try:
                rm = betop.Rumble(custom=self.km.get("rumble_custom")).open()
                own = True
            except Exception as e:
                messagebox.showerror("扫不了", f"{e}")
                return
        fmts = betop.RUMBLE_FORMATS
        total = len(fmts)
        self._scanning = True
        st = {"i": 0, "tick": None, "done": False}

        win = tk.Toplevel(self.root)
        win.title("自动识别震动命令")
        win.configure(bg=C_CARD)
        win.geometry("440x230")
        win.resizable(False, False)
        win.transient(self.root)
        tk.Label(win, text="程序会挨个发候选命令，手柄一直震着", font=(FONT, 11, "bold"),
                 fg=C_TEXT, bg=C_CARD).pack(pady=(16, 2))
        tk.Label(win, text="感觉到震动就点「这次震了！」，没感觉点「下一个」",
                 font=(FONT, 9), fg=C_SUB, bg=C_CARD).pack()
        v_prog = tk.StringVar(value="")
        tk.Label(win, textvariable=v_prog, font=("Consolas", 9), fg=C_ACC,
                 bg=C_CARD).pack(pady=(10, 0))
        v_name = tk.StringVar(value="")
        tk.Label(win, textvariable=v_name, font=("Consolas", 11), fg=C_TEXT,
                 bg="#f4f5f8", padx=8, pady=6, width=42).pack(pady=4)

        def cleanup(keep=None):
            st["done"] = True
            if st["tick"]:
                try:
                    self.root.after_cancel(st["tick"])
                except Exception:
                    pass
            st["tick"] = None
            rm.stop()
            rm.stop_all()          # 有手柄收到某些命令后会一直震，必须全量清零
            self._scanning = False
            if keep is not None:
                self.km["rumble_fmt"] = keep
                self.rumble_fmt.set(fmts[keep][0])
                self.on_rumble_cfg()
                self.rumble_lbl.config(text=f"已选第 {keep + 1} 个，记得保存")
            elif own:
                try:
                    rm.close()
                except Exception:
                    pass
            try:
                win.destroy()
            except Exception:
                pass

        def next_cand():
            if st["done"]:
                return
            st["i"] += 1
            if st["i"] >= total:
                cleanup()
                messagebox.showinfo("扫完了", "全部候选都试过，没找到能震的。\n"
                                              "这把定制版可能压根不支持在 BFM 模式下收震动命令。")
                return
            play()

        def play():
            if st["done"]:
                return
            rm.stop_all()          # 换候选前先彻底清干净，避免上一个还在震
            rm.play_once(st["i"], 255)
            v_prog.set(f"第 {st['i'] + 1} / {total} 个")
            v_name.set(fmts[st["i"]][0])
            st["tick"] = self.root.after(900, keepalive)

        def keepalive():
            """命令可能被设备超时清掉，一直续发，等你慢慢感觉"""
            if st["done"]:
                return
            try:
                rm.play_once(st["i"], 255)
            except Exception:
                pass
            st["tick"] = self.root.after(900, keepalive)

        bt = tk.Frame(win, bg=C_CARD)
        bt.pack(pady=12)
        tk.Button(bt, text="这次震了！用这个", font=(FONT, 10, "bold"), fg="white",
                  bg=C_ACC, activebackground=C_ACC_DK, activeforeground="white",
                  relief="flat", padx=14, pady=6, cursor="hand2",
                  command=lambda: cleanup(st["i"])).pack(side="left", padx=6)
        tk.Button(bt, text="下一个", font=(FONT, 10), fg=C_TEXT, bg="#f0f1f4",
                  relief="flat", padx=14, pady=6, cursor="hand2",
                  command=next_cand).pack(side="left", padx=6)
        tk.Button(bt, text="放弃", font=(FONT, 10), fg=C_SUB, bg="#f0f1f4",
                  relief="flat", padx=14, pady=6, cursor="hand2",
                  command=lambda: cleanup()).pack(side="left", padx=6)
        win.protocol("WM_DELETE_WINDOW", lambda: cleanup())
        play()

    def _refresh_status(self):
        self.chip.config(text="● " + self.status.get(),
                         fg=(C_OK if self.running else C_SUB))

    def loop(self):
        km = self.km
        dz = km.get("deadzone", 0.12)
        tdz = km.get("trigger_deadzone", 0.03)
        while not self.stop.is_set():
            try:
                r = self.dev.read()
            except Exception as e:
                self.status.set(f"读取失败：{e}")
                self._refresh_status()
                break
            if not r:
                time.sleep(0.002)
                continue
            buttons, axes = betop.parse_report(self.dev, list(r), km)
            for k in ("LT", "RT"):
                axes[k] = betop.apply_deadzone(axes[k], tdz)
            for k in ("LX", "LY", "RX", "RY"):
                axes[k] = betop.apply_deadzone(axes[k], dz)
            self.state["buttons"] = buttons
            self.state["axes"] = axes
            try:
                self.pad.update(buttons, axes)
            except Exception:
                pass
        try:
            if self.pad:
                self.pad.reset()
            if self.dev:
                self.dev.close()
        except Exception:
            pass
        self._close_rumble()

    # ------------------------------------------------------------ 实时刷新
    def pump(self):
        self._drain_tray()
        self._drain_alarm()
        if self.running:
            b = self.state.get("buttons", {})
            a = self.state.get("axes", {})
            self.pad_view.set_state(b, a)
            for k, bar in self.bars.items():
                self.draw_bar(bar, a.get(k, 0.0))
        self.root.after(70, self.pump)

    def draw_bar(self, cv, v):
        cv.delete("all")
        w = int(cv["width"]); h = int(cv["height"])
        mid = w // 2
        n = int(abs(v) * (mid - 2))
        color = C_RED if v < 0 else "#3a7bff"
        if v >= 0:
            cv.create_rectangle(mid, 2, mid + n, h - 2, fill=color, outline="")
        else:
            cv.create_rectangle(mid - n, 2, mid, h - 2, fill=color, outline="")

    # ------------------------------------------------------------ 改键
    def rebind(self, name):
        if not self.running:
            messagebox.showinfo("先启动", "先点右上角「启动映射」再改键")
            return
        self.rebind_target = name
        win = tk.Toplevel(self.root)
        win.title(f"绑定 {name}")
        win.geometry("400x140")
        win.transient(self.root)
        tk.Label(win, text=f"按住手柄上想当 {BTN_CN[name]} 用的键…",
                 font=(FONT, 11)).pack(pady=24)
        pb = ttk.Progressbar(win, mode="indeterminate", length=320)
        pb.pack()
        pb.start()
        self._rebind_win = win
        self.root.after(100, lambda: self.watch_rebind(name, win))

    def watch_rebind(self, name, win):
        if self.rebind_target is None:
            return
        try:
            r = self.dev.read()
        except Exception:
            r = None
        if r:
            pressed, ok = self.dev.decode(list(r))
            if pressed:
                u = sorted(pressed)[0]
                self.km["buttons"][name] = u
                self.rebind_target = None
                try:
                    win.destroy()
                except Exception:
                    pass
                self.status.set(f"{name} 已绑定到按钮 {u}（记得保存）")
                self._refresh_status()
                return
        self.root.after(60, lambda: self.watch_rebind(name, win))

    def flip(self, key):
        spec = self.km["axes"].get(key)
        if not spec:
            return
        spec["invert"] = not spec.get("invert", False)
        self.status.set(f"{key} 已{'反向' if spec['invert'] else '恢复正常'}")
        self._refresh_status()

    def calib(self, key):
        """把当前摇杆位置记为中位"""
        spec = self.km["axes"].get(key)
        if not spec:
            return
        raw = None
        try:
            r = self.dev.read()
            if r:
                raw = self.dev.usage_value(list(r), spec.get("up", 1), spec.get("usage"))
        except Exception:
            pass
        if raw is None:
            messagebox.showinfo("校准", "没读到数据，先启动映射、摇杆回中后再试")
            return
        spec["center"] = raw
        self.status.set(f"{key} 中位已设为 {raw}")
        self._refresh_status()

    def on_dz(self):
        self.km["deadzone"] = round(self.dz.get(), 3)
        self.dz_lbl.config(text=f"{self.dz.get():.2f}")

    def save(self):
        self.km["deadzone"] = round(self.dz.get(), 3)
        betop.save_keymap(self.km)
        self.status.set("键位已保存")
        self._refresh_status()

    def show_device(self):
        try:
            dev = betop.open_device()
            mode = "HidP 精确解码" if dev.use_hidp else "字节兜底"
            dev.close()
            info = (f"手柄已连接：北通 BTP-V1T（先游定制版）\n"
                    f"VID 20BC / PID 503C，解码方式：{mode}\n"
                    f"映射状态：{'运行中' if self.running else '未启动'}")
        except Exception as e:
            info = f"没找到手柄：{e}\n\n检查 USB 线插好没、手柄开没开机"
        messagebox.showinfo("设备状态", info)

    def show_help(self):
        txt = os.path.join(HERE, "使用说明.txt")
        if os.path.exists(txt):
            os.startfile(txt)
        else:
            messagebox.showinfo("使用说明",
                                "1. 点「启动映射」→ 系统多出一个 Xbox 360 手柄\n"
                                "2. 开游戏就能玩（基岩版 MC 直接认）\n"
                                "3. 键位不对就用「键位识别向导」重新识别")

    def open_wizard(self):
        import subprocess
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        if getattr(sys, "frozen", False):
            exe = os.path.join(HERE, "BetopWizard.exe")
            if not os.path.exists(exe):
                messagebox.showinfo("向导", f"没找到 {exe}\n主程序本身能用的话，不用管这个向导")
                return
            subprocess.Popen([exe], creationflags=flags)
        else:
            subprocess.Popen([sys.executable, os.path.join(HERE, "wizard.py")],
                             creationflags=flags)
        messagebox.showinfo("向导", "已在新窗口打开识别向导，跟着提示按键即可")


def main():
    root = tk.Tk()
    app = App(root)
    # App.__init__ 里已经挂过了；这里再挂一次防止被覆盖。
    # 关窗口 = 藏到托盘（没托盘就直接退），真退走 app.quit_app()：
    # 停娱乐模式 / 停闹钟 / 马达归零 / 撤托盘，一样都不会漏
    root.protocol("WM_DELETE_WINDOW", app.on_close_request)
    root.mainloop()


if __name__ == "__main__":
    main()
