"""图形化新手教程（主程序左侧「📖 新手教程」）。

这把手柄不是 XInput，游戏认不到，所以中间要挂一层 ViGEm 虚拟手柄。
流程对第一次用的人来说不直观，这里按 1→8 步把每一步画出来，
能点的按钮直接跳到对应功能，驱动和手柄有没有接好也能当场检测。
"""
import math
import threading
import tkinter as tk
from tkinter import messagebox

import betop
import hidraw
from padui import PadView, round_rect, apply_icon, FT, S, SCALE

FONT = "Microsoft YaHei UI"
C_BG = "#f5f6f8"
C_CARD = "white"
C_LINE = "#dfe1e6"
C_SUB = "#79808e"
C_OK = "#0f9d58"
C_BLUE = "#1a73e8"
C_RED = "#c0392b"

W, H = S(560), S(370)

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
    ("⑤ 按键不对？直接改键", [
        "启动映射后按手柄，中间那张图会跟着亮。亮的键跟你实际按的对不上？不用重新跑向导。",
        "主界面右下角有「改键（先启动映射）」：点键名旁边的红色「改」，再按下手柄上你想当这个键用的实体键就绑好了。",
        "摇杆上下反了：轴旁边有「反向」，点一下就翻过来。所有改动保存在 keymap.json，下次打开还是这套。",
    ]),
    ("⑥ 进游戏里选控制器", [
        "以基岩版 Minecraft 为例：设置 → 控制器 → 设备选「Xbox 360 手柄」，就能用了。",
        "凡是只认 XInput 的游戏（大多数手柄游戏）现在都能认到它。",
        "要是游戏里没反应：先关掉游戏再启动映射，然后重开游戏，顺序反了认不到。",
    ]),
    ("⑦ 调震动", [
        "右侧「震动强度」滑块最高能拉到 300%，嫌震得轻就往上拉。",
        "完全不震：先看界面上那行「游戏震动 → 大马达 xx」，有数字说明游戏发过来了。",
        "还是不行就进「🧪 震动实验室」扫一遍命令，让程序自己找出这把能震的那条。",
    ]),
    ("⑧ 手机来消息，手柄就震", [
        "左侧「📱 手机通知」：手机上来了微信、QQ、短信，手柄就震一下，打游戏不用看手机。",
        "开法：勾「开启」前先点「放行防火墙」（弹 UAC 点「是」），然后记下界面上显示的地址，形如 http://192.168.1.13:9595 。",
        "先手动验一次：手机连同一个 WiFi，浏览器打开那个地址，点页面上的「震一下」，手柄震就说明通了。",
        "要自动触发：安卓装 MacroDroid，触发器选「通知收到」，动作选「HTTP 请求」GET，URL 填那个地址加 /notify 。",
        "苹果不行：iOS 快捷指令没有「收到通知」触发器，只有短信/邮件能自动化，或者就用那个网页按钮手动点。",
        "连不上按顺序查：防火墙放行 → 手机电脑同一个 WiFi（访客网络不行）→ 别选 127.0.0.1 和虚拟网卡的 IP。",
    ]),
]


