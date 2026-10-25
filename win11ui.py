"""Win11 风格组件：Mica 背景 + 深色标题栏 + 圆角卡片。

用法：
    import win11ui
    win11ui.apply(root)                 # 窗口级：Mica + 深色标题栏
    card = win11ui.Card(parent)         # 圆角卡片，往 card.body 里 pack
"""
import ctypes

try:
    import pywinstyles
except ImportError:
    pywinstyles = None

import tkinter as tk

# 窗口底色（这个颜色会被抠成透明，露出 Mica 背景；别在实心控件上用它）
HOLE = "#f2f3f7"


def apply(root, dark_header=True):
    """窗口级 Win11 化。失败静默（老系统没有 Mica 也能正常跑）"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    if pywinstyles is None:
        return
    try:
        pywinstyles.apply_style(root, "mica")
    except Exception:
        pass
    if dark_header:
        try:
            pywinstyles.change_header_color(root, "#2b2f36")
        except Exception:
            pass
    try:
        # 注意：抠色透光（set_opacity）实测会把 HOLE 色像素整个变成"透明洞"，
        # 桌面上别的窗口都透进来而且点击穿透，不能用。Mica 只在不透光区域
        # 生效的前提是 Tk 没有铺满底色，Tk 做不到，所以这里不上透光。
        pass
    except Exception:
        pass


class Card(tk.Frame):
    """圆角白卡片。children 往 self.body 里放，卡片大小随内容自动长。

    width 传了就锁宽（比如侧栏），否则完全跟着 body 内容走。
    """

    def __init__(self, master, radius=12, bg="#ffffff", outline="#e3e5ea",
                 pad=10, width=None, **kw):
        outer = master.cget("bg") if isinstance(master, tk.Widget) else HOLE
        super().__init__(master, bg=outer)
        self.radius, self.card_bg, self.outline, self.pad = radius, bg, outline, pad
        self._min_w = width
        self.cv = tk.Canvas(self, bg=outer, highlightthickness=0)
        self.cv.pack(fill="both", expand=True)
        self.body = tk.Frame(self.cv, bg=bg)
        self._win = self.cv.create_window(pad, pad, window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._on_body)
        self.cv.bind("<Configure>", self._on_cv)

    @staticmethod
    def _rr(x1, y1, x2, y2, r):
        # 圆角矩形多边形点集（与 padui._rr_pts 同款，这里独立一份免得互相依赖）
        pts = []
        import math as _m
        for cx, cy, a0, a1 in ((x2 - r, y1 + r, -90, 0), (x2 - r, y2 - r, 0, 90),
                               (x1 + r, y2 - r, 90, 180), (x1 + r, y1 + r, 180, 270)):
            for i in range(0, 91, 15):
                a = _m.radians(a0 + (a1 - a0) * i / 90)
                pts += [cx + r * _m.cos(a), cy + r * _m.sin(a)]
        return pts

    def _on_body(self, e):
        w = max(self._min_w or 0, e.width) + 2 * self.pad
        if abs(self.cv.winfo_reqwidth() - w) > 1:
            self.cv.configure(width=w, height=e.height + 2 * self.pad)

    def _on_cv(self, e=None):
        cv = self.cv
        ww, hh = cv.winfo_width(), cv.winfo_height()
        if ww > 2 * self.pad + 4:
            # 卡片被外层拉宽时，让内容跟着铺满（fill="x" 的行才不会缩在左边）
            cv.itemconfigure(self._win, width=ww - 2 * self.pad)
        cv.delete("cardbg")
        ww, hh = cv.winfo_width(), cv.winfo_height()
        if ww < 4 or hh < 4:
            return
        cv.create_polygon(self._rr(1, 1, ww - 1, hh - 1, self.radius),
                          fill=self.card_bg, outline=self.outline,
                          smooth=True, tags="cardbg")
        cv.tag_lower("cardbg")
