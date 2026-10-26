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
import hidhide
import hidraw
import lab
import alarm
import notify
import tray
import updater

HERE = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.abspath(__file__)))

BTN_ORDER = ["Y", "X", "B", "A", "LB", "RB", "BACK", "START", "LS", "RS",
             "GUIDE"]
BTN_CN = {"Y": "Y", "X": "X", "B": "B", "A": "A", "LB": "LB", "RB": "RB",
          "BACK": "BACK", "START": "START", "LS": "L3", "RS": "R3",
          "GUIDE": "LOGO"}
# 这把的 FN 键固件不上报（按了没数据），不进改键列表；
# LOGO 键的 usage 是 105（2026-10-25 更正，之前被误记成 FN/GUIDE=12）

# 托盘右键菜单 id
T_SHOW, T_TOGGLE, T_ALARM, T_TEST, T_UPDATE, T_EXIT = 1, 2, 3, 4, 5, 6
T_NOTIFY = 7

# 配色 / 手柄图统一放在 padui.py（识别向导 wizard.py 用的是同一套）
import padui
from padui import (C_BG, C_CARD, C_ACC, C_ACC_DK, C_ACC_LT, C_TEXT, C_SUB,
                   C_LINE, C_OK, C_PRESS, P_KNOB, FONT, FT, S, round_rect,
                   PadView, apply_icon)

C_RED = C_ACC          # 旧变量名兼容
C_RED_DK = C_ACC_DK

# ---- Win11 化（v1.0.28）：Mica 窗口 + 深色标题栏 + 圆角卡片 ----
import win11ui
C_BG = win11ui.HOLE          # 底色换成卡片之间的"缝隙色"（比原 C_BG 柔和）
C_LINE = "#e3e5ea"