class Guide(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.i = 0
        self.pad = None
        self._anim = None
        self.title("新手教程 · 八步把北通变成 Xbox 手柄")
        self.geometry("%dx%d" % (S(820), S(740)))
        self.configure(bg=C_BG)
        apply_icon(self)
        self.transient(app.root)

        head = tk.Frame(self, bg=C_BG)
        head.pack(fill="x", padx=S(20), pady=(S(14), S(6)))
        tk.Label(head, text="新手教程", font=FT(15, "bold"),
                 bg=C_BG).pack(anchor="w")
        tk.Label(head, text="按顺序走一遍就能玩上；左边点哪步看哪步",
                 font=FT(9), fg=C_SUB, bg=C_BG).pack(anchor="w", pady=(S(2), S(0)))

        body = tk.Frame(self, bg=C_BG)
        body.pack(fill="both", expand=True, padx=S(20))

        left = tk.Frame(body, bg=C_BG)
        left.pack(side="left", fill="y")
        self.lst = tk.Listbox(left, font=FT(10), height=9, width=22,
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

        # 文字区放可滚动容器里，步骤多了超窗也不截断
        scf = tk.Frame(right, bg=C_BG)
        scf.pack(fill="both", expand=True)
        self.scv = tk.Canvas(scf, bg=C_BG, highlightthickness=0)
        vsb = tk.Scrollbar(scf, orient="vertical", command=self.scv.yview)
        self.scv.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.scv.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(self.scv, bg=C_BG)
        self._scw = self.scv.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda _e:
                   self.scv.configure(scrollregion=self.scv.bbox("all")))
        self.scv.bind("<Configure>", lambda e:
                      self.scv.itemconfigure(self._scw, width=e.width))

        self.title_lbl = tk.Label(inner, text="", font=FT(12, "bold"),
                                  bg=C_BG)
        self.title_lbl.pack(anchor="w", pady=(S(10), S(2)))
        self.text_lbl = tk.Label(inner, text="", font=FT(10), fg="#444",
                                 bg=C_BG, justify="left", wraplength=W)
        self.text_lbl.pack(anchor="w")
        self.res_lbl = tk.Label(inner, text="", font=FT(9), fg=C_SUB,
                                bg=C_BG, justify="left", wraplength=W)
        self.res_lbl.pack(anchor="w", pady=(S(6), S(0)))

        bar = tk.Frame(right, bg=C_BG)
        bar.pack(fill="x", pady=(S(10), S(0)))
        self.act = tk.Button(bar, text="", font=FT(9, "bold"), fg="white",
                             bg=C_OK, relief="flat", padx=S(10), pady=S(5),
                             cursor="hand2", command=self.on_action)
        self.act.pack(side="left")
        tk.Button(bar, text="← 上一步", font=FT(9), relief="flat",
                  bg="white", padx=S(8), pady=S(5),
                  command=lambda: self.go(-1)).pack(side="right")
        tk.Button(bar, text="下一步 →", font=FT(9), relief="flat",
                  bg="white", padx=S(8), pady=S(5),
                  command=lambda: self.go(1)).pack(side="right", padx=S(4))

        self.bind("<Left>", lambda e: self.go(-1))
        self.bind("<Right>", lambda e: self.go(1))
        self.bind("<MouseWheel>", self._on_wheel)
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
                              "去主界面改键",
                              "知道了", "打开震动实验室",
                              "打开手机通知"][self.i])
        self._draw()
        self.after(30, lambda: self.scv.yview_moveto(0))

    def _on_wheel(self, e):
        """鼠标滚轮滚动文字区（没得滚时不吃事件）"""
        try:
            if self.scv.yview() == (0.0, 1.0):
                return
            self.scv.yview_scroll(-1 if e.delta > 0 else 1, "units")
        except tk.TclError:
            pass

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
            if SCALE != 1.0:
                # 手画图示的坐标是 96 DPI 下写的，整组放大到当前 DPI
                self.cv.scale("all", 0, 0, SCALE, SCALE)

    # ---------------------------------------------------------- 图示
    def _d0(self):
        cv = self.cv
        round_rect(cv, 150, 70, 410, 250, 12, fill="#eef1f5", outline="#cfd4dc")
        cv.create_rectangle(150, 70, 410, 100, fill="#dde3ea", outline="")
        for k, x in enumerate((166, 182, 198)):
            cv.create_oval(x, 80, x + 10, 90, fill="#c3cad4", outline="")
        cv.create_text(280, 85, text="ViGEmBus Setup", font=FT(9),
                       fill="#5f6673")
        cv.create_polygon([280, 122, 328, 142, 328, 196, 280, 224, 232, 196,
                           232, 142], smooth=False, fill="#e6f1fb",
                          outline=C_BLUE, width=2)
        cv.create_line(262, 172, 276, 188, 302, 156, fill=C_OK, width=4,
                       capstyle="round", joinstyle="round")
        cv.create_text(280, 236, text="驱动装好后，系统里才能出现虚拟手柄",
                       font=FT(9), fill=C_SUB)
        cv.create_line(280, 258, 280, 286, fill="#b9c0cb", width=2,
                       arrow="last")
        round_rect(cv, 176, 292, 384, 336, 8, fill="#eaf3de", outline=C_OK)
        cv.create_text(280, 314, text="Xbox 360 手柄（虚拟）",
                       font=FT(10, "bold"), fill="#3B6D11")

    def _d1(self):
        cv = self.cv
        round_rect(cv, 60, 130, 210, 270, 10, fill="#eef1f5", outline="#cfd4dc")
        cv.create_rectangle(74, 144, 196, 244, fill="#2f343d", outline="")
        cv.create_text(135, 262, text="电脑", font=FT(9), fill=C_SUB)
        cv.create_line(210, 232, 258, 240, 300, 214, smooth=True,
                       fill="#5f6673", width=3)
        cv.create_text(255, 258, text="USB", font=FT(9), fill=C_SUB)
        round_rect(cv, 320, 176, 480, 246, 34, fill="#3f4551", outline="")
        cv.create_polygon([320, 200, 300, 268, 330, 292, 360, 262, 372, 214],
                          smooth=True, fill="#3f4551", outline="")
        cv.create_polygon([480, 200, 500, 268, 470, 292, 440, 262, 428, 214],
                          smooth=True, fill="#3f4551", outline="")
        cv.create_oval(348, 186, 380, 218, fill="#23272f", outline="")
        cv.create_oval(420, 202, 452, 234, fill="#23272f", outline="")
        cv.create_oval(392, 188, 408, 204, fill=C_OK, outline="")
        cv.create_text(400, 168, text="灯亮 = 连上了", font=FT(9),
                       fill=C_OK)
        cv.create_text(400, 312, text="VID 20BC · 北通 BTP-V1T",
                       font=FT(10, "bold"), fill="#444")
        cv.create_text(400, 332, text="设备管理器里显示成 HID 手柄是正常的",
                       font=FT(9), fill=C_SUB)

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
        cv.create_text(112, 262, text="你的北通", font=FT(9), fill=C_SUB)
        cv.create_line(190, 190, 246, 190, fill=C_BLUE, width=2, arrow="last")
        cv.create_text(218, 172, text="映射", font=FT(9), fill=C_BLUE)
        round_rect(cv, 252, 150, 400, 232, 10, fill="#e6f1fb", outline=C_BLUE)
        cv.create_text(326, 178, text="Xbox 360 手柄", font=FT(10, "bold"),
                       fill="#0C447C")
        cv.create_text(326, 200, text="（ViGEm 虚拟）", font=FT(9),
                       fill=C_BLUE)
        cv.create_line(400, 190, 456, 190, fill=C_BLUE, width=2, arrow="last")
        round_rect(cv, 460, 150, 540, 232, 10, fill="#eaf3de", outline=C_OK)
        cv.create_text(500, 178, text="游戏", font=FT(10, "bold"),
                       fill="#3B6D11")
        cv.create_text(500, 200, text="只认 XInput", font=FT(9), fill=C_OK)
        cv.create_text(280, 300, text="游戏晃虚拟手柄 → 我们把它翻译成北通听得懂的命令",
                       font=FT(10), fill="#444")
        cv.create_text(280, 324, text="反过来：你按北通 → 我们告诉虚拟手柄「A 被按下了」",
                       font=FT(9), fill=C_SUB)

    def _d4(self):
        """改键面板示意（对照主界面右下角那块）"""
        cv = self.cv
        # 面板卡片
        round_rect(cv, 168, 44, 392, 268, 10, fill="#f7f8fa", outline="#cfd4dc")
        cv.create_text(280, 64, text="改键（先启动映射）",
                       font=FT(10, "bold"), fill="#33373f")
        cv.create_line(182, 80, 378, 80, fill="#e2e5ea", width=1)
        # 两列键名 chip，BACK 那个高亮
        names = ["Y", "X", "B", "A", "LB", "RB", "BACK", "START", "L3", "R3"]
        for i, nm in enumerate(names):
            col, row = i % 2, i // 2
            x1, y1 = 186 + col * 100, 92 + row * 28
            x2, y2 = x1 + 90, y1 + 22
            hot = nm == "BACK"
            round_rect(cv, x1, y1, x2, y2, 5,
                       fill=("#e6f1fb" if hot else "#f1f2f5"),
                       outline=(C_BLUE if hot else "#dcdfe5"))
            cv.create_text(x1 + 18, y1 + 11, text=nm, anchor="w",
                           font=FT(9, "bold", family="Consolas"),
                           fill=("#0C447C" if hot else "#5a5e66"))
            cv.create_text(x2 - 18, y1 + 11, text="改",
                           font=FT(9), fill=(C_BLUE if hot else C_RED))
        cv.create_text(280, 246, text="…（LOGO 同样能改）",
                       font=FT(8), fill=C_SUB)
        # 箭头解释
        cv.create_line(118, 186, 182, 178, fill=C_BLUE, width=2, arrow="last")
        cv.create_text(96, 200, text="点「改」", font=FT(9), fill=C_BLUE)
        cv.create_line(378, 186, 428, 176, fill=C_BLUE, width=2, arrow="last")
        cv.create_text(444, 168, text="再按手柄上\n想当它用的键",
                       font=FT(9), fill=C_BLUE, justify="left")
        cv.create_text(280, 298, text="按了 A 亮成别的键 / 手柄键位跟别人不一样，都用这里改",
                       font=FT(10), fill="#444")
        # 底部：摇杆反向提示条
        round_rect(cv, 120, 318, 440, 350, 8, fill="#fdf3e7", outline="#e8a54b")
        cv.create_text(280, 334, text="摇杆上下反了？轴旁边的「反向」点一下就翻过来",
                       font=FT(9), fill="#8a5a13")

    def _d5(self):
        cv = self.cv
        round_rect(cv, 120, 70, 440, 300, 10, fill="#eef1f5", outline="#cfd4dc")
        cv.create_rectangle(120, 70, 440, 100, fill="#dde3ea", outline="")
        cv.create_text(280, 85, text="Minecraft 基岩版 · 设置",
                       font=FT(9), fill="#5f6673")
        rows = [("控制器", True), ("设备：Xbox 360 手柄", True),
                ("按键映射：默认", False), ("震动：开", False)]
        for k, (txt, on) in enumerate(rows):
            y = 120 + k * 46
            round_rect(cv, 140, y, 420, y + 38, 8,
                       fill=("#e6f1fb" if on else "white"),
                       outline=(C_BLUE if on else C_LINE))
            cv.create_text(158, y + 19, text=txt, anchor="w",
                           font=FT(10), fill=("#0C447C" if on else "#444"))
        cv.create_text(280, 330, text="顺序很重要：先启动映射，再开游戏",
                       font=FT(10, "bold"), fill=C_RED)

    def _d6(self):
        cv = self.cv
        for k, (amp, col) in enumerate(((11, C_BLUE), (8, "#8e44ad"),
                                        (16, C_OK))):
            pts = []
            for x in range(120, 446, 4):
                y = 118 + k * 62 - amp * math.sin((x - 120) / 26.0)
                pts += [x, y]
            cv.create_line(pts, fill=col, width=2, smooth=True)
        cv.create_text(120, 250, text="震动强度", anchor="w", font=FT(9),
                       fill=C_SUB)
        round_rect(cv, 120, 268, 440, 278, 5, fill="#dfe1e6", outline="")
        cv.create_oval(372, 262, 396, 286, fill=C_BLUE, outline="")
        cv.create_text(440, 274, text="300%", anchor="e", font=FT(9),
                       fill=C_BLUE)
        cv.create_text(280, 312, text="滑块往上拉 = 把游戏里的轻微震动放大",
                       font=FT(10), fill="#444")
        cv.create_text(280, 336, text="完全不震就去实验室扫命令",
                       font=FT(9), fill=C_SUB)

    def _d7(self):
        """手机 → 局域网 → 电脑 → 手柄震一下"""
        cv = self.cv
        # 手机
        round_rect(cv, 62, 92, 152, 268, 12, fill="#eef1f5", outline="#cfd4dc")
        round_rect(cv, 70, 100, 144, 260, 6, fill="white", outline="")
        round_rect(cv, 76, 118, 138, 172, 8, fill="#e6f1fb", outline=C_BLUE)
        cv.create_text(84, 128, text="微信", anchor="w", font=FT(9),
                       fill="#0C447C")
        cv.create_text(84, 148, text="有新消息", anchor="w", font=FT(9),
                       fill="#444")
        cv.create_text(107, 292, text="手机来通知", font=FT(9), fill=C_SUB)
        # 请求
        cv.create_line(158, 175, 192, 175, arrow="last", fill=C_SUB, width=1.5)
        cv.create_text(175, 160, text="/notify", font=FT(9), fill=C_SUB)
        # 电脑
        round_rect(cv, 200, 108, 372, 226, 8, fill="#eef1f5", outline="#cfd4dc")
        round_rect(cv, 208, 116, 364, 208, 4, fill="white", outline="")
        cv.create_text(286, 146, text="映射器 · 端口 9595", font=FT(10),
                       fill="#5f6673")
        cv.create_text(286, 176, text="http://192.168.1.13:9595",
                       font=FT(9), fill=C_BLUE)
        cv.create_polygon([266, 226, 306, 226, 316, 246, 256, 246],
                          fill="#dde3ea", outline="")
        round_rect(cv, 236, 246, 336, 254, 3, fill="#cfd4dc", outline="")
        cv.create_text(286, 292, text="电脑收到请求", font=FT(9), fill=C_SUB)
        # 手柄 + 震动波
        cv.create_line(378, 175, 412, 175, arrow="last", fill=C_SUB, width=1.5)
        self._mini_pad(cv, 470, 116, 0.62)
        for r in (38, 48, 58):
            for st in (140, -40):
                cv.create_arc(470 - r, 178 - r, 470 + r, 178 + r,
                              start=st, extent=80, style="arc",
                              outline=C_OK, width=2)
        cv.create_text(470, 292, text="手柄震一下", font=FT(9), fill=C_SUB)
        cv.create_text(280, 330, text="手机和电脑必须连同一个 WiFi",
                       font=FT(10, "bold"), fill=C_RED)

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
             self.go_main, self.go_main, self.none, self.open_lab,
             self.open_notify][self.i]()
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

    def open_notify(self):
        self.res_lbl.config(
            text="通知窗口已打开：先点「放行防火墙」（UAC 点是），再勾「开启」",
            fg=C_OK)
        self.app.root.after(200, self.app.open_notify)

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
