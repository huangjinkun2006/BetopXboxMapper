"""图形化新手教程（主程序左侧「📖 新手教程」）。

这把手柄不是 XInput，游戏认不到，所以中间要挂一层 ViGEm 虚拟手柄。
流程对第一次用的人来说不直观，这里按 1→6 步把每一步画出来，
能点的按钮直接跳到对应功能，驱动和手柄有没有接好也能当场检测。
"""
import math
import threading
import tkinter as tk
from tkinter import messagebox

import betop
import hidraw
from padui import PadView, round_rect

FONT = "Microsoft YaHei UI"
C_BG = "#f5f6f8"
C_CARD = "white"
C_LINE = "#dfe1e6"
C_SUB = "#79808e"
C_OK = "#0f9d58"
C_BLUE = "#1a73e8"
C_RED = "#c0392b"

W, H = 560, 370

STEPS = [
    ("① 装 ViGEmBus 驱动", [
        "程序干的事是：在系统里伪造一个 Xbox 360 手柄，游戏晃它，我们再把动作翻译给你的北通。",
        "这个「伪造」靠 ViGEmBus 驱动，没装的话点「启动映射」会直接报错。",
        "绿色版目录里有 ViGEmBus_Setup.exe，双击装一遍，装完重启一次电脑最稳。",
    ]),
    ("② 插上手柄", [
        "用 USB 线连电脑（这把不支持当 XInput 蓝牙手柄用）。连上后手柄灯会亮。",
        "程序只认 VID 20BC 的北通手柄，插上点一下「重新检测」，能看到 PID 就说明认到了。",
        "设备管理器里它叫「HID-compliant game controller」，这是正常的，别去改它。",
    ]),
    ("③ 跑一次键位识别向导", [
        "同样型号的手柄按键顺序也可能不一样，所以要先认一次键。",
        "打开向导后照提示一个个按键就行，大约十秒一个，结果存进 keymap.json。",
        "左边这张图会循环点亮各个键，就是向导里要你按的那些。",
    ]),
    ("④ 回主界面启动映射", [
        "点「启动映射」，状态变成「运行中」，此时系统里就多出一个 Xbox 360 手柄。",
        "中间那张手柄图会随着你按的手柄实时亮键，可以顺手验一遍键位对不对。",
        "不用了就点「停止映射」，虚拟手柄会被撤掉。",
    ]),
    ("⑤ 进游戏里选控制器", [
        "以基岩版 Minecraft 为例：设置 → 控制器 → 设备选「Xbox 360 手柄」，就能用了。",
        "凡是只认 XInput 的游戏（大多数手柄游戏）现在都能认到它。",
        "要是游戏里没反应：先关掉游戏再启动映射，然后重开游戏，顺序反了认不到。",
    ]),
    ("⑥ 调震动", [
        "右侧「震动强度」滑块最高能拉到 300%，嫌震得轻就往上拉。",
        "完全不震：先看界面上那行「游戏震动 → 大马达 xx」，有数字说明游戏发过来了。",
        "还是不行就进「🧪 震动实验室」扫一遍命令，让程序自己找出这把能震的那条。",
    ]),
]