class App:
    def __init__(self, root):
        self.root = root
        root.title("北通游戏厅 · 手柄映射器")
        # 可缩放：内容太少会挤成一团，给个下限；手柄图按比例跟着变（见 _pad_fit）
        root.resizable(True, True)
        root.minsize(S(940), S(620))
        _w0, _h0 = S(1080), S(860)
        root.geometry("%dx%d+%d+%d" % (_w0, _h0,
                                       (root.winfo_screenwidth() - _w0) // 2,
                                       (root.winfo_screenheight() - _h0) // 2))
        root.configure(bg=C_BG)
        apply_icon(root)
        win11ui.apply(root)          # Mica + 深色标题栏（老系统静默跳过）

        self.km = betop.load_keymap()
        self.dev = None
        self.pad = None
        self.running = False
        self.loop_th = None       # 读手柄的线程（切换屏蔽时要等它收尾）
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
        # 手机通知：局域网收一条 HTTP 请求就震一下（默认关，自己开）
        self.notify = notify.NotifyServer(self.km, on_hit=self._notify_buzz)
        root.after(500, self.apply_notify_cfg)
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
            (T_NOTIFY, "📱 手机通知",
             bool(self.km.get("notify_on")), True),
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
                elif cmd == T_NOTIFY:
                    self.open_notify()
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
        """把窗口拉回来（收在托盘/最小化都能恢复），并抢到最前面"""
        try:
            self._tray_hid = False
        except Exception:
            pass
        try:
            self.root.deiconify()          # 托盘(withdraw)/最小化都能恢复
            self.root.lift()
            # 别的窗口占着焦点时 lift 不够，临时置顶一下再取消
            self.root.attributes("-topmost", True)
            self.root.focus_force()
            self.root.after(200, lambda: self.root.attributes("-topmost", False))
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

    # ------------------------------------------------------------ 界面大小
    def _on_ui_scale_drag(self, _v=None):
        """拖动中：只更新百分比标签"""
        try:
            v = int(self.ui_scale.get())
            auto = int(round(padui.DPI / 96.0 * 100))
            self.ui_scale_lbl.config(
                text="%d%%%s" % (v, "（自动）" if v == auto else ""))
        except Exception:
            pass

    def _on_ui_scale_done(self, _e=None):
        """松手：存键位文件，提示重启生效"""
        try:
            v = int(self.ui_scale.get())
        except Exception:
            return
        auto = int(round(padui.DPI / 96.0 * 100))
        # 等于自动值就不落盘，跟着系统 DPI 走
        if v == auto:
            self.km.pop("ui_scale", None)
        else:
            self.km["ui_scale"] = round(v / (padui.DPI / 96.0) / 100.0, 4)
        try:
            betop.save_keymap(self.km)
        except Exception:
            pass
        try:
            self.ui_scale_hint.config(text="已保存，重启后生效")
        except Exception:
            pass

    def _restart_app(self):
        """重启自己：先存滑块值，干净退出（释放单实例互斥），再拉新进程。
        顺序不能反——先起新进程的话，它检查互斥时旧进程还活着，
        会被当成"已运行"直接激活旧窗口然后退出，两边都没了。"""
        self._on_ui_scale_done()
        try:
            import subprocess
            if getattr(sys, "frozen", False):
                new = [sys.executable]
            else:
                new = [sys.executable, os.path.abspath(__file__)]
        except Exception:
            return
        self.quit_app()               # 停震动/闹钟/托盘，释放互斥
        # 等旧窗口真的销毁（互斥随进程退出释放）再拉新的，最多等 2 秒
        for _ in range(20):
            try:
                if not self.root.winfo_exists():
                    break
            except Exception:
                break
            time.sleep(0.1)
        time.sleep(0.2)
        try:
            subprocess.Popen(new)
        except Exception:
            pass
        sys.exit(0)

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
        try:
            self.notify.stop()
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
        _release_instance_lock()      # 干净退出就顺手放锁，下个实例不用等判活
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

    # ------------------------------------------------------------ 手机通知
    def open_notify(self):
        try:
            notify.NotifyDialog(self.root, self)
        except Exception as e:
            messagebox.showerror("手机通知", str(e), parent=self.root)

    def open_hidhide(self):
        """HidHide 完整设置：总开关 / 黑名单 / 白名单（替代官方客户端）"""
        try:
            import hidui
            hidui.HidHideDialog(self.root, self)
        except Exception as e:
            messagebox.showerror("设备屏蔽", str(e), parent=self.root)

    def apply_notify_cfg(self):
        """开关 / 端口变了就重启监听"""
        ns = self.notify
        want = bool(self.km.get("notify_on"))
        if not want:
            ns.stop()
            return
        if ns.running() and getattr(ns, "_bound", None) != ns.port:
            ns.stop()
        if not ns.running():
            ok, err = ns.start()
            if not ok:
                self.status.set("手机通知起不来：%s" % err)
                self._refresh_status()

    def _notify_buzz(self, info=None):
        """真来通知了（在服务器线程里调）-> 开一路震动"""
        ns = self.notify

        def go():
            rm, own = self._get_rm()
            if rm is None:
                ns.q.put(("hit", {"app": "?", "title": "震动通道打不开",
                                  "why": "打不开", "ts": time.time()}))
                return
            prev = getattr(rm, "enabled", True)
            rm.enabled = True        # 就算「转游戏震动」关着，通知也要震
            try:
                alarm.play_ring(rm, ns.ring, ns.strength, ns.seconds)
            except Exception:
                pass
            finally:
                rm.enabled = prev
                if own:
                    try:
                        rm.close()
                    except Exception:
                        pass

        threading.Thread(target=go, daemon=True).start()

    def _get_rm(self):
        """拿一个能发震动的 Rumble：映射跑着就复用，否则自己开一路"""
        try:
            if self.rumble is not None and self.rumble.dev is not None:
                return self.rumble, False
        except Exception:
            pass
        try:
            return betop.Rumble(**self._rumble_kw()).open(), True
        except Exception:
            return None, False

    def _drain_notify(self):
        for kind, info in self.notify.poll():
            try:
                if kind == "hit":
                    src = info.get("app") or info.get("from") or "手机"
                    why = info.get("why", "")
                    if why == "已震动":
                        self.status.set("📱 %s 来消息，震了一下" % src)
                        self._refresh_status()
                elif kind == "on":
                    # 地址不放状态栏了（3 个 URL 会把顶部 chip 撑爆），
                    # 完整地址在「手机通知」窗口里，能看能复制
                    self.status.set("📱 手机通知已开启（地址见「手机通知」）")
                    self._refresh_status()
            except Exception:
                pass

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
        """弹出检查更新窗口（查完顺手把左下角那行字也刷新）"""
        try:
            updater.UpdateDialog(self.root, on_result=self.on_update_result)
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
                # 启动那一下可能是网络刚起来，1 分钟后再试一次
                self.root.after(60000, self.auto_check_update)
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
        sb = tk.Frame(self.root, bg=C_CARD, width=S(152))
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)
        tk.Frame(sb, bg=C_LINE, height=0).pack()

        logo = tk.Frame(sb, bg=C_CARD)
        logo.pack(fill="x", padx=S(18), pady=(S(20), S(4)))
        ic = tk.Canvas(logo, width=S(32), height=S(32), bg=C_CARD, highlightthickness=0)
        ic.pack(side="left")
        round_rect(ic, S(1), S(6), S(31), S(28), S(9), fill=C_RED, outline="")
        ic.create_text(S(16), S(17), text="🎮", font=FT(12, family="Segoe UI Emoji"))
        tk.Label(logo, text="北通游戏厅", font=FT(12, "bold"),
                 fg=C_TEXT, bg=C_CARD).pack(side="left", padx=S(6))
        tk.Label(sb, text="手柄映射工具版", font=FT(8),
                 fg=C_SUB, bg=C_CARD).pack(padx=S(20), anchor="w")

        def nav_header(t):
            tk.Label(sb, text=t, font=FT(8), fg=C_SUB, bg=C_CARD
                     ).pack(fill="x", padx=S(20), pady=(S(16), S(3)))

        def nav_item(t, cmd=None, active=False):
            f = tk.Label(sb, text="  " + t, font=FT(10, "bold" if active else "normal"),
                         fg=(C_RED if active else "#4a4e57"),
                         bg=(C_ACC_LT if active else C_CARD),
                         anchor="w", padx=S(6), pady=S(7), cursor="hand2")
            f.pack(fill="x", padx=S(12), pady=S(1))
            if cmd:
                f.bind("<Button-1>", lambda e: cmd())
            return f

        nav_header("我的手柄")
        nav_item("📖 新手教程", self.open_guide)
        nav_item("🖥 设备检测", self.show_device)
        nav_header("工具箱")
        nav_item("🕹 键位映射", None, active=True)
        nav_item("🛡 设备屏蔽（HidHide）", self.open_hidhide)
        nav_item("🔑 键位识别向导", self.open_wizard)
        nav_item("🧪 震动实验室", self.open_lab)
        nav_item("⏰ 震动闹钟", self.open_alarm)
        nav_item("📱 手机通知", self.open_notify)
        nav_item("📖 使用说明", self.show_help)
        nav_item("💾 保存键位", self.save)
        # 界面大小：滑块 80%~200%，松手保存，重启生效
        nav_header("界面大小")
        _auto_pct = int(round(padui.DPI / 96.0 * 100))
        _cur = self.km.get("ui_scale")
        _cur_pct = int(round(_cur * padui.DPI / 96.0 * 100)) if _cur else _auto_pct
        self.ui_scale_lbl = tk.Label(
            sb, text="%d%%%s" % (_cur_pct, "（自动）" if not _cur else ""),
            font=FT(8), fg=C_SUB, bg=C_CARD)
        self.ui_scale_lbl.pack(fill="x", padx=S(20))
        self.ui_scale = tk.IntVar(value=_cur_pct)
        sc = tk.Scale(sb, from_=80, to=200, orient="horizontal",
                      variable=self.ui_scale, resolution=5,
                      font=FT(8), fg=C_SUB, bg=C_CARD, troughcolor="#e3e5ea",
                      highlightthickness=0, sliderrelief="flat",
                      length=S(110), command=self._on_ui_scale_drag)
        sc.pack(fill="x", padx=S(20))
        sc.bind("<ButtonRelease-1>", self._on_ui_scale_done)
        self.ui_scale_hint = tk.Label(
            sb, text="", font=FT(7), fg=C_ACC, bg=C_CARD, anchor="w")
        self.ui_scale_hint.pack(fill="x", padx=S(20), pady=(S(2), S(0)))
        self.ui_btn = tk.Button(
            sb, text="↻ 重启生效", font=FT(8), fg=C_TEXT, bg="#f0f1f4",
            relief="flat", padx=S(8), pady=S(3), cursor="hand2",
            command=self._restart_app)
        self.ui_btn.pack(fill="x", padx=S(20), pady=(S(4), S(0)))

        nav_header("关于")
        nav_item("🔄 检查更新", self.open_update)

        ft = tk.Frame(sb, bg=C_CARD)
        ft.pack(side="bottom", pady=S(12))
        tk.Label(ft, text="BTP-V1T 先游定制版\nv" + updater.APP_VERSION,
                 font=FT(8), fg="#c2c6cd", bg=C_CARD,
                 justify="center").pack()
        self.foot_upd = tk.Label(ft, text="检查更新…", font=FT(8),
                                 fg="#c2c6cd", bg=C_CARD, cursor="hand2")
        self.foot_upd.pack(pady=(S(5), S(0)))
        self.foot_upd.bind("<Button-1>", lambda e: self.open_update())

        # ================= 主区 =================
        main = tk.Frame(self.root, bg=C_BG)
        main.pack(side="left", fill="both", expand=True)

        top = tk.Frame(main, bg=C_CARD)
        top.pack(fill="x")
        inner = tk.Frame(top, bg=C_CARD)
        inner.pack(fill="x", padx=S(22), pady=S(11))
        tk.Label(inner, text="键位映射", font=FT(15, "bold"),
                 fg=C_TEXT, bg=C_CARD).pack(side="left")
        self.chip = tk.Label(inner, text="● " + self.status.get(), font=FT(9),
                             fg=C_SUB, bg="#f4f5f8", padx=S(10), pady=S(4),
                             wraplength=S(430), justify="left")
        self.chip.pack(side="left", padx=S(14))
        # 手柄电量（插上手柄后自动检测，有线读不到就显示 USB 供电）
        self.lbl_batt = tk.Label(inner, text="🔋 …", font=FT(9),
                                 fg=C_SUB, bg="#f4f5f8", padx=S(10), pady=S(4))
        self.lbl_batt.pack(side="left", padx=(0, 8))
        self._batt_seq = 0
        self._refresh_batt()
        self.btn_run = tk.Button(inner, text="启动映射", font=FT(10, "bold"),
                                 fg="white", bg=C_RED, activebackground=C_RED_DK,
                                 activeforeground="white", relief="flat",
                                 padx=S(22), pady=S(6), cursor="hand2",
                                 command=self.toggle)
        self.btn_run.pack(side="right")
        # 屏蔽物理手柄：走 HidHide 内核过滤驱动（v1.0.13 起替换独占方案，
        # 独占打不过 XboxService / dwm 这些常年持有手柄句柄的系统组件）
        self.btn_hide = tk.Button(inner, text="屏蔽物理手柄", font=FT(9),
                                  relief="flat", padx=S(10), pady=S(6),
                                  cursor="hand2", command=self.toggle_hide)
        self.btn_hide.pack(side="right", padx=(0, 10))
        tk.Button(inner, text="⚙ 名单", font=FT(8), fg=C_SUB,
                  relief="flat", padx=S(8), pady=S(7), cursor="hand2",
                  command=self.open_hidhide).pack(side="right", padx=(0, 6))
        self._refresh_hide_btn()

        # ---------- 中央：手柄图 + 右侧状态 ----------
        row = tk.Frame(main, bg=C_BG)
        row.pack(fill="both", expand=True, padx=S(18), pady=S(14))

        lc = win11ui.Card(row, radius=12, bg=C_CARD, outline=C_LINE, pad=3)
        lc.pack(side="left")
        hdr = tk.Frame(lc.body, bg=C_CARD)
        hdr.pack(fill="x", padx=S(16), pady=(S(10), S(2)))
        tk.Label(hdr, text="实时手柄状态", font=FT(11, "bold"), fg=C_TEXT,
                 bg=C_CARD).pack(side="left")
        tk.Label(hdr, text="按下会亮绿 · 点任意键可重新绑定", font=FT(8),
                 fg=C_SUB, bg=C_CARD).pack(side="left", padx=S(8))
        self.canvas = tk.Canvas(lc.body, width=S(480), height=S(474), bg=C_CARD,
                                highlightthickness=0)
        self.canvas.pack(padx=S(8), pady=(S(2), S(10)))
        self.pad_view = PadView(self.canvas)
        self.pad_view.bind_click(self.rebind)

        # ---- 手柄图跟着窗口缩放 ----
        # PadView.draw() 内部按画布实际尺寸等比缩放居中，所以只要算出画布该多大。
        # 尺寸量化到 40px 一档：拖动窗口时不会每个像素都重合成一套贴图
        self._pad_sz = (S(480), S(474))
        self._pad_job = None
        # 右栏自然宽只测一次存下来：它要在窗口 item 里被强制改宽窄，
        # 但自然宽（reqwidth）是固定的。每次现算的话，手柄卡宽 → 右栏宽 →
        # 右栏内容回包 → 手柄卡宽……又是一圈正反馈
        self._rc_need = 0

        def _pad_fit(e=None):
            try:
                rw, rh = row.winfo_width(), row.winfo_height()
            except Exception:
                return
            if rw < 60 or rh < 60:
                return
            # 给右栏预留它的真实需求：内容自然宽 + 滚动条 + 左右 14px 边距
            # + rc_wrap 的 padx/ipadx + 一点余量。之前固定留 S(340)，可右栏
            # 自然就要 480 上下；两边卡片都改成跟自然宽走之后，手柄卡把自己的
            # 自然宽全要了过去，右栏被挤到 272 还来回晃。
            if self._rc_need <= 0:
                try:
                    need = (rc.winfo_reqwidth() + rc_sb.winfo_width()
                            + S(28) + S(34))
                    self._rc_need = max(need, S(340))
                except Exception:
                    self._rc_need = S(480)
            avail_w = rw - self._rc_need - S(16)
            avail_h = rh - S(84)             # 上面标题行 + 内边距 + 余量
            bw = max(S(280), min(avail_w, S(760)))
            bh = max(S(280), min(avail_h, S(900)))
            if bw / bh > 480 / 474:
                bw = int(bh * 480 / 474)
            else:
                bh = int(bw * 474 / 480)
            bw = max(S(200), bw // S(40) * S(40))
            bh = int(bw * 474 / 480)
            # win11ui.Card 启动布局时会把内容宽度钉死在当时的卡片宽度上，
            # 之后画布调多大卡片都不跟（最大化手柄图被锁小的根因）。
            # 这里把窗口项宽度归零=恢复跟随内容，卡片就会按新画布尺寸重新长。
            # 放在尺寸判等之前：就算尺寸没变也要解一次钉
            try:
                lc.cv.itemconfigure(lc._win, width=0)
            except Exception:
                pass
            if (bw, bh) == self._pad_sz:
                return
            self._pad_sz = (bw, bh)
            self.canvas.configure(width=bw, height=bh)
            self.pad_view.draw()

        def _pad_fit_debounced(e=None):
            if self._pad_job:
                self.root.after_cancel(self._pad_job)
            self._pad_job = self.root.after(120, _pad_fit)

        row.bind("<Configure>", _pad_fit_debounced)
        self.root.after(200, _pad_fit)

        # 右栏内容多（四马达那堆控件），窗口高度装不下 → 做成滚动容器，
        # 鼠标放右栏上滚轮滚，滚到头不影响别处
        rc_wrap = tk.Frame(row, bg=C_BG)
        # expand=True：窗口拉宽后右栏跟着铺满，不然右边一大片空白
        rc_wrap.pack(side="left", fill="both", expand=True, padx=(10, 6), ipadx=S(2))
        rc_cv = tk.Canvas(rc_wrap, bg=C_BG, highlightthickness=0)
        rc_sb = tk.Scrollbar(rc_wrap, orient="vertical", command=rc_cv.yview)
        rc_cv.configure(yscrollcommand=rc_sb.set)
        rc_sb.pack(side="right", fill="y")
        rc_cv.pack(side="left", fill="both", expand=True)
        rc = tk.Frame(rc_cv, bg=C_CARD)
        rc_win = rc_cv.create_window((S(14), S(14)), window=rc, anchor="nw")

        def _rc_round(_e=None):
            """圆角白卡片画在滚动 canvas 最底层，内容窗口四周内缩 14px"""
            rc_cv.delete("cardbg")
            ww, hh = rc_cv.winfo_width(), rc_cv.winfo_height()
            if ww > 8 and hh > 8:
                rc_cv.create_polygon(win11ui.Card._rr(1, 1, ww - 1, hh - 1, 12),
                                     fill=C_CARD, outline=C_LINE, smooth=True,
                                     tags="cardbg")
                rc_cv.tag_lower("cardbg")

        def _rc_on_cfg(_e):
            rc_cv.configure(scrollregion=rc_cv.bbox("all"))
            avail = rc_cv.winfo_width() - rc_sb.winfo_width() - S(28)
            # 内容最宽 640：窗口特别宽时列表按钮不至于拉得稀稀拉拉，居中放
            w = min(avail, S(640))
            rc_cv.itemconfigure(rc_win, width=w)
            rc_cv.coords(rc_win, max(S(14), (rc_cv.winfo_width() -
                                          rc_sb.winfo_width() - w) // 2), 14)
            _rc_round()

        rc.bind("<Configure>", _rc_on_cfg)
        rc_cv.bind("<Configure>", _rc_on_cfg)

        def _rc_wheel(e):
            try:
                w = self.root.winfo_containing(e.x_root, e.y_root)
            except Exception:
                return
            while w is not None and w is not rc_wrap:
                w = getattr(w, "master", None)
            if w is not rc_wrap or rc_cv.yview() == (0.0, 1.0):
                return
            rc_cv.yview_scroll(-1 if e.delta > 0 else 1, "units")

        self.root.bind("<MouseWheel>", _rc_wheel)
        tk.Label(rc, text="设备", font=FT(11, "bold"), fg=C_TEXT,
                 bg=C_CARD).pack(anchor="w", padx=S(14), pady=(S(10), S(4)))
        self.dev_lbl = tk.Label(rc, text="北通 BTP-V1T\n先游定制版", font=FT(9),
                                fg=C_TEXT, bg=C_CARD, justify="left")
        self.dev_lbl.pack(anchor="w", padx=S(14))
        tk.Label(rc, text="游戏里出现两个手柄？点上面「屏蔽物理手柄」，\n"
                         "让游戏只看到虚拟 Xbox 那一把（HidHide 驱动级屏蔽）。\n"
                         "随时可点，映射运行中也行。",
                 font=FT(8), fg=C_SUB, bg=C_CARD,
                 justify="left").pack(anchor="w", padx=S(14), pady=(S(4), S(0)))
        self.mode_lbl = tk.Label(rc, text="解码：未连接", font=FT(8), fg=C_SUB,
                                 bg=C_CARD)
        self.mode_lbl.pack(anchor="w", padx=S(14), pady=(S(2), S(8)))
        tk.Frame(rc, bg=C_LINE, height=1).pack(fill="x", padx=S(12))
        tk.Label(rc, text="改键（先启动映射）", font=FT(9, "bold"), fg=C_TEXT,
                 bg=C_CARD).pack(anchor="w", padx=S(14), pady=(S(8), S(4)))
        chips = tk.Frame(rc, bg=C_CARD)
        chips.pack(padx=S(12), fill="x")
        for i, name in enumerate(BTN_ORDER):
            cell = tk.Frame(chips, bg="#f4f5f8", highlightthickness=1,
                            highlightbackground=C_LINE)
            cell.grid(row=i // 2, column=i % 2, padx=S(3), pady=S(3), sticky="ew")
            tk.Label(cell, text=BTN_CN[name], font=FT(9, "bold", family="Consolas"),
                     fg="#5a5e66", bg="#f4f5f8", width=5).pack(side="left")
            lb = tk.Label(cell, text="改", font=FT(8), fg=C_RED,
                          bg="#f4f5f8", cursor="hand2", padx=S(4))
            lb.pack(side="left")
            lb.bind("<Button-1>", lambda e, n=name: self.rebind(n))
        chips.columnconfigure(0, weight=1)
        chips.columnconfigure(1, weight=1)

        # ---------- 右侧：震动 ----------
        tk.Frame(rc, bg=C_LINE, height=1).pack(fill="x", padx=S(12), pady=(S(10), S(0)))
        tk.Label(rc, text="震动", font=FT(9, "bold"), fg=C_TEXT,
                 bg=C_CARD).pack(anchor="w", padx=S(14), pady=(S(8), S(2)))
        self.rumble_on = tk.BooleanVar(value=bool(self.km.get("rumble", True)))
        tk.Checkbutton(rc, text="把游戏的震动转到手柄上", variable=self.rumble_on,
                       font=FT(9), fg=C_TEXT, bg=C_CARD,
                       activebackground=C_CARD, selectcolor="#eaf5ea",
                       command=self.on_rumble_cfg).pack(anchor="w", padx=S(12))
        fr = tk.Frame(rc, bg=C_CARD)
        fr.pack(fill="x", padx=S(14), pady=(S(4), S(0)))
        tk.Label(fr, text="命令格式", font=FT(8), fg=C_SUB,
                 bg=C_CARD).pack(side="left")
        names = [f[0] for f in betop.RUMBLE_FORMATS]
        self.rumble_fmt = tk.StringVar(value=names[self.km.get("rumble_fmt", 0)])
        om = tk.OptionMenu(fr, self.rumble_fmt, *names)
        om.config(font=FT(8), bg="#f4f5f8", relief="flat",
                  highlightthickness=0, width=16)
        om["menu"].config(font=FT(8))
        om.pack(side="left", padx=S(4))
        self.rumble_fmt.trace_add("write", lambda *_: self.on_rumble_cfg())
        # 震动强度滑块（转发和娱乐模式都吃这个系数）
        gr = tk.Frame(rc, bg=C_CARD)
        gr.pack(fill="x", padx=S(14), pady=(S(2), S(0)))
        tk.Label(gr, text="强度", font=FT(8), fg=C_SUB,
                 bg=C_CARD).pack(side="left")
        tk.Label(gr, text="(>100%放大)", font=FT(7), fg="#a0a4ad",
                 bg=C_CARD).pack(side="left")
        self.rumble_gain = tk.DoubleVar(
            value=float(self.km.get("rumble_gain", 1.0)))
        ttk.Scale(gr, from_=0.05, to=3.0, variable=self.rumble_gain,
                  length=118, command=lambda _v: self.on_gain()).pack(
            side="left", padx=S(4))
        self.gain_lbl = tk.Label(gr, text=f"{int(self.rumble_gain.get() * 100)}%",
                                 font=FT(8, family="Consolas"), fg=C_TEXT, bg=C_CARD, width=4)
        self.gain_lbl.pack(side="left")
        tb = tk.Frame(rc, bg=C_CARD)
        tb.pack(fill="x", padx=S(14), pady=(S(6), S(12)))
        tk.Button(tb, text="试震一下", font=FT(9), fg="white", bg=C_ACC,
                  activebackground=C_ACC_DK, activeforeground="white",
                  relief="flat", padx=S(10), pady=S(4), cursor="hand2",
                  command=self.test_rumble).pack(side="left")
        tk.Button(tb, text="停止震动", font=FT(9), fg="#c0392b", bg="#fdecea",
                  relief="flat", padx=S(10), pady=S(4), cursor="hand2",
                  command=self.stop_rumble).pack(side="left", padx=S(6))
        tk.Button(tb, text="自动识别", font=FT(9), fg=C_TEXT, bg="#f0f1f4",
                  relief="flat", padx=S(10), pady=S(4), cursor="hand2",
                  command=self.auto_scan).pack(side="left", padx=S(6))
        # 状态提示单独一行放着（跟三个按钮同排太宽，右栏会被裁）
        self.rumble_lbl = tk.Label(rc, text="", font=FT(8), fg=C_SUB,
                                   bg=C_CARD, wraplength=S(310), justify="left")
        self.rumble_lbl.pack(anchor="w", padx=S(14), pady=(S(2), S(0)))
        # ---- 四个马达单独测（左柄/右柄/左扳机/右扳机）----
        mt = tk.Frame(rc, bg=C_CARD)
        mt.pack(fill="x", padx=S(10), pady=(S(0), S(2)))
        tk.Label(mt, text="单马达", font=FT(8), fg=C_SUB,
                 bg=C_CARD).pack(side="left")
        self.motor_btns = {}
        for key, name in (("big", "左柄"), ("small", "右柄"),
                          ("tl", "左扳机"), ("tr", "右扳机")):
            b = tk.Button(mt, text=name, font=FT(8), bg="#f0f1f4",
                          fg=C_TEXT, relief="flat", padx=S(4), pady=S(2),
                          cursor="hand2",
                          command=lambda k=key: self.test_motor(k))
            b.pack(side="left", padx=S(1))
            self.motor_btns[key] = b
        self.btn_scan = tk.Button(mt, text="扫命令", font=FT(8),
                                  fg="#1e7e34", bg="#e6f4ea", relief="flat",
                                  padx=S(4), pady=S(2), cursor="hand2",
                                  command=self.open_motor_scan)
        self.btn_scan.pack(side="left", padx=S(3))
        tk.Button(mt, text="重置", font=FT(8), fg=C_SUB,
                  bg="#f0f1f4", relief="flat", padx=S(4), pady=S(2), cursor="hand2",
                  command=self.reset_rumble).pack(side="left")
        # 合并模式：反正都是震动，四个马达共用一条命令一起震
        self.rm_merge = tk.BooleanVar(
            value=bool(self.km.get("rumble_merge", True)))
        tk.Checkbutton(rc, text="四个马达合并成一个震动（不分左右 / 扳机）",
                       variable=self.rm_merge, font=FT(8), fg=C_TEXT,
                       bg=C_CARD, activebackground=C_CARD, selectcolor="#eaf5ea",
                       command=self.on_merge).pack(anchor="w", padx=S(12))
        # 游戏只发两大马达信号，扳机要震只能跟着手柄马达走
        self.trig_follow = tk.BooleanVar(
            value=bool(self.km.get("trig_follow", False)))
        self.cb_trig = tk.Checkbutton(
            rc, text="扳机马达跟着手柄一起震（游戏信号里没有扳机）",
            variable=self.trig_follow, font=FT(8), fg=C_SUB,
            bg=C_CARD, activebackground=C_CARD, selectcolor="#eaf5ea",
            command=self.on_trig_follow)
        self.cb_trig.pack(anchor="w", padx=S(12))
        self._refresh_motor_btns()
        # 诊断：游戏到底有没有把震动发过来
        self.dbg_lbl = tk.Label(rc, text="还没收到游戏的震动指令",
                                font=FT(8, family="Consolas"), fg="#a0a4ad",
                                bg=C_CARD, justify="left")
        self.dbg_lbl.pack(anchor="w", padx=S(14), pady=(S(0), S(4)))
        # 娱乐模式：手柄无限震动，再点一次停
        self.fun_stop = threading.Event()
        self._fun_thread = None
        self._fun_rm = None
        self._fun_own = False
        tb2 = tk.Frame(rc, bg=C_CARD)
        tb2.pack(fill="x", padx=S(14), pady=(S(6), S(12)))
        self.btn_fun = tk.Button(tb2, text="娱乐模式 · 无限震动",
                                 font=FT(9, "bold"), fg="white", bg="#8e44ad",
                                 activebackground="#6c3483",
                                 activeforeground="white", relief="flat",
                                 padx=S(12), pady=S(4), cursor="hand2",
                                 command=self.toggle_fun)
        self.btn_fun.pack(side="left")
        tk.Label(tb2, text="再点一次按钮停止", font=FT(8), fg=C_SUB,
                 bg=C_CARD).pack(side="left", padx=S(6))
        cl = tk.Frame(rc, bg=C_CARD)
        cl.pack(fill="x", padx=S(14), pady=(S(0), S(10)))
        self.custom_lbl = tk.Label(cl, text=self._custom_text(),
                                   font=FT(8), fg=C_SUB, bg=C_CARD,
                                   justify="left", wraplength=S(210))
        self.custom_lbl.pack(side="left")
        self.btn_clr_custom = tk.Button(
            cl, text="🗑", font=FT(8), relief="flat", bg="#fdecea",
            fg="#c0392b", padx=S(5), pady=S(0), cursor="hand2",
            command=lambda: self.clear_custom(True))
        self.btn_clr_custom.pack(side="right")

        # ---------- 底部：摇杆 / 扳机 ----------
        bc = win11ui.Card(main, radius=12, bg=C_CARD, outline=C_LINE, pad=3)
        bc.pack(fill="x", padx=S(18), pady=(S(0), S(14)))
        head = tk.Frame(bc.body, bg=C_CARD)
        head.pack(fill="x", padx=S(16), pady=(S(10), S(4)))
        tk.Label(head, text="摇杆 / 扳机", font=FT(11, "bold"), fg=C_TEXT,
                 bg=C_CARD).pack(side="left")
        tk.Label(head, text="摇杆死区", font=FT(9), fg=C_TEXT,
                 bg=C_CARD).pack(side="right")
        self.dz = tk.DoubleVar(value=self.km.get("deadzone", 0.12))
        ttk.Scale(head, from_=0, to=0.5, variable=self.dz, length=S(110),
                  command=lambda v: self.on_dz()).pack(side="right")
        self.dz_lbl = tk.Label(head, text=f"{self.dz.get():.2f}",
                               font=FT(9, family="Consolas"), fg=C_TEXT, bg=C_CARD, width=4)
        self.dz_lbl.pack(side="right")

        bars = tk.Frame(bc.body, bg=C_CARD)
        bars.pack(fill="x", padx=S(16), pady=(S(0), S(12)))
        self.bars = {}
        for i, k in enumerate(betop.AXIS_TARGETS):
            col = tk.Frame(bars, bg=C_CARD)
            col.grid(row=0, column=i, padx=S(6))
            tk.Label(col, text=k, font=FT(9, "bold", family="Consolas"), fg=C_SUB,
                     bg=C_CARD).pack()
            cv = tk.Canvas(col, width=S(104), height=S(12), bg="#f4f5f8", highlightthickness=0)
            cv.pack(pady=S(2))
            self.bars[k] = cv
            fz = tk.Label(col, text="反向", font=FT(8), fg=C_RED, bg=C_CARD,
                          cursor="hand2")
            fz.pack()
            fz.bind("<Button-1>", lambda e, kk=k: self.flip(kk))
            if k in ("LX", "LY", "RX", "RY"):
                cz = tk.Label(col, text="中位", font=FT(8), fg=C_RED, bg=C_CARD,
                              cursor="hand2")
                cz.pack()
                cz.bind("<Button-1>", lambda e, kk=k: self.calib(kk))

        self.root.after(70, self.pump)

    # ------------------------------------------------------------ 控制
    def toggle(self):
        if self.running:
            self.stop_mapping()
        else:
            self.start_mapping()

    def stop_mapping(self):
        self.stop.set()
        self.running = False
        self.fun_stop.set()          # 娱乐模式一起停
        self._close_rumble()
        th = getattr(self, "loop_th", None)
        if th is not None and th.is_alive():
            th.join(timeout=1.5)     # 等 loop 收尾把句柄关掉，不然重开时会撞
        # 屏蔽开着时留着 dev：句柄一放，重开就得赌白名单生效
        if not self.km.get("shield"):
            self.dev = None
        self.pad = None
        self.btn_run.config(text="启动映射", bg=C_RED)
        self.status.set("已停止")
        self._refresh_status()

    def start_mapping(self, quiet=False):
        """开映射。返回 True/False"""
        try:
            # 已经握着句柄（比如先点了屏蔽）就直接用，别重复开
            if self.dev is None:
                self.dev = betop.open_device()
            self.pad = betop.VirtualPad(rumble_callback=self.on_rumble)
        except Exception as e:
            # 半途失败要把已经打开的手柄句柄关掉，不然泄漏一个独占路障
            if getattr(self, "dev", None):
                try:
                    self.dev.close()
                except Exception:
                    pass
                self.dev = None
            if not quiet:
                messagebox.showerror("启动失败",
                                     f"{e}\n\n确认 ViGEmBus 驱动装好了没")
            return False
        # 震动通道单独开（游戏接口没有输出报告），开不了也只是没震，不影响映射
        try:
            self.rumble = betop.Rumble(**self._rumble_kw()).open()
            self.rumble_lbl.config(text="震动通道已开")
        except Exception as e:
            self.rumble = None
            self.rumble_lbl.config(text=f"震动通道开不了：{e}")
            self.dbg_lbl.config(text="震动通道开不了，游戏震动转不出去",
                                fg="#c0392b")
        self._sync_shield()
        self.stop.clear()
        self.running = True
        self.btn_run.config(text="停止映射", bg="#5a5e66")
        be = "HidP 精确解码" if self.dev.use_hidp else "字节兜底"
        hid = " · 物理手柄已屏蔽" if self.km.get("shield") else ""
        self.status.set(f"运行中（{be}{hid}）— 去开基岩版 MC")
        self.mode_lbl.config(text="解码：" + be)
        self._refresh_status()
        self.loop_th = threading.Thread(target=self.loop, daemon=True)
        self.loop_th.start()
        return True

    # ------------------------------------------------------- 屏蔽物理手柄
    def _shield_insts(self):
        """要操作的设备实例：当下枚举到的 ∪ 上次屏蔽时记下来的。

        记历史这一步很关键 —— 手柄休眠/拔掉后枚举不到它，只靠实时枚举就
        再也解除不了屏蔽了（按钮会一直显示"已屏蔽"且点不动）。
        """
        insts = []
        try:
            insts += hidhide.betop_instances(betop.VID)
        except Exception:
            pass
        for i in (self.km.get("shield_insts") or []):
            if i not in insts:
                insts.append(i)
        return insts

    def _shield_state(self):
        """以 HidHide 驱动里的实际名单为准"""
        if not hidhide.installed():
            return None
        insts = self._shield_insts()
        if not insts:
            return None
        return any(hidhide.is_shielded(i) for i in insts)

    def _refresh_hide_btn(self):
        on = self._shield_state()
        if on is None:
            self.btn_hide.config(text="屏蔽物理手柄（需装 HidHide）",
                                 bg="#f0f1f4", fg=C_SUB)
        elif on:
            self.btn_hide.config(text="物理手柄已屏蔽",
                                 bg="#e6f4ea", fg="#1e7e34")
        else:
            self.btn_hide.config(text="屏蔽物理手柄", bg="#f0f1f4", fg=C_TEXT)

    def _ensure_hidhide(self):
        """没装 HidHide 就引导安装。装好返回 True"""
        if hidhide.installed():
            return True
        src = os.path.join(os.path.dirname(HERE), "HidHide_x64.exe")
        if not os.path.isfile(src):
            src = os.path.join(HERE, "HidHide_x64.exe")
        if os.path.isfile(src):
            msg = ("屏蔽物理手柄需要 HidHide 内核过滤驱动（跟 ViGEmBus 同一家"
                   "出的，用来把物理手柄从游戏眼前藏掉）。\n\n"
                   "已经附带好了安装包，点「是」现在装（会弹 UAC 授权）。")
            if not messagebox.askyesno("需要装 HidHide", msg):
                return False
            self.status.set("正在安装 HidHide ……")
            self._refresh_status()
            ok = hidhide.install_silent(src)
        else:
            msg = ("屏蔽物理手柄需要 HidHide 内核过滤驱动。\n\n"
                   "点「是」去官方页面下载安装（约 8MB），装完回来再点一次屏蔽。")
            if not messagebox.askyesno("需要装 HidHide", msg):
                return False
            import webbrowser
            webbrowser.open("https://github.com/nefarius/HidHide/releases")
            return False
        if not ok or not hidhide.installed():
            messagebox.showerror("安装没完成",
                                 "HidHide 没装上（可能 UAC 点了取消，或者装完"
                                 "要重启）。\n可以手动跑目录里的 HidHide_x64.exe。")
            return False
        messagebox.showinfo("装好了", "HidHide 已安装，现在帮你把物理手柄屏蔽掉。")
        return True

    def _sync_shield(self):
        """屏蔽开着时，把【当前】这把的实例补进黑名单。

        HidHide 是按设备实例路径匹配的，而实例路径里带着 USB 口信息 ——
        换个 USB 口插，路径就变了，老的黑名单条目立刻失效。所以每回开
        映射（此时确定能读到手柄）都补一次，换口也不怕。
        """
        if not self.km.get("shield"):
            return
        if not hidhide.installed():
            return
        try:
            insts = hidhide.betop_instances(betop.VID)
        except Exception:
            return
        if not insts:
            return
        missing = [i for i in insts if not hidhide.is_shielded(i)]
        if not missing:
            self.km["shield_insts"] = insts
            return
        me = os.path.abspath(sys.argv[0])
        apps = [a for a in (me, os.path.join(os.path.dirname(me),
                                             "BetopWizard.exe"))
                if os.path.isfile(a)]
        hidhide.shield_on(missing, apps)
        self.km["shield_insts"] = insts
        betop.save_keymap(self.km)

    def toggle_hide(self):
        if not self._ensure_hidhide():
            return
        # 先把手柄句柄攥在手里再隐藏：HidHide 不会收回已经打开的句柄，
        # 所以哪怕白名单没生效（换机器 / 中文路径被 CLI 截断之类），
        # 映射照样读得到物理手柄。这是屏蔽能稳稳管用的关键顺序。
        if self.dev is None:
            try:
                self.dev = betop.open_device()
            except Exception:
                pass          # 读不到也别拦着，手柄离线时还要能解除屏蔽
        insts = self._shield_insts()
        if not insts:
            messagebox.showerror("屏蔽失败",
                                 "既没枚举到北通手柄，也没有历史记录可解除。\n"
                                 "把手柄插上 / 按 LOGO 唤醒后再点一次。")
            return
        want = not any(hidhide.is_shielded(i) for i in insts)
        self.status.set("正在改 HidHide 黑名单 ……")
        self._refresh_status()
        if want:
            # 把映射器 / 向导都加进白名单，不然屏蔽后自己反倒读不到手柄；
            # 白名单 + 藏设备 + 总开关串成一条 CLI 调用
            me = os.path.abspath(sys.argv[0])
            apps = {me, os.path.join(os.path.dirname(me), "BetopWizard.exe")}
            ok = hidhide.shield_on(insts,
                                   [a for a in apps if os.path.isfile(a)])
        else:
            ok = hidhide.shield_off(insts)
        if not ok:
            messagebox.showerror(
                "屏蔽失败",
                "HidHide 名单没改成（点了 UAC 取消？驱动没起来？）。\n\n"
                "可以手动确认：\n"
                r'C:\Program Files\Nefarius Software Solutions\HidHide\x64'
                r'\HidHideCLI.exe --dev-list')
            self._refresh_hide_btn()
            return
        self.km["shield_insts"] = insts
        self.km["shield"] = any(hidhide.is_shielded(i) for i in insts)
        betop.save_keymap(self.km)
        self._refresh_hide_btn()
        if self.km["shield"]:
            self.status.set("物理手柄已屏蔽 — 游戏里只剩虚拟 Xbox 那把\n"
                            "（映射器自己走了白名单，照读不误）")
        else:
            self.status.set("物理手柄恢复可见（游戏里会有两把）")
        self._refresh_status()

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
            self.rumble.custom = self.km.get("rumble_custom")
            self.rumble.custom_trig = self.km.get("rumble_custom_trig")
            self.rumble.merge = bool(self.km.get("rumble_merge", True))
            self.rumble._last = None       # 模板换过，别被去重挡住

    # -------------------------------------------------- 四个马达各自配置
    MOTOR_CN = {"big": "左柄（大马达）", "small": "右柄（小马达）",
                "tl": "左扳机", "tr": "右扳机"}

    def _rumble_kw(self):
        """造 Rumble 的统一参数：手柄马达模板 + 扳机马达模板"""
        return dict(fmt=self._fmt_index(),
                    enabled=bool(self.rumble_on.get()),
                    custom=self.km.get("rumble_custom"),
                    custom_trig=self.km.get("rumble_custom_trig"),
                    merge=bool(self.km.get("rumble_merge", True)))

    def _motor_tpl_key(self, which):
        return "rumble_custom_trig" if which in ("tl", "tr") \
            else "rumble_custom"

    def _has_motor(self, which):
        """这个马达有没有命令可用（没扫出来的点上去只会白震）"""
        if self.km.get("rumble_merge", True):
            return True      # 合并模式：四个马达共用一条命令，都能震
        tpl = self.km.get(self._motor_tpl_key(which))
        if tpl is None:
            # 没自定义模板时走下拉里的候选格式，左右两个槽都在
            return which in ("big", "small")
        return bool(betop._norm_motor(tpl.get("motor")).get(which))

    def _refresh_motor_btns(self):
        m = bool(self.km.get("rumble_merge", True))
        for k, b in getattr(self, "motor_btns", {}).items():
            ok = self._has_motor(k)
            b.config(text=self.MOTOR_CN[k].split("（")[0] + ("" if ok else " ?"),
                     bg="#e6f4ea" if ok else "#f0f1f4",
                     fg="#1e7e34" if ok else "#a0a4ad")
        # 合并模式下不用扫命令、也不用单独勾扳机跟随（本来就一起震）
        if getattr(self, "btn_scan", None) is not None:
            self.btn_scan.config(state="disabled" if m else "normal",
                                 fg="#a0a4ad" if m else "#1e7e34")
        if getattr(self, "cb_trig", None) is not None:
            self.cb_trig.config(state="disabled" if m else "normal",
                                fg="#c8ccd4" if m else C_SUB)

    def on_merge(self):
        self.km["rumble_merge"] = bool(self.rm_merge.get())
        betop.save_keymap(self.km)
        if self.rumble is not None:
            self.rumble.merge = self.km["rumble_merge"]
        self._refresh_motor_btns()

    def on_trig_follow(self):
        self.km["trig_follow"] = bool(self.trig_follow.get())
        betop.save_keymap(self.km)

    def test_motor(self, which):
        """单独震一个马达 0.9 秒"""
        if which in ("tl", "tr") and not self._has_motor(which):
            if messagebox.askyesno(
                    "扳机马达还没配命令",
                    f"「{self.MOTOR_CN[which]}」的命令还没扫出来。\n\n"
                    "协议没公开，得挨个试命令才能找出来 —— 现在去扫？\n"
                    "（会一条条发，感觉到震就点「有感，就它了」）",
                    parent=self.root):
                self.open_motor_scan(which)
            return
        try:
            r, own = self.rumble, False
            if r is None or r.dev is None:
                r = betop.Rumble(**self._rumble_kw()).open()
                own = True
        except Exception as e:
            self.rumble_lbl.config(text=f"打不开：{e}")
            return
        merged = bool(self.km.get("rumble_merge", True))
        self.rumble_lbl.config(
            text=("四个马达一起震 0.9 秒…" if merged
                  else f"{self.MOTOR_CN[which]} 震 0.9 秒…"))

        def go():
            err = None
            try:
                r.play_motor(which, 255, 0.9)
            except Exception as e:
                err = str(e)
            if own:
                try:
                    r.stop_all()
                    r.close()
                except Exception:
                    pass
            if err:
                self.root.after(0, lambda: self.rumble_lbl.config(text=err))

        threading.Thread(target=go, daemon=True).start()

    def reset_rumble(self):
        """扫错了 / 震动全废时的救命按钮：回到已验证能震的那条命令"""
        if not messagebox.askyesno(
                "重置震动命令",
                "恢复成已经验证能震的那条：\n"
                "  WriteFile · 命令头 0x08 · 大马达第 3 字节、小马达第 4 字节\n\n"
                "（你扫出来的配置会丢掉，确定吗？）", parent=self.root):
            return
        self.km["rumble_fmt"] = 28
        self.km["rumble_custom"] = {"chan": "write", "fixed": [[1, 8]],
                                    "motor": {"big": 3, "small": 4}}
        self.km.pop("rumble_custom_trig", None)
        betop.save_keymap(self.km)
        if self.rumble is not None:
            self.rumble.fmt = 28
            self.rumble.custom = self.km.get("rumble_custom")
            self.rumble.custom_trig = None
            self.rumble._last = None
        self.rumble_fmt.set(betop.RUMBLE_FORMATS[28][0])
        self._refresh_motor_btns()
        self.rumble_lbl.config(text="已恢复默认震动命令，点「试震一下」看看")

    def open_motor_scan(self, which=None):
        """扫未知马达的命令（右柄 / 扳机）"""
        try:
            MotorScan(self.root, self, which or "small")
        except Exception as e:
            messagebox.showerror("扫不了", str(e), parent=self.root)

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
            b, s = min(255, int(big * g)), min(255, int(small * g))
            # XInput 只有两大马达信号，扳机要震就只能跟着走；
            # 合并模式下本来就四个一起，直接给上
            if self.km.get("trig_follow") or self.km.get("rumble_merge", True):
                tl, tr = b, s
            else:
                tl = tr = 0
            self.rumble.set(b, s, tl, tr)
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
                rm = betop.Rumble(**self._rumble_kw()).open()
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
            r = betop.Rumble(**self._rumble_kw()).open()
        except Exception as e:
            self.rumble_lbl.config(text=f"打不开：{e}")
            return
        merged = bool(self.km.get("rumble_merge", True))
        self.rumble_lbl.config(text="震两下…" if merged else "连震三下…")

        def go():
            try:
                g = self._gain()
                if merged:
                    # 合并模式下四个马达一起，单独试大/小没意义
                    seq = [(255, 255), (0, 0), (255, 255), (0, 0)]
                else:
                    # 先单独大马达、再单独小马达、最后两个一起，好分辨哪个在响
                    seq = [(255, 0), (0, 0), (0, 255), (0, 0),
                           (255, 255), (0, 0)]
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
                rm = betop.Rumble(**self._rumble_kw()).open()
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
                rm = betop.Rumble(**self._rumble_kw()).open()
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
        win.geometry("%dx%d" % (S(440), S(230)))
        win.resizable(False, False)
        win.transient(self.root)
        tk.Label(win, text="程序会挨个发候选命令，手柄一直震着", font=FT(11, "bold"),
                 fg=C_TEXT, bg=C_CARD).pack(pady=(S(16), S(2)))
        tk.Label(win, text="感觉到震动就点「这次震了！」，没感觉点「下一个」",
                 font=FT(9), fg=C_SUB, bg=C_CARD).pack()
        v_prog = tk.StringVar(value="")
        tk.Label(win, textvariable=v_prog, font=FT(9, family="Consolas"), fg=C_ACC,
                 bg=C_CARD).pack(pady=(S(10), S(0)))
        v_name = tk.StringVar(value="")
        tk.Label(win, textvariable=v_name, font=FT(11, family="Consolas"), fg=C_TEXT,
                 bg="#f4f5f8", padx=S(8), pady=S(6), width=42).pack(pady=S(4))

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
        bt.pack(pady=S(12))
        tk.Button(bt, text="这次震了！用这个", font=FT(10, "bold"), fg="white",
                  bg=C_ACC, activebackground=C_ACC_DK, activeforeground="white",
                  relief="flat", padx=S(14), pady=S(6), cursor="hand2",
                  command=lambda: cleanup(st["i"])).pack(side="left", padx=S(6))
        tk.Button(bt, text="下一个", font=FT(10), fg=C_TEXT, bg="#f0f1f4",
                  relief="flat", padx=S(14), pady=S(6), cursor="hand2",
                  command=next_cand).pack(side="left", padx=S(6))
        tk.Button(bt, text="放弃", font=FT(10), fg=C_SUB, bg="#f0f1f4",
                  relief="flat", padx=S(14), pady=S(6), cursor="hand2",
                  command=lambda: cleanup()).pack(side="left", padx=S(6))
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
            # 屏蔽开着就别松手：句柄一放，能不能再开回来就得看白名单脸色，
            # 握着它才是稳的（HidHide 不会收回已打开的句柄）
            if self.dev and not self.km.get("shield"):
                self.dev.close()
        except Exception:
            pass
        self._close_rumble()

    # ------------------------------------------------------------ 实时刷新
    def pump(self):
        self._drain_tray()
        self._drain_alarm()
        self._drain_notify()
        if self.running:
            b = self.state.get("buttons", {})
            a = self.state.get("axes", {})
            self.pad_view.set_state(b, a)
            for k, bar in self.bars.items():
                self.draw_bar(bar, a.get(k, 0.0), k)
        # 震动联动：有马达在转就让图上的手柄跟着抖
        try:
            self.pad_view.set_shake(betop.Rumble.max_level())
        except Exception:
            pass
        # 电量：每 ~8 秒重探一次（读 HID 要开句柄，别太勤）
        self._batt_seq += 1
        if self._batt_seq >= 115:
            self._batt_seq = 0
            self._refresh_batt()
        self.root.after(70, self.pump)

    def _refresh_batt(self):
        """后台线程探测电量，回来刷新标签（battery_info 要开句柄会卡 1~2 秒）"""
        def work():
            try:
                info = betop.battery_info()
            except Exception:
                info = None
            try:
                # 窗口已关时 mainloop 已退出，after 会炸 —— 静默即可
                self.root.after(0, lambda: self._show_batt(info))
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _show_batt(self, info):
        if info is None:
            self.lbl_batt.config(text="🔋 未连接", fg="#c2c6cd")
        elif isinstance(info, tuple) and info and info[0] == "usb":
            self.lbl_batt.config(text="🔌 USB 供电", fg=C_SUB)
        elif isinstance(info, tuple) and isinstance(info[0], int):
            self.lbl_batt.config(text=f"🔋 {info[0]}%",
                                 fg=C_OK if info[0] > 20 else C_RED)
        else:
            self.lbl_batt.config(text="🔋 --", fg=C_SUB)

    def draw_bar(self, cv, v, k=""):
        cv.delete("all")
        w = int(cv["width"]); h = int(cv["height"])
        mid = w // 2
        n = int(abs(v) * (mid - 2))
        color = C_RED if v < 0 else "#3a7bff"
        if v >= 0:
            cv.create_rectangle(mid, 2, mid + n, h - 2, fill=color, outline="")
        else:
            cv.create_rectangle(mid - n, 2, mid, h - 2, fill=color, outline="")
        if k in ("LY", "RY"):
            # 纵向轴：横条看不出哪头是上，标出来（推上=往右↑填蓝）
            cv.create_text(5, h // 2, text="↓", font=FT(7, family="Consolas"),
                           fill="#c2c6cd")
            cv.create_text(w - 5, h // 2, text="↑", font=FT(7, family="Consolas"),
                           fill="#c2c6cd")

    # ------------------------------------------------------------ 改键
    def rebind(self, name):
        if not self.running:
            messagebox.showinfo("先启动", "先点右上角「启动映射」再改键")
            return
        self.rebind_target = name
        win = tk.Toplevel(self.root)
        win.title(f"绑定 {name}")
        win.geometry("%dx%d" % (S(400), S(140)))
        win.transient(self.root)
        tk.Label(win, text=f"按住手柄上想当 {BTN_CN[name]} 用的键…",
                 font=FT(11)).pack(pady=S(24))
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


class MotorScan:
    """给还没找出命令的马达（右柄 / 扳机）扫命令。

    协议是厂商私有的，没得抓包只能穷举：命令头字节 × 强度字节位置，
    一条条发 0.9 秒，用户感觉到目标马达在震就点「有感」，存进 keymap。
    """

    # 0x08 是已经验证能把左柄大马达震起来的命令头，放最前面先试
    HEADS = [0x08, 0x00, 0x01, 0x02, 0x04, 0x0B, 0x10, 0x11, 0x12, 0x20,
             0x40, 0x55]
    OFFS = [3, 4, 5, 6, 7, 8]
    TRY_SEC = 0.9
    MOTORS = (("big", "左柄（大马达）"), ("small", "右柄（小马达）"),
              ("tl", "左扳机"), ("tr", "右扳机"))

    def __init__(self, parent, app, which="small"):
        self.app = app
        self.which = tk.StringVar(value=which)
        self.rm = betop.Rumble(**app._rumble_kw()).open()
        self.chan_mode = tk.StringVar(value="write")
        self.stop_ev = threading.Event()
        self.got_ev = threading.Event()
        self.skip_ev = threading.Event()
        self.cur = None          # (chan, head, off, 序号)
        self._undo = None        # (keymap键, 保存前的模板)
        self.th = None

        w = tk.Toplevel(parent)
        self.win = w
        w.title("扫马达命令")
        w.geometry("%dx%d" % (S(430), S(300)))
        w.configure(bg=C_BG)
        w.transient(parent)
        tk.Label(w, text="扫马达命令", font=FT(12, "bold"), fg=C_TEXT,
                 bg=C_BG).pack(anchor="w", padx=S(14), pady=(S(12), S(2)))
        tk.Label(w, text="协议没公开，只能挨个试。把要找的马达选上，点开始，"
                         "感觉到它在震就立刻点「有感，就它了」。",
                 font=FT(8), fg=C_SUB, bg=C_BG, wraplength=S(400),
                 justify="left").pack(anchor="w", padx=S(14))
        mf = tk.Frame(w, bg=C_BG)
        mf.pack(fill="x", padx=S(14), pady=(S(8), S(2)))
        for key, name in self.MOTORS:
            tk.Radiobutton(mf, text=name, variable=self.which, value=key,
                           font=FT(9), fg=C_TEXT, bg=C_BG,
                           activebackground=C_BG, selectcolor="#eaf5ea",
                           command=self._on_pick).pack(side="left", padx=S(2))
        self.prog = tk.Label(w, text="点「开始扫描」", font=FT(9),
                             fg=C_TEXT, bg=C_BG, justify="left")
        self.prog.pack(anchor="w", padx=S(14), pady=(S(10), S(2)))
        self.hex_lbl = tk.Label(w, text="", font=FT(9, family="Consolas"), fg=C_SUB,
                                bg=C_BG)
        self.hex_lbl.pack(anchor="w", padx=S(14))
        cf = tk.Frame(w, bg=C_BG)
        cf.pack(fill="x", padx=S(14), pady=(S(4), S(0)))
        tk.Label(cf, text="通道", font=FT(8), fg=C_SUB,
                 bg=C_BG).pack(side="left")
        tk.Radiobutton(cf, text="只试 WriteFile（快）", variable=self.chan_mode,
                       value="write", font=FT(8), fg=C_TEXT, bg=C_BG,
                       activebackground=C_BG,
                       selectcolor="#eaf5ea").pack(side="left", padx=S(4))
        tk.Radiobutton(cf, text="两种通道都试（慢一倍）", variable=self.chan_mode,
                       value="both", font=FT(8), fg=C_TEXT, bg=C_BG,
                       activebackground=C_BG,
                       selectcolor="#eaf5ea").pack(side="left")
        bf = tk.Frame(w, bg=C_BG)
        bf.pack(fill="x", padx=S(14), pady=(S(12), S(6)))
        self.btn_go = tk.Button(bf, text="开始扫描", font=FT(9), fg="white",
                                bg=C_ACC, activebackground=C_ACC_DK,
                                activeforeground="white", relief="flat",
                                padx=S(10), pady=S(4), cursor="hand2",
                                command=self.start)
        self.btn_go.pack(side="left")
        self.btn_got = tk.Button(bf, text="有感，就它了", font=FT(9),
                                 fg="#1e7e34", bg="#e6f4ea", relief="flat",
                                 padx=S(10), pady=S(4), cursor="hand2",
                                 state="disabled", command=self.got)
        self.btn_got.pack(side="left", padx=S(4))
        tk.Button(bf, text="下一条", font=FT(9), fg=C_TEXT, bg="#f0f1f4",
                  relief="flat", padx=S(10), pady=S(4), cursor="hand2",
                  command=self.skip).pack(side="left")
        tk.Button(bf, text="停", font=FT(9), fg="#c0392b", bg="#fdecea",
                  relief="flat", padx=S(10), pady=S(4), cursor="hand2",
                  command=self.stop).pack(side="left", padx=S(4))
        self.btn_undo = tk.Button(bf, text="撤销上次", font=FT(9),
                                  fg=C_TEXT, bg="#f0f1f4", relief="flat",
                                  padx=S(8), pady=S(4), cursor="hand2",
                                  state="disabled", command=self.undo)
        self.btn_undo.pack(side="left")
        tk.Label(w, text="全程手柄都在通电状态，扫完记得停一下；"
                         "中途卡住震个不停就点「停」再关窗口。",
                 font=FT(7), fg="#a0a4ad", bg=C_BG, wraplength=S(400),
                 justify="left").pack(anchor="w", padx=S(14), pady=(S(6), S(0)))
        w.protocol("WM_DELETE_WINDOW", self.close)
        self._on_pick()

    # ---------------------------------------------------------- 交互
    def _on_pick(self):
        n = dict(self.MOTORS).get(self.which.get(), "")
        self.prog.config(text=f"目标：{n}")

    def start(self):
        if self.th is not None and self.th.is_alive():
            return
        self.stop_ev.clear()
        self.got_ev.clear()
        self.skip_ev.clear()
        self.btn_go.config(state="disabled")
        self.btn_got.config(state="normal")
        self.th = threading.Thread(target=self._run, daemon=True)
        self.th.start()

    def got(self):
        self.got_ev.set()

    def undo(self):
        """存错了就退回保存前的那条命令"""
        if not self._undo:
            return
        key, old = self._undo
        if old is None:
            self.app.km.pop(key, None)
        else:
            self.app.km[key] = old
        betop.save_keymap(self.app.km)
        rm = self.app.rumble
        if rm is not None:
            if key == "rumble_custom_trig":
                rm.custom_trig = self.app.km.get(key)
            else:
                rm.custom = self.app.km.get(key)
        self.app._refresh_motor_btns()
        self._undo = None
        self.btn_undo.config(state="disabled")
        self.prog.config(text="已撤销，回到保存前的命令")

    def skip(self):
        self.skip_ev.set()

    def stop(self):
        self.stop_ev.set()

    def close(self):
        self.stop_ev.set()
        try:
            if self.th is not None:
                self.th.join(timeout=1.5)
        except Exception:
            pass
        try:
            self.rm.stop_all()
            self.rm.close()
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass

    # ---------------------------------------------------------- 扫描
    def _chans(self):
        return ("write", "set") if self.chan_mode.get() == "both" \
            else ("write",)

    def _busy_offsets(self):
        """别的马达已经占掉的字节位置。

        扫右柄时第一条候选本来是「头 0x08 + 第 3 字节」—— 那正是左柄大马达
        的命令，手柄必然在震，一感觉到就点「有感」就会把右柄记成左柄的位置，
        结果震动全废。所以这些位置直接跳过不试。
        """
        which = self.which.get()
        out = set()
        for key in ("rumble_custom", "rumble_custom_trig"):
            tpl = self.app.km.get(key) or {}
            for k, off in betop._norm_motor(tpl.get("motor")).items():
                if k != which:
                    out.add(off)
        return out

    def _candidates(self):
        skip = self._busy_offsets()
        out = []
        for chan in self._chans():
            for head in self.HEADS:
                for off in self.OFFS:
                    if off in skip:
                        continue
                    out.append((chan, head, off))
        return out

    def _send(self, chan, head, off, v):
        b = [2] + [0] * 63
        if head:
            b[1] = head
        b[off] = v
        try:
            if chan == "set":
                self.rm.dev.set_report(b)
            else:
                self.rm.dev.write(b)
        except Exception:
            pass

    @staticmethod
    def _hex(head, off, v=255):
        b = [2] + [0] * 63
        if head:
            b[1] = head
        b[off] = v
        return " ".join(f"{x:02X}" for x in b[:10]) + " …"

    def _run(self):
        cands = self._candidates()
        total = len(cands)
        i = 0
        for chan, head, off in cands:
            if self.stop_ev.is_set():
                return self._done(False)
            i += 1
            self.cur = (chan, head, off, i)
            # 每条一开始就锁住「有感」，0.7 秒后才让点 —— 防手快点错
            self.app.root.after(0, lambda i=i, h=head, o=off, c=chan: (
                self.btn_got.config(state="disabled"),
                self.prog.config(
                    text=f"第 {i}/{total} 条："
                         f"{'SET_REPORT' if c == 'set' else 'WriteFile'}"
                         f" · 头 0x{h:02X} · 强度写在第 {o} 字节"),
                self.hex_lbl.config(text=self._hex(h, o))))
            self.app.root.after(700, lambda: (
                self.btn_got.config(state="normal")
                if not self.stop_ev.is_set() else None))
            t0 = time.time()
            while time.time() - t0 < self.TRY_SEC:
                if self.stop_ev.is_set() or self.got_ev.is_set() \
                        or self.skip_ev.is_set():
                    break
                self._send(chan, head, off, 255)
                time.sleep(0.05)
            self._send(chan, head, off, 0)
            if self.got_ev.is_set():
                c, h, o, _n = self.cur
                self.app.root.after(0, lambda c=c, h=h, o=o:
                                    self._save(c, h, o))
                return
            self.skip_ev.clear()
        self._done(True)

    def _done(self, finished):
        def ui():
            self.btn_go.config(state="normal")
            self.btn_got.config(state="disabled")
            if finished:
                self.prog.config(text="扫完了，都没反应 —— 这个马达可能根本"
                                      "没装，或者得走别的通道")
        self.app.root.after(0, ui)

    # ---------------------------------------------------------- 保存
    @staticmethod
    def _fmt_to_spec(idx):
        """把下拉里正在用的那条候选命令反推成模板。

        没自定义模板时（keymap 里 rumble_custom 为空）震动全靠下拉那条，
        这时扫出右柄可不能直接存个只有 small 的模板 —— 左柄会跟着失效。
        所以先把当前那条候选翻译成模板，再往里补新扫到的槽位。
        """
        name, ch, fn = betop.RUMBLE_FORMATS[idx]
        z, a, b = fn(0, 0), fn(255, 0), fn(0, 255)
        fixed, motor = [], {}
        for i in range(64):
            if z[i]:
                fixed.append((i, z[i]))
        for i in range(64):
            if z[i] == 0 and a[i] == 255:
                motor["big"] = i
            if z[i] == 0 and b[i] == 255:
                motor["small"] = i
        return {"chan": "set" if ch == 0 else "write",
                "fixed": fixed, "motor": motor}

    def _save(self, chan, head, off):
        which = self.which.get()
        key = self.app._motor_tpl_key(which)
        tpl = dict(self.app.km.get(key) or {})
        self._undo = (key, self.app.km.get(key))     # 存错了能退回去
        if not tpl and key == "rumble_custom":
            tpl = self._fmt_to_spec(self.app._fmt_index())
        # 存之前先让人核一遍：扫的时候很容易把别的马达的震动当成目标马达
        name = dict(self.MOTORS).get(which, which)
        old_off = betop._norm_motor(tpl.get("motor")).get(which)
        msg = (f"要把「{name}」的强度写在第 {off} 字节"
               f"（命令头 0x{head:02X}，"
               f"{'SET_REPORT' if chan == 'set' else 'WriteFile'}）")
        if old_off is not None and old_off != off:
            msg += f"\n这个马达原来记的是第 {old_off} 字节，会被改掉"
        msg += ("\n\n确定刚才是【这个马达】在震，不是别的马达？\n"
                "拿不准就点「否」，继续扫下一条。")
        if not messagebox.askyesno("确认保存这条命令", msg, parent=self.win):
            self.prog.config(text="没保存，继续扫下一条")
            return
        old_head = None
        for o, v in tpl.get("fixed") or []:
            if o == 1:
                old_head = v
        if old_head is not None and old_head != head and not messagebox.askyesno(
                "命令头不一样",
                f"这条的命令头是 0x{head:02X}，但现在已经存的是 "
                f"0x{old_head:02X}。\n换成新的可能让原来能震的马达失效，换吗？",
                parent=self.win):
            return
        tpl["chan"] = chan
        tpl["fixed"] = [[1, head]] + [f for f in (tpl.get("fixed") or [])
                                      if f[0] != 1]
        mot = tpl.get("motor")
        if isinstance(mot, list):
            d = {}
            if len(mot) > 0 and mot[0]:
                d["big"] = mot[0]
            if len(mot) > 1 and mot[1]:
                d["small"] = mot[1]
            mot = d
        mot = dict(mot or {})
        mot[which] = off
        tpl["motor"] = mot
        self.app.km[key] = tpl
        betop.save_keymap(self.app.km)
        rm = self.app.rumble
        if rm is not None:
            if which in ("tl", "tr"):
                rm.custom_trig = tpl
            else:
                rm.custom = tpl
        self.app._refresh_motor_btns()
        self.btn_undo.config(state="normal")
        name = dict(self.MOTORS).get(which, which)
        self.prog.config(text=f"存好了：{name} → 头 0x{head:02X} "
                              f"第 {off} 字节（不对就点「撤销上次」）")
        messagebox.showinfo("存好了",
                            f"「{name}」的命令：\n"
                            f"  命令头 0x{head:02X}，强度写在第 {off} 字节\n\n"
                            f"现在去主界面点那个马达的按钮就能单独震了。",
                            parent=self.win)


# 单实例判重用的锁文件（O_EXCL 原子创建：已存在=另一个实例在跑）。
# 文件里写首实例的 PID，第二个实例据此判断是"真在跑"还是"崩溃残留"。
import os as _os
_LOCK_DIR = _os.path.join(_os.environ.get("LOCALAPPDATA",
                          _os.environ.get("TEMP", "C:/tmp")), "BetopMapper")
_LOCK_PATH = _os.path.join(_LOCK_DIR, ".single_lock")
_INSTANCE_LOCK_FD = None


def _lock_owner_alive(path):
    """读锁文件里的 PID，判断持有者是否还活着。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            pid = int(f.read().strip())
    except Exception:
        return True          # 读不到 PID 就保守认为在跑（走激活分支）
    try:
        k = __import__("ctypes").windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        k.CloseHandle(h)
        return True
    except Exception:
        return True


def _kill_same_name_family():
    """把和自己同名的父/子（PyInstaller 的 bootloader 外壳）结束掉。
    只杀同名进程，绝不碰 explorer 之类的。"""
    import ctypes
    from ctypes import wintypes
    k = ctypes.windll.kernel32
    me = _os.getpid()
    mexe = _os.path.basename(sys.executable or "").lower()
    try:
        class PE32W(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.c_void_p),
                        ("th32ModuleID", wintypes.DWORD),
                        ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", ctypes.c_long),
                        ("dwFlags", wintypes.DWORD),
                        ("szExeFile", wintypes.WCHAR * 260)]

        k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PE32W)]
        k.Process32FirstW.restype = wintypes.BOOL
        k.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PE32W)]
        k.Process32NextW.restype = wintypes.BOOL
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.TerminateProcess.argtypes = [wintypes.HANDLE, ctypes.c_uint]
        k.TerminateProcess.restype = wintypes.BOOL

        info = {}
        snap = k.CreateToolhelp32Snapshot(0x00000002, 0)   # TH32CS_SNAPPROCESS
        if snap and int(snap) != -1:
            e = PE32W()
            e.dwSize = ctypes.sizeof(PE32W)
            ok = k.Process32FirstW(snap, ctypes.byref(e))
            while ok:
                info[e.th32ProcessID] = (e.th32ParentProcessID,
                                         (e.szExeFile or "").lower())
                ok = k.Process32NextW(snap, ctypes.byref(e))
            k.CloseHandle(snap)

        targets = []
        ppid = info.get(me, (0, ""))[0]
        if ppid and ppid != me and info.get(ppid, (0, ""))[1] == mexe:
            targets.append(ppid)
        for pid, (p, nm) in info.items():
            if p == me and pid != me and nm == mexe:
                targets.append(pid)
        for t in targets:
            h = k.OpenProcess(0x0001, False, t)     # PROCESS_TERMINATE
            if h:
                k.TerminateProcess(h, 0)
                k.CloseHandle(h)
    except Exception:
        pass


_MEI_GARBAGE = _os.path.join(_LOCK_DIR, ".mei_garbage")
# 第二实例盖个时间戳，第一实例看到变了就把窗口拉回前台
_ACT_REQ = _os.path.join(_LOCK_DIR, ".activate")


def _queue_mei_cleanup():
    """第二实例：把自己那份临时目录记进清单，交给还在跑的那个实例删。

    onefile 每次启动都往 %TEMP% 解压一份（本程序约 42MB），正常由 bootloader
    退出时回收；第二实例的 bootloader 是我们要结束掉的，不会自己收尾，所以把
    路径记下来让别人代删——自己没法删（文件还被自己占着），派脱机 cmd 在本机
    实测会被一起清掉，也不靠谱。"""
    try:
        d = getattr(sys, "_MEIPASS", None)
        if not d or not _os.path.isdir(d):
            return
        with open(_MEI_GARBAGE, "a", encoding="utf-8") as f:
            f.write(d + "\n")
    except Exception:
        pass


def _periodic_mei_sweep(root):
    """主线程里定时扫一遍临时目录垃圾清单（每 30 秒一次）。
    不放后台线程里做——Tk 的 after 跨线程调不一定生效。"""
    try:
        _sweep_mei_garbage()
    except Exception:
        pass
    try:
        root.after(30000, lambda: _periodic_mei_sweep(root))
    except Exception:
        pass


def _sweep_mei_garbage():
    """第一实例：把清单里的临时目录删掉（它们的主人已经退出了）。"""
    try:
        if not _os.path.exists(_MEI_GARBAGE):
            return
        import shutil
        mine = _os.path.normcase(getattr(sys, "_MEIPASS", "") or "")
        with open(_MEI_GARBAGE, "r", encoding="utf-8") as f:
            paths = [x.strip() for x in f if x.strip()]
        left = []
        for p in paths:
            if _os.path.normcase(p) == mine:      # 别删自己正在用的
                continue
            try:
                shutil.rmtree(p, ignore_errors=True)
            except Exception:
                pass
            if _os.path.isdir(p):
                left.append(p)                     # 还被占着，下次再试
        if left:
            with open(_MEI_GARBAGE, "w", encoding="utf-8") as f:
                f.write("\n".join(left) + "\n")
        else:
            _os.remove(_MEI_GARBAGE)
    except Exception:
        pass


def _exit_second_instance():
    """第二个实例收尾：把外壳一起带走，别留下僵尸进程。

    PyInstaller onefile 的 exe 跑起来是两个进程——真程序在子进程里，父进程只是
    bootloader 外壳。子进程用 os._exit() 硬退的话外壳**不会**跟着走，会永远
    留在进程列表里（看着就像又开了一个实例，还白占一份 42MB 的临时目录）。
    这里先把同名的外壳进程结束掉，把自己那份临时目录记进清单让第一个实例代删，
    再优雅退出；万一优雅退出被卡住，6 秒后看门狗强杀自己兜底。"""
    try:
        _kill_same_name_family()
    except Exception:
        pass
    try:
        _queue_mei_cleanup()
    except Exception:
        pass
    try:
        import ctypes as _c
        import threading as _t

        def _watchdog():
            try:
                time.sleep(6.0)
                _c.windll.kernel32.TerminateProcess(
                    _c.windll.kernel32.GetCurrentProcess(), 0)
            except Exception:
                pass
        _t.Thread(target=_watchdog, daemon=True).start()
    except Exception:
        pass
    sys.exit(0)


def _activate_existing(evname):
    """已有实例在跑：用命名事件把它拉回前台（不行再按标题兜底），
    然后自己强制退出，绝不新开窗口/托盘。"""
    import ctypes
    from ctypes import wintypes
    k = ctypes.windll.kernel32
    u = ctypes.windll.user32
    k.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k.OpenEventW.restype = wintypes.HANDLE
    k.SetEvent.argtypes = [wintypes.HANDLE]
    k.SetEvent.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL
    u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    u.FindWindowW.restype = wintypes.HWND
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.ShowWindow.restype = wintypes.BOOL
    u.SetForegroundWindow.argtypes = [wintypes.HWND]
    u.SetForegroundWindow.restype = wintypes.BOOL
    # 先把"把我拉回前台"的请求落盘——越早越好，后面哪怕中途被打断也生效
    try:
        with open(_ACT_REQ, "w", encoding="utf-8") as f:
            f.write("%.6f" % time.time())
    except Exception:
        pass
    # 首个实例可能还没建好激活事件：重试一小段，再按标题兜底翻窗
    for _ in range(15):   # 约 1.5s
        eh = k.OpenEventW(0x1F0000, False, evname)   # EVENT_ALL_ACCESS
        if eh:
            k.SetEvent(eh)
            k.CloseHandle(eh)
            _exit_second_instance()
        time.sleep(0.1)
    # 事件没接住（旧版本实例在跑）：直接按标题把窗口翻前台
    hwnd = u.FindWindowW(None, "北通游戏厅 · 手柄映射器")
    if hwnd:
        u.ShowWindow(hwnd, 9)              # SW_RESTORE
        u.SetForegroundWindow(hwnd)
    _exit_second_instance()


def _single_instance():
    """单实例：已经在跑就把旧窗口翻到前台，自己退掉。
    免得用户每次双击都新开一个进程——多个实例同时读手柄、同时建虚拟
    Xbox 手柄，游戏里会出现双重输入。
    判重用「锁文件 O_EXCL 原子创建」：谁先创建谁就是首实例，第二个实例
    创建必失败（不依赖启动快慢、也不读 ctypes last-error，冻结 exe 里
    GetLastError 会误报，导致每次点桌面都多开一个）。文件里记 PID，崩溃
    残留的死锁会被新实例识别并清掉。任何一步异常都放行（宁可多开一个，
    也不能打不开）。"""
    try:
        evname = "BetopXboxMapper_Activate_%s" % updater.APP_VERSION
        try:
            _os.makedirs(_LOCK_DIR, exist_ok=True)
        except Exception:
            pass
        try:
            fd = _os.open(_LOCK_PATH,
                          _os.O_CREAT | _os.O_EXCL | _os.O_RDWR)
        except FileExistsError:
            # 锁已存在：看持有者是否真在跑
            if _lock_owner_alive(_LOCK_PATH):
                _activate_existing(evname)   # 内部直接结束本进程
            # 崩溃残留：清掉重抢
            try:
                _os.remove(_LOCK_PATH)
            except Exception:
                pass
            try:
                fd = _os.open(_LOCK_PATH,
                              _os.O_CREAT | _os.O_EXCL | _os.O_RDWR)
            except FileExistsError:
                return          # 极端情况抢不到，放行（不卡死）
        # 我是首实例：写 PID 并持有 fd（进程退出自动关，文件靠 PID 判活）
        try:
            _os.write(fd, str(_os.getpid()).encode("utf-8"))
        except Exception:
            pass
        global _INSTANCE_LOCK_FD
        _INSTANCE_LOCK_FD = fd
        return
    except SystemExit:
        raise
    except Exception:
        return


def _release_instance_lock():
    """正常退出时删掉锁文件，下次启动直接拿到（不用靠 PID 判活）。"""
    global _INSTANCE_LOCK_FD
    try:
        if _INSTANCE_LOCK_FD is not None:
            try:
                _os.close(_INSTANCE_LOCK_FD)
            except Exception:
                pass
            _INSTANCE_LOCK_FD = None
    except Exception:
        pass
    try:
        _os.remove(_LOCK_PATH)
    except Exception:
        pass


def _install_activate(app):
    """首个实例建一个命名事件 + 后台线程等待；收到 SetEvent 就把自己的
    窗口拉到前台（deiconify+lift+focus，托盘态也能拉回）。"""
    try:
        import ctypes
        import threading
        from ctypes import wintypes
        k = ctypes.windll.kernel32
        evname = "BetopXboxMapper_Activate_%s" % updater.APP_VERSION
        k.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL,
                                   wintypes.BOOL, wintypes.LPCWSTR]
        k.CreateEventW.restype = wintypes.HANDLE
        k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k.WaitForSingleObject.restype = wintypes.DWORD
        eh = k.CreateEventW(None, False, False, evname)   # 自动复位
        if not eh:
            return

        k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k.WaitForSingleObject.restype = wintypes.DWORD

        # 拉窗口这件事**绝对不能**走 root.after：
        # ① 跨线程调 Tk 不安全；② 就算在主线程里轮询，实测 Tk 的定时器跑两轮
        # 就停摆（本程序界面重、定时器被挤掉）。所以这里用后台线程 + 纯 Win32
        # 调用（ShowWindow/SetForegroundWindow），完全不碰 Tk，稳。
        u = ctypes.windll.user32
        u.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
        u.GetAncestor.restype = wintypes.HWND
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u.ShowWindow.restype = wintypes.BOOL
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.SetForegroundWindow.restype = wintypes.BOOL
        try:
            hwnd = u.GetAncestor(wintypes.HWND(int(app.root.winfo_id())), 2)
        except Exception:
            hwnd = None

        def _bring_up(tag):
            try:
                if hwnd:
                    u.ShowWindow(hwnd, 9)          # SW_RESTORE（托盘态也拉回）
                    u.SetForegroundWindow(hwnd)
            except Exception:
                pass
            try:
                app.show_window()                  # 顺手让 Tk 状态也同步
            except Exception:
                pass
            try:
                _sweep_mei_garbage()               # 帮第二个实例收临时目录
            except Exception:
                pass

        _seen = [0.0]
        try:
            if _os.path.exists(_ACT_REQ):
                _seen[0] = _os.path.getmtime(_ACT_REQ)
        except Exception:
            pass

        _tick = [0]

        def _waiter():
            while True:
                try:
                    if k.WaitForSingleObject(eh, 200) == 0:
                        _bring_up("event")
                    try:
                        mt = _os.path.getmtime(_ACT_REQ)
                        if mt > _seen[0] + 0.001:
                            _seen[0] = mt
                            _bring_up("file")
                    except Exception:
                        pass
                    # 每 20 秒扫一次临时目录垃圾（纯文件操作，放线程里最稳，
                    # 交给 Tk 定时器实测会被挤掉）
                    _tick[0] += 1
                    if _tick[0] % 100 == 0:
                        try:
                            _sweep_mei_garbage()
                        except Exception:
                            pass
                except Exception:
                    try:
                        time.sleep(0.2)
                    except Exception:
                        return

        t = threading.Thread(target=_waiter, daemon=True)
        t.start()
        app._activate_event = eh
        # 顺手把上次崩溃/被强杀留下的临时目录清掉
        try:
            app.root.after(3000, _sweep_mei_garbage)
        except Exception:
            pass
    except Exception:
        pass



def main():
    # 高分屏：必须在建窗口前声明 DPI 感知，否则 Tk 按 96 DPI 初始化，
    # 150% 缩放的屏上字只有正常 2/3 大（padui 导入时也设过一次，这里双保险）
    try:
        padui.enable_dpi()
    except Exception:
        pass
    # 用户手动界面大小（倍率，0/缺省=跟随系统 DPI），键位文件里存着
    try:
        _mult = betop.load_keymap().get("ui_scale")
        if _mult:
            padui.apply_user_scale(_mult)
    except Exception:
        pass
    _single_instance()
    root = tk.Tk()
    app = App(root)
    _install_activate(app)          # 单实例激活：第二个实例靠它把本窗口拉回前台
    try:
        root.after(5000, lambda: _periodic_mei_sweep(root))
    except Exception:
        pass

    # App.__init__ 里已经挂过了；这里再挂一次防止被覆盖。
    # 关窗口 = 藏到托盘（没托盘就直接退），真退走 app.quit_app()：
    # 停娱乐模式 / 停闹钟 / 马达归零 / 撤托盘，一样都不会漏
    root.protocol("WM_DELETE_WINDOW", app.on_close_request)
    root.mainloop()


if __name__ == "__main__":
    main()
