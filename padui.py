"""Xbox 手柄图绘制模块：主界面 gui.py 和识别向导 wizard.py 共用同一张图。

用法：
    pv = PadView(canvas)            # 画好手柄
    pv.bind_click(lambda name: ...)  # 点图上按键的回调（可选）
    pv.set_state(buttons, axes)      # 每帧刷新：按键亮、摇杆帽动、扳机扣动
    pv.highlight("A")               # 高亮某个键（向导用，琥珀色）
    pv.set_shake(level)             # 震动联动：level 0~1，越大抖得越凶

每个按键都是独立的图片控件（assets/ 里从实物图裁出来的 PNG），
按下 = 贴"提亮+绿染"版本并下沉 1px，向导待按 = 琥珀染。
顶部 LT/LB/RT/RB 用俯视图裁的实物图，扳机随扣动深度下压。
"""
import math
import os
import sys

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

# ---- 手柄配色（旧版 Canvas 画的遗留，gui.py import 兼容用）----
P_BODY    = "#20222a"
P_KNOB    = "#2e3038"
P_RING    = "#14151a"
P_DPAD    = "#191b22"
P_PANEL   = "#2b2e39"
P_LED     = "#3f7dff"
P_ABXY    = "#17181f"

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


def _base_dir():
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def app_icon_path():
    base = _base_dir()
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