class Guide(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.i = 0
        self.pad = None
        self._anim = None
        self.title("新手教程 · 六步把北通变成 Xbox 手柄")
        self.geometry("820x680")
        self.configure(bg=C_BG)
        self.transient(app.root)

        head = tk.Frame(self, bg=C_BG)
        head.pack(fill="x", padx=20, pady=(14, 6))
        tk.Label(head, text="新手教程", font=(FONT, 15, "bold"),
                 bg=C_BG).pack(anchor="w")
        tk.Label(head, text="按顺序走一遍就能玩上；左边点哪步看哪步",
                 font=(FONT, 9), fg=C_SUB, bg=C_BG).pack(anchor="w", pady=(2, 0))

        body = tk.Frame(self, bg=C_BG)
        body.pack(fill="both", expand=True, padx=20)

        left = tk.Frame(body, bg=C_BG)
        left.pack(side="left", fill="y")
        self.lst = tk.Listbox(left, font=(FONT, 10), height=8, width=22,
                              relief="flat", bg="white",
                              highlightthickness=1,
                              highlightbackground=C_LINE,
                              selectbackground=C_BLUE,
                              selectforeground="white")
        for t, _b in STEPS:
            self.lst.insert("end", t)
        self.lst.pack(fill="y")
        self.lst.select_set(0)
        self.lst.bind("<<ListboxSelect>>", self.on_pick)

        right = tk.Frame(body, bg=C_BG)
        right.pack(side="left", fill="both", expand=True, padx=(14, 0))

        box = tk.Frame(right, bg=C_CARD, highlightthickness=1,
                       highlightbackground=C_LINE)
        box.pack()
        self.cv = tk.Canvas(box, width=W, height=H, bg=C_CARD,
                            highlightthickness=0)
        self.cv.pack()

        self.title_lbl = tk.Label(right, text="", font=(FONT, 12, "bold"),
                                  bg=C_BG)
        self.title_lbl.pack(anchor="w", pady=(10, 2))
        self.text_lbl = tk.Label(right, text="", font=(FONT, 10), fg="#444",
                                 bg=C_BG, justify="left", wraplength=W)
        self.text_lbl.pack(anchor="w")
        self.res_lbl = tk.Label(right, text="", font=(FONT, 9), fg=C_SUB,
                                bg=C_BG, justify="left", wraplength=W)
        self.res_lbl.pack(anchor="w", pady=(6, 0))

        bar = tk.Frame(right, bg=C_BG)
        bar.pack(fill="x", pady=(10, 0))
        self.act = tk.Button(bar, text="", font=(FONT, 9, "bold"), fg="white",
                             bg=C_OK, relief="flat", padx=10, pady=5,
                             cursor="hand2", command=self.on_action)
        self.act.pack(side="left")
        tk.Button(bar, text="← 上一步", font=(FONT, 9), relief="flat",
                  bg="white", padx=8, pady=5,
                  command=lambda: self.go(-1)).pack(side="right")
        tk.Button(bar, text="下一步 →", font=(FONT, 9), relief="flat",
                  bg="white", padx=8, pady=5,
                  command=lambda: self.go(1)).pack(side="right", padx=4)

        self.bind("<Left>", lambda e: self.go(-1))
        self.bind("<Right>", lambda e: self.go(1))
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.show()

    # ---------------------------------------------------------- 切换
    def on_pick(self, _e=None):
        sel = self.lst.curselection()
        if not sel:
            return
        self.i = sel[0]
        self.show()

    def go(self, d):
        self.i = max(0, min(len(STEPS) - 1, self.i + d))
        self.lst.select_clear(0, "end")
        self.lst.select_set(self.i)
        self.show()

    def show(self):
        t, lines = STEPS[self.i]
        self.title_lbl.config(text=t)
        self.text_lbl.config(text="\n".join("· " + s for s in lines))
        self.res_lbl.config(text="", fg=C_SUB)
        self.act.config(text=["检测驱动装好没", "重新检测手柄",
                              "打开键位向导", "回到主界面",
                              "知道了", "打开震动实验室"][self.i])
        self._draw()

    def _stop_anim(self):
        if self._anim is not None:
            try:
                self.after_cancel(self._anim)
            except Exception:
                pass
            self._anim = None

    def _draw(self):
        self._stop_anim()
        self.cv.delete("all")
        self.pad = None
        if self.i == 2:
            self.pad = PadView(self.cv)
            self._anim_keys()
        else:
            getattr(self, "_d%d" % self.i)()

    # ---------------------------------------------------------- 图示
    def _d0(self):
        cv = self.cv
        round_rect(cv, 150, 70, 410, 250, 12, fill="#eef1f5", outline="#cfd4dc")
        cv.create_rectangle(150, 70, 410, 100, fill="#dde3ea", outline="")
        for k, x in enumerate((166, 182, 198)):
            cv.create_oval(x, 80, x + 10, 90, fill="#c3cad4", outline="")
        cv.create_text(280, 85, text="ViGEmBus Setup", font=(FONT, 9),
                       fill="#5f6673")
        cv.create_polygon([280, 122, 328, 142, 328, 196, 280, 224, 232, 196,
                           232, 142], smooth=False, fill="#e6f1fb",
                          outline=C_BLUE, width=2)
        cv.create_line(262, 172, 276, 188, 302, 156, fill=C_OK, width=4,
                       capstyle="round", joinstyle="round")
        cv.create_text(280, 236, text="驱动装好后，系统里才能出现虚拟手柄",
                       font=(FONT, 9), fill=C_SUB)
        cv.create_line(280, 258, 280, 286, fill="#b9c0cb", width=2,
                       arrow="last")
        round_rect(cv, 176, 292, 384, 336, 8, fill="#eaf3de", outline=C_OK)
        cv.create_text(280, 314, text="Xbox 360 手柄（虚拟）",
                       font=(FONT, 10, "bold"), fill="#3B6D11")

    def _d1(self):
        cv = self.cv
        round_rect(cv, 60, 130, 210, 270, 10, fill="#eef1f5", outline="#cfd4dc")
        cv.create_rectangle(74, 144, 196, 244, fill="#2f343d", outline="")
        cv.create_text(135, 262, text="电脑", font=(FONT, 9), fill=C_SUB)
        cv.create_line(210, 232, 258, 240, 300, 214, smooth=True,
                       fill="#5f6673", width=3)
        cv.create_text(255, 258, text="USB", font=(FONT, 9), fill=C_SUB)
        round_rect(cv, 320, 176, 480, 246, 34, fill="#3f4551", outline="")
        cv.create_polygon([320, 200, 300, 268, 330, 292, 360, 262, 372, 214],
                          smooth=True, fill="#3f4551", outline="")
        cv.create_polygon([480, 200, 500, 268, 470, 292, 440, 262, 428, 214],
                          smooth=True, fill="#3f4551", outline="")
        cv.create_oval(348, 186, 380, 218, fill="#23272f", outline="")
        cv.create_oval(420, 202, 452, 234, fill="#23272f", outline="")
        cv.create_oval(392, 188, 408, 204, fill=C_OK, outline="")
        cv.create_text(400, 168, text="灯亮 = 连上了", font=(FONT, 9),
                       fill=C_OK)
        cv.create_text(400, 312, text="VID 20BC · 北通 BTP-V1T",
                       font=(FONT, 10, "bold"), fill="#444")
        cv.create_text(400, 332, text="设备管理器里显示成 HID 手柄是正常的",
                       font=(FONT, 9), fill=C_SUB)

    def _anim_keys(self):
        keys = ["A", "B", "X", "Y", "LB", "RB", "UP", "RIGHT", "DOWN",
                "LEFT", "LS", "RS", "LT", "RT"]

        def tick():
            if self.pad is None:
                return
            k = keys[self._ki % len(keys)]
            self.pad.highlight(k)
            self.pad.set_state({}, {k: 1.0} if k in ("LT", "RT") else {})
            self._ki += 1
            self._anim = self.after(650, tick)

        self._ki = 0
        tick()

    def _d3(self):
        cv = self.cv
        self._mini_pad(cv, 90, 118, 0.9)
        cv.create_text(112, 262, text="你的北通", font=(FONT, 9), fill=C_SUB)
        cv.create_line(190, 190, 246, 190, fill=C_BLUE, width=2, arrow="last")
        cv.create_text(218, 172, text="映射", font=(FONT, 9), fill=C_BLUE)
        round_rect(cv, 252, 150, 400, 232, 10, fill="#e6f1fb", outline=C_BLUE)
        cv.create_text(326, 178, text="Xbox 360 手柄", font=(FONT, 10, "bold"),
                       fill="#0C447C")
        cv.create_text(326, 200, text="（ViGEm 虚拟）", font=(FONT, 9),
                       fill=C_BLUE)
        cv.create_line(400, 190, 456, 190, fill=C_BLUE, width=2, arrow="last")
        round_rect(cv, 460, 150, 540, 232, 10, fill="#eaf3de", outline=C_OK)
        cv.create_text(500, 178, text="游戏", font=(FONT, 10, "bold"),
                       fill="#3B6D11")
        cv.create_text(500, 200, text="只认 XInput", font=(FONT, 9), fill=C_OK)
        cv.create_text(280, 300, text="游戏晃虚拟手柄 → 我们把它翻译成北通听得懂的命令",
                       font=(FONT, 10), fill="#444")
        cv.create_text(280, 324, text="反过来：你按北通 → 我们告诉虚拟手柄「A 被按下了」",
                       font=(FONT, 9), fill=C_SUB)

    def _d4(self):
        cv = self.cv
        round_rect(cv, 120, 70, 440, 300, 10, fill="#eef1f5", outline="#cfd4dc")
        cv.create_rectangle(120, 70, 440, 100, fill="#dde3ea", outline="")
        cv.create_text(280, 85, text="Minecraft 基岩版 · 设置",
                       font=(FONT, 9), fill="#5f6673")
        rows = [("控制器", True), ("设备：Xbox 360 手柄", True),
                ("按键映射：默认", False), ("震动：开", False)]
        for k, (txt, on) in enumerate(rows):
            y = 120 + k * 46
            round_rect(cv, 140, y, 420, y + 38, 8,
                       fill=("#e6f1fb" if on else "white"),
                       outline=(C_BLUE if on else C_LINE))
            cv.create_text(158, y + 19, text=txt, anchor="w",
                           font=(FONT, 10), fill=("#0C447C" if on else "#444"))
        cv.create_text(280, 330, text="顺序很重要：先启动映射，再开游戏",
                       font=(FONT, 10, "bold"), fill=C_RED)

    def _d5(self):
        cv = self.cv
        for k, (amp, col) in enumerate(((11, C_BLUE), (8, "#8e44ad"),
                                        (16, C_OK))):
            pts = []
            for x in range(120, 446, 4):
                y = 118 + k * 62 - amp * math.sin((x - 120) / 26.0)
                pts += [x, y]
            cv.create_line(pts, fill=col, width=2, smooth=True)
        cv.create_text(120, 250, text="震动强度", anchor="w", font=(FONT, 9),
                       fill=C_SUB)
        round_rect(cv, 120, 268, 440, 278, 5, fill="#dfe1e6", outline="")
        cv.create_oval(372, 262, 396, 286, fill=C_BLUE, outline="")
        cv.create_text(440, 274, text="300%", anchor="e", font=(FONT, 9),
                       fill=C_BLUE)
        cv.create_text(280, 312, text="滑块往上拉 = 把游戏里的轻微震动放大",
                       font=(FONT, 10), fill="#444")
        cv.create_text(280, 336, text="完全不震就去实验室扫命令",
                       font=(FONT, 9), fill=C_SUB)

    @staticmethod
    def _mini_pad(cv, x, y, s):
        """缩略手柄图（流程示意用）"""
        poly = []
        for px, py in ((0, 20), (-18, 74), (-26, 118), (0, 132),
                       (26, 118), (18, 74)):
            poly += [x + px * s, y + py * s]
        cv.create_polygon(poly, smooth=True, fill="#3f4551", outline="")
        round_rect(cv, x - 26 * s, y, x + 26 * s, y + 40 * s, 12 * s,
                   fill="#3f4551", outline="")
        cv.create_oval(x - 12 * s, y + 12 * s, x - 2 * s, y + 22 * s,
                       fill="#23272f", outline="")
        cv.create_oval(x + 2 * s, y + 18 * s, x + 12 * s, y + 28 * s,
                       fill="#23272f", outline="")

    # ---------------------------------------------------------- 动作
    def on_action(self):
        try:
            [self.check_driver, self.check_pad, self.open_wizard,
             self.go_main, self.none, self.open_lab][self.i]()
        except Exception as e:
            messagebox.showerror("出错了", str(e), parent=self)

    def none(self):
        self.res_lbl.config(text="这步没有要点的，直接进游戏试就行", fg=C_SUB)

    def go_main(self):
        self.app.root.lift()
        self.app.root.focus_force()
        self.res_lbl.config(text="主界面已置顶，点红色那个「启动映射」按钮",
                            fg=C_OK)

    def open_wizard(self):
        self.res_lbl.config(text="向导已打开，照提示按键就行", fg=C_OK)
        self.app.root.after(200, self.app.open_wizard)

    def open_lab(self):
        self.res_lbl.config(text="实验室已打开，点「🏆 最强对决」开始", fg=C_OK)
        self.app.root.after(200, self.app.open_lab)

    def check_driver(self):
        self.res_lbl.config(text="正在检测…", fg=C_SUB)

        def go():
            ok, msg = False, ""
            try:
                import vgamepad
                g = vgamepad.VX360Gamepad()
                try:
                    ok, msg = True, "ViGEmBus 已装好，可以创建虚拟手柄"
                finally:
                    del g
            except Exception as e:
                msg = f"没装好（{e}）\n去绿色版目录双击 ViGEmBus_Setup.exe 装一遍"
            self.after(0, lambda: self.res_lbl.config(
                text=msg, fg=(C_OK if ok else C_RED)))

        threading.Thread(target=go, daemon=True).start()

    def check_pad(self):
        try:
            rows = hidraw.list_devices(betop.VID)
        except Exception as e:
            self.res_lbl.config(text=f"枚举失败：{e}", fg=C_RED)
            return
        if not rows:
            self.res_lbl.config(
                text="没找到北通手柄（VID 20BC）。\n"
                     "换个 USB 口、换根线试试，线要能传数据不能只充电",
                fg=C_RED)
            return
        pids = sorted({f"{v:04X}:{p:04X}" for v, p, *_r in rows})
        n = len({r[5] for r in rows})
        self.res_lbl.config(
            text=f"找到了：{' / '.join(pids)}，共 {n} 个 HID 接口（正常是 3 个）",
            fg=C_OK)

    def on_close(self):
        self._stop_anim()
        self.destroy()
