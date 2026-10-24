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

# ---- 手柄配色（碳黑版）----
P_BODY    = "#2b2f38"
P_BODY_LT = "#363b46"
P_IDLE    = "#5b6374"
P_RING    = "#20242c"

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

        # 机身：两侧外扩握把 + 中段
        cv.create_polygon([170, 194, 136, 266, 124, 330, 172, 358, 220, 332, 230, 250],
                          smooth=True, fill=P_BODY, outline="")
        cv.create_polygon([390, 194, 424, 266, 436, 330, 388, 358, 340, 332, 330, 250],
                          smooth=True, fill=P_BODY, outline="")
        round_rect(cv, 140, 116, 420, 258, 56, fill=P_BODY, outline="")
        round_rect(cv, 158, 124, 402, 200, 40, fill=P_BODY_LT, outline="")

        # 扳机
        for name, x1, x2 in (("LT", 160, 238), ("RT", 322, 400)):
            bg = round_rect(cv, x1, 60, x2, 84, 11, fill=P_RING, outline="")
            fl = round_rect(cv, x1 + 2, 62, x1 + 3, 82, 9, fill=C_PRESS, outline="")
            self.trig[name] = (x1 + 2, x2 - 2, fl)
            self._add(name, bg)
            cv.create_text((x1 + x2) // 2, 50, text=name,
                           font=("Consolas", 8, "bold"), fill=C_SUB)

        # 肩键
        for name, x1, x2 in (("LB", 154, 250), ("RB", 310, 406)):
            it = round_rect(cv, x1, 90, x2, 112, 9, fill=P_IDLE, outline="")
            self._add(name, it)
            cv.create_text((x1 + x2) // 2, 101, text=name,
                           font=("Consolas", 8, "bold"), fill="white")

        # 左摇杆（上左）
        lx, ly, lr = 206, 182, 40
        cv.create_oval(lx - lr, ly - lr, lx + lr, ly + lr, fill=P_RING, outline="")
        k = cv.create_oval(lx - 25, ly - 25, lx + 25, ly + 25, fill=P_IDLE, outline="")
        self._add("LS", k)
        cv.create_text(lx, ly, text="LS", font=("Consolas", 8, "bold"), fill="white")
        self.knob_l = (k, lx, ly)

        # 右摇杆（下中）
        rx, ry, rr = 348, 256, 40
        cv.create_oval(rx - rr, ry - rr, rx + rr, ry + rr, fill=P_RING, outline="")
        k2 = cv.create_oval(rx - 25, ry - 25, rx + 25, ry + 25, fill=P_IDLE, outline="")
        self._add("RS", k2)
        cv.create_text(rx, ry, text="RS", font=("Consolas", 8, "bold"), fill="white")
        self.knob_r = (k2, rx, ry)

        # 十字键（下左）
        dx, dy, ds = 224, 262, 28
        for name, ox, oy in (("UP", 0, -1), ("DOWN", 0, 1),
                             ("LEFT", -1, 0), ("RIGHT", 1, 0)):
            if ox:
                x1, x2 = dx + ox * ds - ds * 0.52, dx + ox * ds + ds * 0.52
                y1, y2 = dy - ds * 0.36, dy + ds * 0.36
            else:
                x1, x2 = dx - ds * 0.36, dx + ds * 0.36
                y1, y2 = dy + oy * ds - ds * 0.52, dy + oy * ds + ds * 0.52
            it = round_rect(cv, x1, y1, x2, y2, 5, fill=P_IDLE, outline="")
            self.dpad_items[name] = it
            self._add(name, it)

        # ABXY（右上菱形）
        fx, fy, fr = 374, 176, 44
        for name, ox, oy in (("Y", 0, -1), ("A", 0, 1), ("X", -1, 0), ("B", 1, 0)):
            cx, cy = fx + ox * fr, fy + oy * fr
            cv.create_oval(cx - 17, cy - 17, cx + 17, cy + 17, fill=P_RING, outline="")
            it = cv.create_oval(cx - 14, cy - 14, cx + 14, cy + 14,
                               fill=P_IDLE, outline="")
            self._add(name, it)
            cv.create_text(cx, cy, text=name, font=("Consolas", 11, "bold"),
                           fill="white")

        # VIEW / MENU
        for name, cx, cy in (("BACK", 252, 214), ("START", 312, 214)):
            it = cv.create_oval(cx - 11, cy - 11, cx + 11, cy + 11,
                               fill=P_IDLE, outline="")
            self._add(name, it)
            cv.create_text(cx, cy, text=("◁" if name == "BACK" else "▷"),
                           font=(FONT, 9, "bold"), fill="white")

        # 中间发光 LOGO
        self.glow = cv.create_oval(262, 148, 306, 192, fill="", outline=C_ACC, width=2)
        it = cv.create_oval(268, 154, 300, 186, fill=P_IDLE, outline="")
        self._add("GUIDE", it)
        cv.create_text(284, 170, text="◎", font=(FONT, 15, "bold"), fill="white")

        cv.create_text(284, 322, text="XBOX 360  ·  VIRTUAL PAD",
                       font=("Consolas", 9, "bold"), fill="#79808e")

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
            col = P_IDLE
            if on:
                col = C_PRESS
            elif self.hl == name:
                col = C_HL
            for it in ids:
                cv.itemconfig(it, fill=col)

        for name, it in self.dpad_items.items():
            on = bool(b.get(name))
            col = C_PRESS if on else (C_HL if self.hl == name else P_IDLE)
            cv.itemconfig(it, fill=col)

        for knob, ax, ay, nm in ((self.knob_l, "LX", "LY", "LS"),
                                 (self.knob_r, "RX", "RY", "RS")):
            it, cx, cy = knob
            dx = a.get(ax, 0.0) * 15
            dy = a.get(ay, 0.0) * 15
            cv.coords(it, cx - 25 + dx, cy - 25 + dy, cx + 25 + dx, cy + 25 + dy)
            cv.itemconfig(it, fill=(C_PRESS if b.get(nm) else P_IDLE))

        for name in ("LT", "RT"):
            x1, x2, it = self.trig[name]
            v = max(0.0, min(1.0, a.get(name, 0.0)))
            if v <= 0.001:
                cv.coords(it, [0, 0, 0, 0])
            else:
                cv.coords(it, _rr_pts(x1, 62, x1 + (x2 - x1) * v, 82, 9))
