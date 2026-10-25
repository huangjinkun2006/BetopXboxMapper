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
    """手柄图 —— 顶部一张完整顶视图 + 正面实物照片，按键全是独立贴图控件。

    布局（canvas 480 x 510 标定，其他尺寸等比缩放居中）：
        顶部：完整的顶视图（assets/pad_top.png，扳机/肩键/USB-C 全都看得到），
              LT/LB/RT/RB 四个区域是独立贴图控件，按下亮绿
        下方：正面图 360 宽居中，按键热区按 1365x1024 原图标定等比缩放
        摇杆：帽是单独裁的圆形贴图，拨动摇杆时整颗帽跟着滑，
              底座那圈是照片里擦掉帽后留下的暗色沉孔
    """

    IMG_W, IMG_H = 1365, 1024
    PAD_W = 360            # 正面图显示宽（"把手柄缩小"就调这里）
    PAD_X = 60             # 正面图左上 x（480 标定，居中）
    PAD_Y = 236            # 正面图顶部 y
    CANVAS_W = 480
    CANVAS_H = 510

    # 顶视图（assets/pad_top.png，1448x1086）：裁掉白边后整条铺在顶部
    TOP_BBOX = (38, 204, 1411, 867)    # 内容区（原图坐标）
    TOP_W = 456                        # 显示宽（480 标定）
    TOP_Y = 6                          # 显示顶部 y
    # LT/LB/RT/RB 在顶视图原图里的区域 (x1, y1, x2, y2)，按下亮绿
    TOP_REGIONS = {
        "LT": (60, 200, 400, 465),
        "LB": (60, 460, 460, 680),
        "RT": (1050, 200, 1395, 465),
        "RB": (965, 460, 1385, 680),
    }

    # 圆形按键：名字 -> (cx, cy, r)，原图像素（assets/<名>.png 就按这个裁的）
    # LS/RS 不在这里 —— 摇杆单独走 STICKS
    BTN_CIRC = {
        "Y": (1060, 296, 62), "X": (963, 393, 62),
        "B": (1157, 393, 62), "A": (1060, 490, 62),
        "BACK": (488, 291, 44), "START": (857, 288, 44),
        "GUIDE": (779, 397, 44),
    }
    # 十字键（实测中心/臂长/半宽，原图像素）
    DPAD_C = (468, 616, 100, 49)
    # 摇杆（原图 1365 空间）：帽圆心/裁切半径/最大位移。
    # 帽从照片上裁圆（含龙猫贴纸），底座把帽擦掉留暗色沉孔
    STICKS = {
        "LS": {"cx": 272, "cy": 364, "r": 113, "disp": 40},
        "RS": {"cx": 874, "cy": 600, "r": 113, "disp": 40},
    }

    def __init__(self, canvas):
        self.cv = canvas
        self.btns = {}         # 名字 -> item id（独立贴图控件）
        self.drop0 = {}        # 名字 -> 贴图原始 y（按下下沉/扳机下压相对它）
        self.zones = []        # (name, x1, y1, x2, y2) 画布坐标热区
        self.knobs = {}        # 名字 -> (cap_id, x0, y0, disp) 摇杆帽滑动
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
        key = ("front", w, h)
        if key not in _PHOTO_CACHE:
            p = os.path.join(_base_dir(), "pad_front.jpg")
            img = Image.open(p).convert("RGB").resize((w, h), Image.LANCZOS)
            _PHOTO_CACHE[key] = ImageTk.PhotoImage(img)
        return _PHOTO_CACHE[key]

    @staticmethod
    def _load_top(w, h):
        """顶视图：裁掉白边按目标尺寸缩放，结果缓存"""
        from PIL import Image, ImageTk
        key = ("top", w, h)
        if key not in _PHOTO_CACHE:
            p = os.path.join(_base_dir(), "assets", "pad_top.png")
            img = Image.open(p).convert("RGB").crop(PadView.TOP_BBOX)
            img = img.resize((w, h), Image.LANCZOS)
            _PHOTO_CACHE[key] = ImageTk.PhotoImage(img)
        return _PHOTO_CACHE[key]

    @staticmethod
    def _tint_rgb(img, tint):
        """提亮+染色，tint: press(绿) / hl(琥珀)"""
        from PIL import Image, ImageEnhance
        rgb = img.convert("RGB")
        rgb = ImageEnhance.Brightness(rgb).enhance(1.30)
        col = Image.new("RGB", rgb.size,
                        C_PRESS if tint == "press" else C_HL)
        return Image.blend(rgb, col, 0.38 if tint == "press" else 0.45)

    @staticmethod
    def _btn_image(name, w, h, tint):
        """按键贴图三态：normal / press(亮+绿) / hl(琥珀)。裁自 assets/<名>.png"""
        from PIL import Image, ImageTk
        key = ("btn", name, w, h, tint)
        if key in _PHOTO_CACHE:
            return _PHOTO_CACHE[key]
        p = os.path.join(_base_dir(), "assets", name + ".png")
        img = Image.open(p).convert("RGBA")
        img = img.resize((max(1, w), max(1, h)), Image.LANCZOS)
        if tint:
            out = Image.merge("RGBA",
                              (*PadView._tint_rgb(img, tint).split(),
                               img.split()[3]))
        else:
            out = img
        ph = ImageTk.PhotoImage(out)
        _PHOTO_CACHE[key] = ph
        return ph

    @staticmethod
    def _top_overlay(name, w, h, tint):
        """顶视图上 LT/LB/RT/RB 的覆盖贴图：None=全透明占位，press/hl=染色裁块"""
        from PIL import Image, ImageTk
        key = ("topov", name, w, h, tint)
        if key in _PHOTO_CACHE:
            return _PHOTO_CACHE[key]
        if not tint:
            out = Image.new("RGBA", (max(1, w), max(1, h)), (0, 0, 0, 0))
        else:
            p = os.path.join(_base_dir(), "assets", "pad_top.png")
            img = Image.open(p).convert("RGB").crop(PadView.TOP_BBOX)
            x1, y1, x2, y2 = PadView.TOP_REGIONS[name]
            bx, by = PadView.TOP_BBOX[0], PadView.TOP_BBOX[1]
            img = img.crop((x1 - bx, y1 - by, x2 - bx, y2 - by))
            img = img.resize((max(1, w), max(1, h)), Image.LANCZOS)
            out = PadView._tint_rgb(img, tint).convert("RGBA")
        ph = ImageTk.PhotoImage(out)
        _PHOTO_CACHE[key] = ph
        return ph

    @staticmethod
    def _stick_images(name, w, h, tint):
        """摇杆帽贴图：照片裁圆 + 边缘羽化，tint 同 _btn_image。
        底座沉孔用 _stick_base 单独生成。"""
        from PIL import Image, ImageDraw, ImageTk
        key = ("cap", name, w, h, tint)
        if key in _PHOTO_CACHE:
            return _PHOTO_CACHE[key]
        g = PadView.STICKS[name]
        p = os.path.join(_base_dir(), "pad_front.jpg")
        photo = Image.open(p).convert("RGB")
        f = photo.width / float(PadView.IMG_W)     # 1365 -> 实际像素
        cx, cy, r = g["cx"] * f, g["cy"] * f, g["r"] * f
        img = photo.crop((int(cx - r), int(cy - r),
                          int(cx + r), int(cy + r)))
        img = img.resize((max(1, w), max(1, h)), Image.LANCZOS)
        # 圆形 alpha：不透明到 92%，最后 8% 用渐细的圆环描边羽化
        mask = Image.new("L", img.size, 0)
        d = ImageDraw.Draw(mask)
        rw, rh = img.size

        def _el(t):
            return [rw / 2 - rw / 2 * t, rh / 2 - rh / 2 * t,
                    rw / 2 + rw / 2 * t, rh / 2 + rh / 2 * t]

        d.ellipse(_el(0.92), fill=255)
        steps = 12
        wd = max(1, int(rw * 0.006))
        for i in range(steps):
            t = 0.92 + 0.08 * (i + 1) / steps
            d.ellipse(_el(t), outline=int(255 * (steps - i) / (steps + 1)),
                      width=wd)
        if tint:
            out = Image.merge("RGBA",
                              (*PadView._tint_rgb(img).split(), mask))
        else:
            out = Image.merge("RGBA", (*img.split(), mask))
        ph = ImageTk.PhotoImage(out)
        _PHOTO_CACHE[key] = ph
        return ph

    @staticmethod
    def _stick_base(name, w, h):
        """摇杆底座贴图：照片裁一块，把帽的位置擦成暗色沉孔。
        帽滑走时露出来的是沉孔，不是照片里那颗原帽。"""
        from PIL import Image, ImageDraw, ImageTk
        key = ("base", name, w, h)
        if key in _PHOTO_CACHE:
            return _PHOTO_CACHE[key]
        g = PadView.STICKS[name]
        p = os.path.join(_base_dir(), "pad_front.jpg")
        photo = Image.open(p).convert("RGB")
        f = photo.width / float(PadView.IMG_W)
        cx, cy, r = g["cx"] * f, g["cy"] * f, g["r"] * f
        br = int(r * 1.18)                     # 底座比帽大一圈，盖住擦除边
        img = photo.crop((int(cx - br), int(cy - br),
                          int(cx + br), int(cy + br)))
        img = img.resize((max(1, w), max(1, h)), Image.LANCZOS)
        # 沉孔颜色：从帽边缘外的缝隙里采样
        pts = []
        for ang in (45, 135, 225, 315):
            import math as _m
            a = _m.radians(ang)
            px = int(cx + 1.02 * r * _m.cos(a))
            py = int(cy + 1.02 * r * _m.sin(a))
            px = min(max(px, 0), photo.width - 1)
            py = min(max(py, 0), photo.height - 1)
            pts.append(photo.getpixel((px, py)))
        col = tuple(sum(c[i] for c in pts) // 4 for i in range(3))
        hole = Image.new("RGB", img.size, col)
        dr = ImageDraw.Draw(hole)
        # 沉孔 inner 圈再压暗一点，做出下凹感
        dk = tuple(max(0, c - 14) for c in col)
        rw = img.size[0]
        dr.ellipse([rw * 0.22, rw * 0.22, rw * 0.78, rw * 0.78], fill=dk)
        mask = Image.new("L", img.size, 0)
        dm = ImageDraw.Draw(mask)
        hr = g["r"] / (br * 2.0)               # 擦除半径占底座一半的比例
        dm.ellipse([rw * (0.5 - hr), rw * (0.5 - hr),
                    rw * (0.5 + hr), rw * (0.5 + hr)], fill=255)
        img.paste(hole, (0, 0), mask)
        ph = ImageTk.PhotoImage(img)
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
        cv = self.cv
        cv.delete("all")
        self.btns.clear()
        self.drop0.clear()
        self.zones = []
        self.knobs.clear()
        self._shake_off = (0, 0)

        try:
            cw, ch = int(cv["width"]), int(cv["height"])
        except Exception:
            cw, ch = self.CANVAS_W, self.CANVAS_H
        # 布局按 480x510 标定，画布不是这个尺寸（向导 560x370 等）就等比缩放居中
        k = min(cw / self.CANVAS_W, ch / self.CANVAS_H)
        ox = int((cw - self.CANVAS_W * k) // 2)
        oy = int((ch - self.CANVAS_H * k) // 2)

        # ---- 顶部：完整顶视图（扳机/肩键/USB-C 一张全出现）----
        tw = int(self.TOP_W * k)
        th = int(tw * (self.TOP_BBOX[3] - self.TOP_BBOX[1]) /
                 float(self.TOP_BBOX[2] - self.TOP_BBOX[0]))
        tx = ox + int(((self.CANVAS_W - self.TOP_W) / 2) * k)
        ty = oy + int(self.TOP_Y * k)
        cv.create_image(tx, ty, anchor="nw", image=self._load_top(tw, th))
        st = tw / float(self.TOP_BBOX[2] - self.TOP_BBOX[0])
        for name, (x1, y1, x2, y2) in self.TOP_REGIONS.items():
            ax = tx + (x1 - self.TOP_BBOX[0]) * st
            ay = ty + (y1 - self.TOP_BBOX[1]) * st
            aw, ah = int((x2 - x1) * st), int((y2 - y1) * st)
            it = cv.create_image(ax, ay, anchor="nw",
                                 image=self._top_overlay(name, aw, ah, None))
            self._reg(name, it, ax, ay, ax + aw, ay + ah)
            self.drop0[name] = ay

        # ---- 正面图：居中 ----
        pw = int(self.PAD_W * k)
        ph = int(self.IMG_H * (pw / self.IMG_W))
        px0 = ox + int(self.PAD_X * k)
        py0 = oy + int(self.PAD_Y * k)
        s = pw / self.IMG_W
        cv.create_image(px0, py0, anchor="nw",
                        image=self._load_photo(pw, ph))

        def X(x):
            return px0 + x * s

        def Y(y):
            return py0 + y * s

        def R(r):
            return r * s

        # ---- 摇杆：暗色沉孔底座 + 会滑动的帽 ----
        for name, g in self.STICKS.items():
            bw = int(2 * g["r"] * 1.18 * s)
            bx, by = X(g["cx"]) - bw / 2, Y(g["cy"]) - bw / 2
            cv.create_image(bx, by, anchor="nw",
                            image=self._stick_base(name, bw, bw))
            cw2 = int(2 * g["r"] * s)
            cap_x0, cap_y0 = X(g["cx"]) - cw2 / 2, Y(g["cy"]) - cw2 / 2
            cap = cv.create_image(cap_x0, cap_y0, anchor="nw",
                                  image=self._stick_images(name, cw2, cw2,
                                                           None))
            self.btns[name] = cap
            self.zones.append((name, X(g["cx"] - 118), Y(g["cy"] - 118),
                               X(g["cx"] + 118), Y(g["cy"] + 118)))
            self.drop0[name] = cap_y0
            self.knobs[name] = (cap, cap_x0, cap_y0, g["disp"] * s)

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
            w, h = self._size_of(name)
            img = self._image_of(name, w, h, tint)
            # 扳机随扣动深度下压最多 6px；普通按键按下下沉 1px；
            # 顶视图整图上的区域只亮绿不下沉
            if name in self.TOP_REGIONS:
                drop = 0
            elif name in ("LT", "RT"):
                drop = int(trig_v * 6)
            else:
                drop = 1 if on else 0
            ddx = ddy = 0
            if name in self.knobs:
                _, x0, y0, disp = self.knobs[name]
                axn = "LX" if name == "LS" else "RX"
                ayn = "LY" if name == "LS" else "RY"
                ddx = max(-1.0, min(1.0, a.get(axn, 0.0))) * disp
                ddy = -max(-1.0, min(1.0, a.get(ayn, 0.0))) * disp
                cv.coords(it, x0 + ddx + offx, y0 + drop + ddy + offy)
            else:
                x1, _, _y1, _ = self._zone_of(name)
                cv.coords(it, x1 + offx,
                          self.drop0.get(name, _y1) + drop + offy)
            cv.itemconfig(it, image=img)

    def _zone_of(self, name):
        for n, x1, y1, x2, y2 in self.zones:
            if n == name:
                return (x1, y1, x2, y2)
        return (0, 0, 0, 0)

    def _size_of(self, name):
        x1, y1, x2, y2 = self._zone_of(name)
        return int(x2 - x1), int(y2 - y1)

    def _image_of(self, name, w, h, tint):
        if name in self.STICKS:
            return self._stick_images(name, w, h, tint)
        if name in self.TOP_REGIONS:
            return self._top_overlay(name, w, h, tint)
        return self._btn_image(name, w, h, tint)


_PHOTO_CACHE = {}
