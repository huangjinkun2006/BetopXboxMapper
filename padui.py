"""Xbox 手柄图绘制模块：主界面 gui.py 和识别向导 wizard.py 共用同一张图。

用法：
    pv = PadView(canvas)            # 画好手柄
    pv.bind_click(lambda name: ...)  # 点图上按键的回调（可选）
    pv.set_state(buttons, axes)      # 每帧刷新：按键亮、摇杆帽动、扳机填充
    pv.highlight("A")               # 高亮某个键（向导用，琥珀色）
"""
import math

# ---- 界面配色（Xbox 绿）----
C_BG      = "#f2f3f7"
C_CARD    = "#ffffff"
C_ACC     = "#107c10"
C_ACC_DK  = "#0c5f0c"
C_ACC_LT  = "#eaf5ea"
C_TEXT    = "#26282e"
C_SUB     = "#8a8f99"
C_LINE    = "#ececf0"
C_OK      = "#22c07a"
C_PRESS   = "#5dc21e"
C_HL      = "#ffb02e"      # 向导高亮：待按下的键

# ---- 手柄配色（北通 BTP-V1T 实物风：哑光近黑 + 中央蓝色灯阵）----
P_BODY    = "#20222a"      # 机身哑光黑
P_KNOB    = "#2e3038"      # 摇杆帽 / 按钮深灰
P_RING    = "#14151a"      # 摇杆底座
P_DPAD    = "#191b22"      # 十字键（亮面黑）
P_PANEL   = "#2b2e39"      # 中央亮面斜面板
P_LED     = "#3f7dff"      # 蓝色 LED 灯阵 / 右摇杆光环
P_ABXY    = "#17181f"      # ABXY 亮面黑

# ABXY 按下时的亮色（平时是亮面黑）
ABXY_COLORS = {
    "Y": ("#f2c200", "#ffe25e"),
    "X": ("#1e9de8", "#7cc7ff"),
    "B": ("#e8453c", "#ff9a92"),
    "A": ("#3fb54a", "#93e59b"),
}

FONT = "Microsoft YaHei"


def _rr_pts(x1, y1, x2, y2, r):
    pts = []
    for cx, cy, sa in ((x2 - r, y2 - r, 0), (x1 + r, y2 - r, 90),
                       (x1 + r, y1 + r, 180), (x2 - r, y1 + r, 270)):
        for i in range(10):
            a = math.radians(sa + i * 9)
            pts += [cx + r * math.cos(a), cy + r * math.sin(a)]
    return pts


def round_rect(cv, x1, y1, x2, y2, r, **kw):
    return cv.create_polygon(_rr_pts(x1, y1, x2, y2, r), smooth=True, **kw)