class PadView:
    """手柄图 —— 实物照片做底图，每个按键是独立图片控件叠在上面。

    布局（canvas 480 x 432）：
        顶部扳机行：LT/RT（大扳机）+ LB/RB（横条肩键），俯视图裁的实物图
        正面图 370 宽居中，按键热区按 1365x1024 原图标定等比缩放
    """

    IMG_W, IMG_H = 1365, 1024
    PAD_W = 370            # 正面图显示宽（"把手柄缩小"就调这里）
    TOP_Y = 150            # 正面图顶部 y
    CANVAS_W = 480

    # 圆形按键：名字 -> (cx, cy, r)，原图像素（assets/<名>.png 就按这个裁的）
    BTN_CIRC = {
        "Y": (1060, 296, 62), "X": (963, 393, 62),
        "B": (1157, 393, 62), "A": (1060, 490, 62),
        "BACK": (488, 291, 44), "START": (857, 288, 44),
        "GUIDE": (779, 397, 44),
        "LS": (270, 382, 88), "RS": (869, 588, 118),
    }
    # 十字键（实测中心/臂长/半宽，原图像素）
    DPAD_C = (468, 616, 100, 49)
    # 顶部扳机行：显示位置 (x, y, w, h)，按 480 宽画布标定
    TOP_ASSETS = {
        "LT": (60, 4, 88, 87),
        "RT": (332, 4, 88, 87),
        "LB": (72, 94, 105, 53),
        "RB": (303, 94, 105, 53),
    }

    def __init__(self, canvas):
        self.cv = canvas
        self.btns = {}         # 名字 -> item id（独立贴图控件）
        self.drop0 = {}        # 名字 -> 贴图原始 y（按下下沉/扳机下压相对它）
        self.zones = []        # (name, x1, y1, x2, y2) 画布坐标热区
        self.knob_l = self.knob_r = None   # (dot_id, bx, by, 位移半径)
        self.hl = None
        self._cb = None
        self._shake = 0.0      # 0~1 震动强度
        self._shake_off = (0, 0)
        self._shake_job = None
        cv = self.cv
        cv.bind("<Button-1>", self._on_click)
        cv.bind("<Motion>", self._on_motion)
        self.draw()

    # -------------------------------------------------- 素材加载
    @staticmethod
    def _load_photo(w, h):
        """正面底图按目标尺寸缩放，结果缓存（PhotoImage 必须持有引用）"""
        from PIL import Image, ImageTk
        key = (w, h)
        if key not in _PHOTO_CACHE:
            p = os.path.join(_base_dir(), "pad_front.jpg")
            img = Image.open(p).convert("RGB").resize((w, h), Image.LANCZOS)
            _PHOTO_CACHE[key] = ImageTk.PhotoImage(img)
        return _PHOTO_CACHE[key]

    @staticmethod
    def _btn_image(name, w, h, tint):
        """按键贴图三态：normal / press(亮+绿) / hl(琥珀)。裁自 assets/<名>.png"""
        from PIL import Image, ImageEnhance, ImageTk
        key = (name, w, h, tint)
        if key in _PHOTO_CACHE:
            return _PHOTO_CACHE[key]
        p = os.path.join(_base_dir(), "assets", name + ".png")
        img = Image.open(p).convert("RGBA")
        img = img.resize((max(1, w), max(1, h)), Image.LANCZOS)
        if tint:
            rgb = img.convert("RGB")
            rgb = ImageEnhance.Brightness(rgb).enhance(1.30)
            col = Image.new("RGB", rgb.size,
                            C_PRESS if tint == "press" else C_HL)
            rgb = Image.blend(rgb, col, 0.38 if tint == "press" else 0.45)
            out = Image.merge("RGBA", (*rgb.split(), img.split()[3]))
        else:
            out = img
        ph = ImageTk.PhotoImage(out)
        _PHOTO_CACHE[key] = ph
        return ph

    # -------------------------------------------------- 绘制
    def _reg(self, name, item, zx1, zy1, zx2, zy2):
        self.btns[name] = item
        self.zones.append((name, zx1, zy1, zx2, zy2))

    def bind_click(self, cb):
        self._cb = cb

    def _hit(self, ex, ey):
        for name, x1, y1, x2, y2 in self.zones:
            if x1 <= ex <= x2 and y1 <= ey <= y2:
                return name
        return None

    def _on_click(self, e):
        n = self._hit(e.x - self._shake_off[0], e.y - self._shake_off[1])
        if n and self._cb:
            self._cb(n)

    def _on_motion(self, e):
        try:
            x = e.x - self._shake_off[0]
            y = e.y - self._shake_off[1]
            self.cv.config(cursor="hand2" if self._hit(x, y) else "")
        except Exception:
            pass

    def draw(self):
        import random
        cv = self.cv
        cv.delete("all")
        self.btns.clear()
        self.drop0.clear()
        self.zones = []
        self._shake_off = (0, 0)

        try:
            cw, ch = int(cv["width"]), int(cv["height"])
        except Exception:
            cw, ch = self.CANVAS_W, 432
        # 布局按 480x432 标定，画布不是这个尺寸（向导 560x370 等）就等比缩放居中
        k = min(cw / self.CANVAS_W, ch / 432.0)
        ox = int((cw - self.CANVAS_W * k) // 2)
        oy = int((ch - 432 * k) // 2)

        # ---- 正面图：缩小居中，放在扳机行下方 ----
        pw = int(self.PAD_W * k)
        ph = int(self.IMG_H * (pw / self.IMG_W))
        px0 = ox + int(55 * k)
        py0 = oy + int(self.TOP_Y * k)
        s = pw / self.IMG_W
        cv.create_image(px0, py0, anchor="nw",
                        image=self._load_photo(pw, ph))

        def X(x):
            return px0 + x * s

        def Y(y):
            return py0 + y * s

        def R(r):
            return r * s

        # ---- 顶部扳机 / 肩键（俯视图实物图，独立控件）----
        for name, (x, y, w, h) in self.TOP_ASSETS.items():
            ax, ay = ox + int(x * k), oy + int(y * k)
            aw, ah = int(w * k), int(h * k)
            img = self._btn_image(name, aw, ah, None)
            it = cv.create_image(ax, ay, anchor="nw", image=img)
            self._reg(name, it, ax, ay, ax + aw, ay + ah)
            self.drop0[name] = ay

        # ---- 圆形按键（独立贴图）----
        for name, (cx, cy, r) in self.BTN_CIRC.items():
            d = 2 * R(r)
            img = self._btn_image(name, int(d), int(d), None)
            it = cv.create_image(X(cx) - d / 2, Y(cy) - d / 2,
                                 anchor="nw", image=img)
            self._reg(name, it, X(cx - r), Y(cy - r), X(cx + r), Y(cy + r))
            self.drop0[name] = Y(cy) - d / 2

        # ---- 十字键四臂（独立贴图）----
        dx, dy, L, Wd = self.DPAD_C
        arms = (("UP",    dx - Wd, dy - L,      dx + Wd, dy - 6),
                ("DOWN",  dx - Wd, dy + 6,      dx + Wd, dy + L),
                ("LEFT",  dx - L,  dy - Wd,     dx - 6,  dy + Wd),
                ("RIGHT", dx + 6,  dy - Wd,     dx + L,  dy + Wd))
        for name, x1, y1, x2, y2 in arms:
            w, h = int((x2 - x1) * s), int((y2 - y1) * s)
            img = self._btn_image(name, w, h, None)
            it = cv.create_image(X(x1), Y(y1), anchor="nw", image=img)
            self._reg(name, it, X(x1), Y(y1), X(x2), Y(y2))
            self.drop0[name] = Y(y1)

        # ---- 摇杆位移指示点：半透明白点叠在帽上随轴滑动 ----
        for tag, bx, by in (("L", 270, 382), ("R", 869, 588)):
            dot = cv.create_oval(0, 0, 0, 0, fill="#ffffff",
                                 stipple="gray50", outline="")
            if tag == "L":
                self.knob_l = (dot, X(bx), Y(by), R(40))
            else:
                self.knob_r = (dot, X(bx), Y(by), R(40))

    # -------------------------------------------------- 震动抖动
    def set_shake(self, level):
        """level 0~1。>0 时启动抖动循环，归 0 平稳停下"""
        self._shake = max(0.0, min(1.0, level))
        if self._shake > 0 and self._shake_job is None:
            self._shake_step()

    def _shake_step(self):
        import random
        cv = self.cv
        if self._shake <= 0:
            ox, oy = self._shake_off
            if ox or oy:
                cv.move("all", -ox, -oy)
            self._shake_off = (0, 0)
            self._shake_job = None
            return
        amp = 1.0 + self._shake * 2.0
        nx = int(round(random.uniform(-amp, amp)))
        ny = int(round(random.uniform(-amp / 2, amp / 2)))
        ox, oy = self._shake_off
        cv.move("all", nx - ox, ny - oy)
        self._shake_off = (nx, ny)
        self._shake_job = self.cv.after(45, self._shake_step)

    # -------------------------------------------------- 刷新
    def highlight(self, name):
        self.hl = name

    def set_state(self, buttons, axes):
        cv = self.cv
        b = buttons or {}
        a = axes or {}
        # 抖动期间 set_state 的绝对 coords 要带上当前偏移，不然每帧都把
        # 按钮拽回原位，抖动就只剩底图在抖了
        offx, offy = self._shake_off

        for name, it in self.btns.items():
            on = bool(b.get(name))
            trig_v = max(0.0, min(1.0, a.get(name, 0.0))) \
                if name in ("LT", "RT") else 0.0
            active = on or trig_v > 0.05
            tint = "press" if active else ("hl" if self.hl == name else None)
            x1, y1, x2, y2 = self._zone_of(name)
            w, h = int(x2 - x1), int(y2 - y1)
            img = self._btn_image(name, w, h, tint)
            # 扳机随扣动深度下压最多 6px；普通按键按下下沉 1px
            drop = int(trig_v * 6) if name in ("LT", "RT") else (1 if on else 0)
            cv.itemconfig(it, image=img)
            cv.coords(it, x1 + offx, self.drop0.get(name, y1) + drop + offy)

        # 摇杆位移点（值正 = 上推，画布 y 取反）
        for knob, ax, ay, nm in ((self.knob_l, "LX", "LY", "LS"),
                                 (self.knob_r, "RX", "RY", "RS")):
            it, bx, by, br = knob
            ddx = a.get(ax, 0.0) * br
            ddy = -a.get(ay, 0.0) * br
            r = br * 0.9
            cv.coords(it, bx - r + ddx + offx, by - r + ddy + offy,
                      bx + r + ddx + offx, by + r + ddy + offy)
            cv.itemconfig(it, fill=(C_PRESS if b.get(nm) else "#ffffff"))

    def _zone_of(self, name):
        for n, x1, y1, x2, y2 in self.zones:
            if n == name:
                return (x1, y1, x2, y2)
        return (0, 0, 0, 0)


_PHOTO_CACHE = {}
