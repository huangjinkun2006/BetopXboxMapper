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

# ABXY 实机点亮配色：(平时, 按下变亮) —— Y 橙 / X 蓝 / B 红 / A 绿
ABXY_COLORS = {
    "Y": ("#f08a1d", "#ffb75e"),
    "X": ("#2e7bff", "#8ab4ff"),
    "B": ("#e0333a", "#ff8a8e"),
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
    """手柄图 —— 直接用 BTP-V1T 实物照片做底图，按键高亮/摇杆点叠在照片上。

    热区坐标按 1365x1024 原图标定（_calib 脚本用颜色特征找的 ABXY 圆心，
    其余按布局目测），运行时按画布大小等比缩放。
    点击用画布级 hit-test（Canvas 的 fill="" 元素不响应 tag_bind）。
    """

    IMG_W, IMG_H = 1365, 1024

    # 圆形按键：名字 -> (cx, cy, r)，原图像素
    BTN_CIRC = {
        "Y": (1060, 296, 57), "X": (963, 393, 57),
        "B": (1157, 393, 57), "A": (1060, 490, 57),
        "BACK": (488, 291, 40), "START": (857, 288, 40),
        "GUIDE": (779, 397, 40),
        "LS": (270, 382, 100), "RS": (869, 588, 108),
    }
    # FN 键固件不上报，刻意不进热区（跟旧版一致：不亮、不可改键）
    DPAD_C = (471, 591, 121, 78)          # 十字键 cx, cy, 臂长, 臂宽
    SHOULDER = {"LB": (212, 115, 443, 194), "RB": (928, 115, 1150, 194)}
    TRIGGERS = {"LT": (255, 64, 406, 106), "RT": (952, 64, 1116, 106)}
    KNOB_R = 83                            # 摇杆帽本体半径（原图像素）

    def __init__(self, canvas):
        self.cv = canvas
        self.items = {}        # 名字 -> [高亮 item ids]
        self.dpad_items = {}   # 方向 -> item id
        self.trig = {}         # LT/RT -> item id
        self.zones = []        # (name, x1, y1, x2, y2) 画布坐标
        self.knob_l = self.knob_r = None   # (dot_id, bx, by, 位移半径)
        self.hl = None
        self._cb = None
        cv = self.cv
        cv.bind("<Button-1>", self._on_click)
        cv.bind("<Motion>", self._on_motion)
        self.draw()

    # -------------------------------------------------- 底图
    @staticmethod
    def _load_photo(w, h):
        """按目标尺寸缩放实物照片，结果按尺寸缓存（PhotoImage 必须持有引用）"""
        import os
        import sys
        from PIL import Image, ImageTk
        key = (w, h)
        if key not in _PHOTO_CACHE:
            base = getattr(sys, "_MEIPASS",
                           os.path.dirname(os.path.abspath(__file__)))
            p = os.path.join(base, "pad_front.jpg")
            img = Image.open(p).convert("RGB").resize((w, h), Image.LANCZOS)
            _PHOTO_CACHE[key] = ImageTk.PhotoImage(img)
        return _PHOTO_CACHE[key]

    # -------------------------------------------------- 绘制
    def _reg(self, name, item, zx1, zy1, zx2, zy2):
        self.items.setdefault(name, []).append(item)
        self.zones.append((name, zx1, zy1, zx2, zy2))

    def _hi(self, x1, y1, x2, y2, shape="oval"):
        """建一个初始不可见的高亮块，按下时叠绿色半透明"""
        kw = dict(fill="", outline="", width=4)
        if shape == "oval":
            return self.cv.create_oval(x1, y1, x2, y2, **kw)
        return self.cv.create_rectangle(x1, y1, x2, y2, **kw)

    def bind_click(self, cb):
        self._cb = cb

    def _hit(self, ex, ey):
        for name, x1, y1, x2, y2 in self.zones:
            if x1 <= ex <= x2 and y1 <= ey <= y2:
                return name
        return None

    def _on_click(self, e):
        n = self._hit(e.x, e.y)
        if n and self._cb:
            self._cb(n)

    def _on_motion(self, e):
        try:
            self.cv.config(cursor="hand2" if self._hit(e.x, e.y) else "")
        except Exception:
            pass

    def draw(self):
        cv = self.cv
        cv.delete("all")
        self.items.clear()
        self.dpad_items.clear()
        self.trig.clear()
        self.zones = []

        try:
            cw, ch = int(cv["width"]), int(cv["height"])
        except Exception:
            cw, ch = 560, 370
        s = min(cw / self.IMG_W, ch / self.IMG_H)
        w, h = int(self.IMG_W * s), int(self.IMG_H * s)
        ox, oy = (cw - w) // 2, (ch - h) // 2
        cv.create_image(ox, oy, anchor="nw",
                        image=self._load_photo(w, h))

        def X(x):
            return ox + x * s

        def Y(y):
            return oy + y * s

        def R(r):
            return r * s

        # 圆形按键：BACK/START/GUIDE/ABXY + LS/RS（热区 + 高亮块）
        for name, (cx, cy, r) in self.BTN_CIRC.items():
            it = self._hi(X(cx - r), Y(cy - r), X(cx + r), Y(cy + r))
            self._reg(name, it, X(cx - r), Y(cy - r), X(cx + r), Y(cy + r))

        # 十字键四臂
        dx, dy, L, Wd = self.DPAD_C
        arms = (("UP", dx - Wd / 2, dy - L, dx + Wd / 2, dy - L * 0.12),
                ("DOWN", dx - Wd / 2, dy + L * 0.12, dx + Wd / 2, dy + L),
                ("LEFT", dx - L, dy - Wd / 2, dx - L * 0.12, dy + Wd / 2),
                ("RIGHT", dx + L * 0.12, dy - Wd / 2, dx + L, dy + Wd / 2))
        for name, x1, y1, x2, y2 in arms:
            it = self._hi(X(x1), Y(y1), X(x2), Y(y2), shape="rect")
            self.dpad_items[name] = it
            self._reg(name, it, X(x1), Y(y1), X(x2), Y(y2))

        # 肩键 / 扳机（图顶上露出的那两条）
        for name, (x1, y1, x2, y2) in self.SHOULDER.items():
            it = self._hi(X(x1), Y(y1), X(x2), Y(y2), shape="rect")
            self._reg(name, it, X(x1), Y(y1), X(x2), Y(y2))
        for name, (x1, y1, x2, y2) in self.TRIGGERS.items():
            it = self._hi(X(x1), Y(y1), X(x2), Y(y2), shape="rect")
            self.trig[name] = it
            self._reg(name, it, X(x1), Y(y1), X(x2), Y(y2))

        # 摇杆位移指示点：半透明圆叠在帽上随轴滑动（值正=上推，y 取反）
        for tag, bx, by in (("L", 270, 382), ("R", 869, 588)):
            dot = cv.create_oval(0, 0, 0, 0, fill="#ffffff",
                                 stipple="gray50", outline="")
            if tag == "L":
                self.knob_l = (dot, X(bx), Y(by), R(40))
            else:
                self.knob_r = (dot, X(bx), Y(by), R(40))
        self.glow = None

    # -------------------------------------------------- 刷新
    def highlight(self, name):
        self.hl = name

    def set_state(self, buttons, axes):
        cv = self.cv
        b = buttons or {}
        a = axes or {}

        # 按键高亮：按下 = 绿色半透明，向导待按 = 琥珀
        for name, ids in self.items.items():
            if name in ("LS", "RS", "LT", "RT"):
                continue
            on = bool(b.get(name))
            if on:
                st = dict(fill=C_PRESS, stipple="gray25",
                          outline=C_PRESS, width=3)
            elif self.hl == name:
                st = dict(fill=C_HL, stipple="gray25",
                          outline=C_HL, width=4)
            else:
                st = dict(fill="", outline="", width=0)
            for it in ids:
                cv.itemconfig(it, **st)

        # 扳机：按下深度超阈值就亮
        for name, it in self.trig.items():
            v = max(0.0, min(1.0, a.get(name, 0.0)))
            if v > 0.05 or self.hl == name:
                cv.itemconfig(it, fill=C_PRESS if v > 0.05 else C_HL,
                              stipple="gray50", outline=C_PRESS, width=2)
            else:
                cv.itemconfig(it, fill="", outline="", width=0)

        # 摇杆位移点
        for knob, ax, ay, nm in ((self.knob_l, "LX", "LY", "LS"),
                                 (self.knob_r, "RX", "RY", "RS")):
            it, bx, by, br = knob
            dx = a.get(ax, 0.0) * br
            dy = -a.get(ay, 0.0) * br
            r = br * 0.9
            cv.coords(it, bx - r + dx, by - r + dy, bx + r + dx, by + r + dy)
            cv.itemconfig(it, fill=(C_PRESS if b.get(nm) else "#ffffff"))


_PHOTO_CACHE = {}


# ---- 程序图标（icon.ico 跟随 exe 打包，开发态用源码目录那份）----
def app_icon_path():
    import os
    import sys
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(base, "icon.ico")
    return p if os.path.exists(p) else None


def apply_icon(win):
    """给 Tk 窗口挂手柄图标；失败静默（不挡主流程）"""
    p = app_icon_path()
    if p:
        try:
            win.iconbitmap(p)
        except Exception:
            pass