class PadView:
    """中央那张 Xbox 手柄图"""

    def __init__(self, canvas):
        self.cv = canvas
        self.items = {}        # 名字 -> [item ids]
        self.dpad_items = {}   # 方向 -> item id
        self.trig = {}         # LT/RT -> (x1, x2, fill_id)
        self.knob_l = self.knob_r = None
        self.glow = None
        self.hl = None         # 当前高亮的键名
        self._cb = None
        self.draw()

    # -------------------------------------------------- 绘制
    def _add(self, name, item):
        self.items.setdefault(name, []).append(item)
        if self._cb:
            self.cv.tag_bind(item, "<Button-1>", lambda e, n=name: self._cb(n))
            self.cv.tag_bind(item, "<Enter>",
                             lambda e: self.cv.config(cursor="hand2"))
            self.cv.tag_bind(item, "<Leave>", lambda e: self.cv.config(cursor=""))

    def bind_click(self, cb):
        self._cb = cb

    def draw(self):
        cv = self.cv
        cv.delete("all")
        self.items.clear()
        self.dpad_items.clear()
        self.trig.clear()

        # 机身：一条平滑闭合轮廓勾出整个手柄（含双握把和中下凹口）
        cv.create_polygon(
            [120, 162, 152, 132, 212, 124, 262, 116, 284, 108, 306, 116,
             356, 124, 416, 132, 448, 162, 468, 210, 466, 258, 438, 326,
             400, 356, 356, 349, 330, 308, 284, 294, 238, 308, 212, 349,
             168, 356, 130, 326, 102, 258, 100, 210],
            smooth=True, fill=P_BODY, outline="")
        # 顶部中间的小凸起（USB 口的意思）
        round_rect(cv, 268, 100, 300, 116, 6, fill=P_BODY, outline="")

        # 扳机
        for name, x1, x2 in (("LT", 160, 238), ("RT", 322, 400)):
            bg = round_rect(cv, x1, 52, x2, 74, 11, fill=P_RING, outline="")
            fl = round_rect(cv, 0, 0, 0, 0, 9, fill=C_PRESS, outline="")
            cv.coords(fl, [0, 0, 0, 0])
            self.trig[name] = (x1 + 2, x2 - 2, fl)
            self._add(name, bg)
            cv.create_text((x1 + x2) // 2, 42, text=name,
                           font=("Consolas", 8, "bold"), fill=C_SUB)

        # 肩键
        for name, x1, x2 in (("LB", 154, 250), ("RB", 310, 406)):
            it = round_rect(cv, x1, 82, x2, 102, 9, fill=P_KNOB, outline="")
            self._add(name, it)
            cv.create_text((x1 + x2) // 2, 92, text=name,
                           font=("Consolas", 8, "bold"), fill="white")

        # 中央亮面斜面板（实物上半部那块梯形饰板，压在摇杆底座之下）
        cv.create_polygon([234, 118, 334, 118, 360, 198, 208, 198],
                          smooth=True, fill=P_PANEL, outline="#3a3d48")

        # 左摇杆（上左）
        lx, ly, lr = 206, 182, 40
        cv.create_oval(lx - lr, ly - lr, lx + lr, ly + lr, fill=P_RING, outline="")
        k = cv.create_oval(lx - 25, ly - 25, lx + 25, ly + 25, fill=P_KNOB, outline="")
        self._add("LS", k)
        cv.create_text(lx, ly, text="LS", font=("Consolas", 8, "bold"), fill="#c9c9cf")
        self.knob_l = (k, lx, ly)

        # 右摇杆（下中）：底座外圈带一圈蓝色 LED 光环（实物特征）
        rx, ry, rr = 352, 268, 40
        cv.create_oval(rx - rr - 4, ry - rr - 4, rx + rr + 4, ry + rr + 4,
                       fill="", outline=P_LED, width=2)
        cv.create_oval(rx - rr, ry - rr, rx + rr, ry + rr, fill=P_RING, outline="")
        k2 = cv.create_oval(rx - 25, ry - 25, rx + 25, ry + 25, fill=P_KNOB, outline="")
        self._add("RS", k2)
        cv.create_text(rx, ry, text="RS", font=("Consolas", 8, "bold"), fill="#c9c9cf")
        self.knob_r = (k2, rx, ry)

        # 十字键（下左）：连成一体的大十字（亮面黑）
        dx, dy, ds = 220, 262, 26
        L, W = ds * 1.5, ds * 0.44
        for name, ox, oy in (("UP", 0, -1), ("DOWN", 0, 1),
                             ("LEFT", -1, 0), ("RIGHT", 1, 0)):
            if ox:
                x1, x2 = (dx, dx + ox * L) if ox > 0 else (dx + ox * L, dx)
                y1, y2 = dy - W, dy + W
            else:
                x1, x2 = dx - W, dx + W
                y1, y2 = (dy, dy + oy * L) if oy > 0 else (dy + oy * L, dy)
            it = round_rect(cv, x1, y1, x2, y2, 7, fill=P_DPAD, outline="#3d404a")
            self.dpad_items[name] = it
            self._add(name, it)
        # 中心小块补缝
        round_rect(cv, dx - W, dy - W, dx + W, dy + W, 4,
                   fill=P_DPAD, outline="#3d404a")

        # ABXY（右上菱形）：实物是四颗亮面黑圆钮（字母很淡），按下闪对应彩光
        fx, fy, fr = 378, 172, 38
        for name, ox, oy in (("Y", 0, -1), ("A", 0, 1), ("X", -1, 0), ("B", 1, 0)):
            cx, cy = fx + ox * fr, fy + oy * fr
            it = cv.create_oval(cx - 17, cy - 17, cx + 17, cy + 17,
                               fill=P_ABXY, outline="#3a3d47")
            self._add(name, it)
            cv.create_text(cx, cy + 1, text=name, font=("Consolas", 10, "bold"),
                           fill="#565a66")

        # 中央控制区：⌂ GUIDE / ☰ BACK（上排），FN（装饰）+ 蓝色先游 logo START（下排）
        it = cv.create_oval(248, 134, 270, 156, fill=P_ABXY, outline="#41444f")
        self._add("GUIDE", it)
        cv.create_text(259, 145, text="⌂", font=(FONT, 12, "bold"), fill="#9aa0ae")

        it = cv.create_oval(298, 134, 320, 156, fill=P_ABXY, outline="#41444f")
        self._add("BACK", it)
        cv.create_text(309, 145, text="☰", font=(FONT, 12, "bold"), fill="#9aa0ae")

        round_rect(cv, 246, 170, 272, 190, 5, fill=P_ABXY, outline="#41444f")
        cv.create_text(259, 180, text="FN", font=("Consolas", 8, "bold"),
                       fill="#8a8f9c")

        it = cv.create_oval(296, 170, 320, 192, fill=P_ABXY, outline="#41444f")
        self._add("START", it)
        cv.create_text(307, 180, text="➤", font=(FONT, 11, "bold"), fill=P_LED)

        # 中央蓝色 LED 灯阵（4x3 小圆点，实物特征）
        for r in range(3):
            for c in range(4):
                x0, y0 = 268 + c * 14, 222 + r * 14
                cv.create_oval(x0, y0, x0 + 5, y0 + 5, fill=P_LED, outline="")
        self.glow = None

    # -------------------------------------------------- 刷新
    def highlight(self, name):
        self.hl = name

    def set_state(self, buttons, axes):
        cv = self.cv
        b = buttons or {}
        a = axes or {}

        for name, ids in self.items.items():
            if name in ("LT", "RT", "LS", "RS"):
                continue
            on = bool(b.get(name))
            if name in ABXY_COLORS:            # 亮面黑圆钮：按下闪对应彩光
                lit = ABXY_COLORS[name][1]
                col = lit if on else (C_HL if self.hl == name else P_ABXY)
            else:
                col = P_KNOB
                if on:
                    col = C_PRESS
                elif self.hl == name:
                    col = C_HL
            for it in ids:
                cv.itemconfig(it, fill=col)

        for name, it in self.dpad_items.items():
            on = bool(b.get(name))
            col = C_PRESS if on else (C_HL if self.hl == name else P_DPAD)
            cv.itemconfig(it, fill=col)

        for knob, ax, ay, nm in ((self.knob_l, "LX", "LY", "LS"),
                                 (self.knob_r, "RX", "RY", "RS")):
            it, cx, cy = knob
            dx = a.get(ax, 0.0) * 15
            dy = a.get(ay, 0.0) * 15
            cv.coords(it, cx - 25 + dx, cy - 25 + dy, cx + 25 + dx, cy + 25 + dy)
            cv.itemconfig(it, fill=(C_PRESS if b.get(nm) else P_KNOB))

        for name in ("LT", "RT"):
            x1, x2, it = self.trig[name]
            v = max(0.0, min(1.0, a.get(name, 0.0)))
            if v <= 0.001:
                cv.coords(it, [0, 0, 0, 0])
            else:
                cv.coords(it, _rr_pts(x1, 54, x1 + (x2 - x1) * v, 72, 9))
