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

# ---- 手柄配色（扁平微软风：近黑机身 + 四色 ABXY）----
P_BODY    = "#242428"      # 机身近黑
P_KNOB    = "#3d3d42"      # 摇杆帽 / view / menu 深灰
P_RING    = "#1a1a1e"      # 摇杆底座
P_DPAD    = "#8f8f96"      # 十字键中灰
P_GUIDE   = "#ffffff"      # 中央白圆

# ABXY 微软四色：(平时, 按下变亮)
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
            fl = round_rect(cv, x1 + 2, 54, x1 + 3, 72, 9, fill=C_PRESS, outline="")
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

        # 左摇杆（上左）
        lx, ly, lr = 206, 182, 40
        cv.create_oval(lx - lr, ly - lr, lx + lr, ly + lr, fill=P_RING, outline="")
        k = cv.create_oval(lx - 25, ly - 25, lx + 25, ly + 25, fill=P_KNOB, outline="")
        self._add("LS", k)
        cv.create_text(lx, ly, text="LS", font=("Consolas", 8, "bold"), fill="#c9c9cf")
        self.knob_l = (k, lx, ly)

        # 右摇杆（下中）
        rx, ry, rr = 352, 260, 40
        cv.create_oval(rx - rr, ry - rr, rx + rr, ry + rr, fill=P_RING, outline="")
        k2 = cv.create_oval(rx - 25, ry - 25, rx + 25, ry + 25, fill=P_KNOB, outline="")
        self._add("RS", k2)
        cv.create_text(rx, ry, text="RS", font=("Consolas", 8, "bold"), fill="#c9c9cf")
        self.knob_r = (k2, rx, ry)

        # 十字键（下左）：一整个灰色十字
        dx, dy, ds = 224, 262, 28
        for name, ox, oy in (("UP", 0, -1), ("DOWN", 0, 1),
                             ("LEFT", -1, 0), ("RIGHT", 1, 0)):
            if ox:
                x1, x2 = dx + ox * ds - ds * 0.52, dx + ox * ds + ds * 0.52
                y1, y2 = dy - ds * 0.36, dy + ds * 0.36
            else:
                x1, x2 = dx - ds * 0.36, dx + ds * 0.36
                y1, y2 = dy + oy * ds - ds * 0.52, dy + oy * ds + ds * 0.52
            it = round_rect(cv, x1, y1, x2, y2, 5, fill=P_DPAD, outline="")
            self.dpad_items[name] = it
            self._add(name, it)

        # ABXY（右上菱形）：微软四色，Y 黄 / X 蓝 / B 红 / A 绿
        # （画在右摇杆之后，A 压在摇杆环上沿，跟参考图一致）
        fx, fy, fr = 368, 186, 42
        for name, ox, oy in (("Y", 0, -1), ("A", 0, 1), ("X", -1, 0), ("B", 1, 0)):
            cx, cy = fx + ox * fr, fy + oy * fr
            it = cv.create_oval(cx - 17, cy - 17, cx + 17, cy + 17,
                               fill=ABXY_COLORS[name][0], outline="")
            self._add(name, it)
            cv.create_text(cx, cy, text=name, font=("Consolas", 11, "bold"),
                           fill="white")

        # VIEW / MENU：两个小深灰圆
        for name, cx, cy in (("BACK", 246, 216), ("START", 316, 218)):
            it = cv.create_oval(cx - 11, cy - 11, cx + 11, cy + 11,
                                fill=P_KNOB, outline="")
            self._add(name, it)
            cv.create_text(cx, cy, text=("◁" if name == "BACK" else "▷"),
                           font=(FONT, 9, "bold"), fill="#b9b9c0")

        # 中间发光 LOGO：白色大圆
        self.glow = cv.create_oval(258, 144, 310, 196, fill="", outline=P_GUIDE, width=2)
        it = cv.create_oval(264, 150, 304, 190, fill=P_GUIDE, outline="")
        self._add("GUIDE", it)
        cv.create_text(284, 170, text="✕", font=(FONT, 15, "bold"), fill="#3a3a40")

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
            if name in ABXY_COLORS:            # 四色键：平时原色，按下变亮
                base, lit = ABXY_COLORS[name]
                col = lit if on else (C_HL if self.hl == name else base)
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
